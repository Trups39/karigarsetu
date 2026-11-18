"""Run the agent scenarios in agent_eval/cases.json against the REAL Claude.

    cd backend
    python -m agent_eval.run            all scenarios
    python -m agent_eval.run S1 B3      only these
    python -m agent_eval.run --list     list the scenarios

Safe: it uses its own temporary SQLite database with the sample data (never your real database),
and WhatsApp sending is switched off. It uses ANTHROPIC_API_KEY and CLAUDE_MODEL from backend/.env,
so it costs a little Claude usage (about 1-3 calls per message).

Writes a report to agent_eval/reports/report-<date>.md with every message, reply and check.
"""
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---- test settings, before the app is imported (real environment / .env can't override these) ----
_tmp = tempfile.mkdtemp(prefix="ks-agent-eval-")
os.environ.update({
    "DATABASE_URL": "sqlite:///" + os.path.join(_tmp, "eval.db"),
    "SAMPLE_MAKERS": "true", "SEED_DEMO_ORDERS": "true", "DEMO_TODAY": "2026-11-16",
    "WHATSAPP_PROVIDER": "none",          # never send real WhatsApp messages from a test
    "SMTP_USERNAME": "", "SMTP_PASSWORD": "",   # and no real email
    "DEMO_RETAILER_PHONE": "", "INTERNAL_API_KEY": "agent-eval-key", "ADMIN_PASSWORD": "eval-only",
})

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import config, i18n  # noqa: E402
from app import seed as seed_mod  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Maker, Order, OrderLine, Product, Stock  # noqa: E402

# Only warnings and errors from the app here; the per-call token lines would mix into the pass/FAIL output.
logging.getLogger("karigarsetu").setLevel(logging.WARNING)
logging.getLogger("karigarsetu.agent").setLevel(logging.WARNING)

HEADERS = {"X-Internal-Key": "agent-eval-key"}
DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
GREEN, RED, DIM, END = ("\033[32m", "\033[31m", "\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "", "", "")


def norm(text: str) -> str:
    return (text or "").translate(DEV_DIGITS).lower()


def language_of(text: str) -> str:
    return "English" if not re.search(r"[ऀ-ॿ]", text or "") else i18n.detect(text)


# ---------- reading the database ----------

def snapshot(s: Session) -> dict:
    return {o.code: (o.status, o.price_per_pair, o.due_date) for o in s.exec(select(Order))}


def newest_order(s: Session):
    return s.exec(select(Order).order_by(Order.id.desc())).first()


def order_fields(s: Session, o: Order) -> dict:
    p = s.get(Product, o.product_id)
    return {"code": o.code, "maker": s.get(Maker, o.maker_id).name, "design": p.code, "status": o.status.value,
            "price_per_pair": o.price_per_pair,
            "total_pairs": sum(ln.qty for ln in s.exec(select(OrderLine).where(OrderLine.order_id == o.id))),
            "proposed_date": o.proposed_date.isoformat() if o.proposed_date else None,
            "due_date": o.due_date.isoformat() if o.due_date else None}


def maker_by_name(s: Session, name: str) -> Maker:
    m = s.exec(select(Maker).where(Maker.name == name)).first()
    if not m:
        raise ValueError(f"No maker called {name}")
    return m


def product_of(s: Session, maker: str, design: str) -> Product:
    m = maker_by_name(s, maker)
    p = s.exec(select(Product).where(Product.maker_id == m.id, Product.code == design)).first()
    if not p:
        raise ValueError(f"{maker} has no design {design}")
    return p


# ---------- checks ----------

def check_step(s: Session, exp: dict, reply: str, before: dict, last: str | None) -> list[tuple[bool, str]]:
    sub = lambda v: v.replace("{last}", last or "?") if isinstance(v, str) else v  # noqa: E731
    out = []
    after = snapshot(s)
    created = sorted(set(after) - set(before))
    r = norm(reply)

    if not reply.strip() and not exp.get("empty_reply_ok"):
        out.append((False, "reply is empty"))
    if "new_order" in exp:
        ok = bool(created) == exp["new_order"]
        out.append((ok, f"new order: expected {'yes' if exp['new_order'] else 'no'}, got "
                        f"{', '.join(created) if created else 'none'}"))
    if exp.get("orders_unchanged"):
        changed = [c for c in after if before.get(c) != after[c]]
        out.append((not changed, "orders unchanged" if not changed else f"orders changed: {', '.join(changed)}"))
    for key in ("order", "order_if_created"):
        if key in exp:
            if key == "order_if_created" and not created:
                out.append((True, "no order created (price check not needed)"))
                continue
            o = s.exec(select(Order).where(Order.code == last)).first() if last else None
            if not o:
                out.append((False, f"{key}: no order created in this scenario to check"))
                continue
            got = order_fields(s, o)
            for f, want in exp[key].items():
                out.append((got.get(f) == want, f"{got.get('code', 'order')}.{f}: expected {want}, got {got.get(f)}"))
    for code, want in (exp.get("status") or {}).items():
        if "{last}" in code and not last:
            out.append((False, "status: no order created in this scenario to check"))
            continue
        code = sub(code)
        o = s.exec(select(Order).where(Order.code == code)).first()
        got = o.status.value if o else "missing"
        out.append((got == want, f"{code} status: expected {want}, got {got}"))
    for st in exp.get("stock") or []:
        p = product_of(s, st["maker"], st["design"])
        row = s.exec(select(Stock).where(Stock.product_id == p.id, Stock.size == st["size"])).first()
        got = row.ready if row else 0
        out.append((got == st["ready"], f"stock {st['design']} size {st['size']}: expected {st['ready']}, got {got}"))
    if "product" in exp:
        want = dict(exp["product"])
        p = product_of(s, want.pop("maker"), want.pop("design"))
        for f, v in want.items():
            out.append((getattr(p, f) == v, f"{p.code}.{f}: expected {v}, got {getattr(p, f)}"))
    if "maker" in exp:
        want = dict(exp["maker"])
        m = maker_by_name(s, want.pop("name"))
        for f, v in want.items():
            out.append((getattr(m, f) == v, f"{m.name}.{f}: expected {v}, got {getattr(m, f)}"))
    if exp.get("reply_any"):
        words = [sub(w) for w in exp["reply_any"]]
        out.append((any(norm(w) in r for w in words), f"reply mentions one of {words}"))
    if exp.get("reply_all"):
        words = [sub(w) for w in exp["reply_all"]]
        missing = [w for w in words if norm(w) not in r]
        out.append((not missing, f"reply mentions all of {words}" + (f" (missing {missing})" if missing else "")))
    if exp.get("reply_none"):
        found = [sub(w) for w in exp["reply_none"] if norm(sub(w)) in r]
        out.append((not found, "reply avoids " + str(exp["reply_none"]) + (f" (found {found})" if found else "")))
    if "language" in exp:
        got = language_of(reply)
        out.append((got == exp["language"], f"language: expected {exp['language']}, got {got} (a guess)"))
    return out


# ---------- running ----------

def fresh_database() -> None:
    seed_mod.reset()
    with Session(engine) as s:
        seed_mod.seed(s)


def setup_order(client: TestClient, spec: dict, phones: dict) -> str:
    with Session(engine) as s:
        m = maker_by_name(s, spec["maker"])
    body = {"maker_id": m.id, "product_code": spec["design"], "retailer_name": spec.get("shop_name", "Pune Footwear House"),
            "retailer_phone": phones["shop"], "city": "Pune", "language": "Marathi",
            "lines": [{"size": int(k), "qty": v} for k, v in spec["lines"].items()]}
    r = client.post("/internal/orders", json=body, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"setup_order failed: {r.text}")
    return r.json()["order"]["code"]


def run_scenario(client: TestClient, sc: dict, phones: dict, real_key: str) -> dict:
    fresh_database()
    mode = sc.get("claude", True)
    config.ANTHROPIC_API_KEY = "" if mode is False else ("sk-ant-wrong-key" if mode == "bad_key" else real_key)
    agent_log = logging.getLogger("karigarsetu.agent")
    agent_log.disabled = mode == "bad_key"   # the expected "invalid key" error would only clutter the output
    last, results = None, []
    try:
        for step in sc["steps"]:
            if "setup_order" in step:
                last = setup_order(client, step["setup_order"], phones)
                results.append({"setup": f"created pending order {last}", "checks": []})
                continue
            say = step["say"].replace("{last}", last or "?")
            phone = phones[step["from"]]
            with Session(engine) as s:
                before = snapshot(s)
            t0 = time.time()
            resp = client.post("/internal/simulate-message", json={"phone": phone, "body": say}, headers=HEADERS)
            secs = time.time() - t0
            reply = resp.json().get("reply", "") if resp.status_code == 200 else f"HTTP {resp.status_code}: {resp.text}"
            with Session(engine) as s:
                if set(snapshot(s)) - set(before):
                    last = newest_order(s).code
                checks = [(resp.status_code == 200, f"HTTP {resp.status_code}")]
                checks += check_step(s, step.get("expect", {}), reply, before, last)
            results.append({"from": step["from"], "say": say, "reply": reply, "secs": secs, "checks": checks})
    except Exception as e:  # noqa: BLE001
        results.append({"error": f"{type(e).__name__}: {e}", "checks": [(False, "scenario crashed")]})
    finally:
        config.ANTHROPIC_API_KEY = real_key
        agent_log.disabled = False
    passed = all(ok for r in results for ok, _ in r["checks"])
    return {"id": sc["id"], "name": sc["name"], "passed": passed, "steps": results}


def write_report(runs: list[dict]) -> Path:
    (HERE / "reports").mkdir(exist_ok=True)
    path = HERE / "reports" / f"report-{datetime.now():%Y%m%d-%H%M%S}.md"
    ok = sum(r["passed"] for r in runs)
    lines = [f"# Agent test report, {datetime.now():%d %b %Y %H:%M}", "",
             f"Model: `{config.CLAUDE_MODEL}` · **{ok}/{len(runs)} scenarios passed**", "",
             "| Scenario | Result |", "|---|---|"]
    lines += [f"| {r['id']} {r['name']} | {'✅ pass' if r['passed'] else '❌ FAIL'} |" for r in runs]
    for r in runs:
        lines += ["", f"## {r['id']}: {r['name']} {'✅' if r['passed'] else '❌'}"]
        for st in r["steps"]:
            if "setup" in st:
                lines.append(f"- _Setup: {st['setup']}_")
                continue
            if "error" in st:
                lines.append(f"- **Error:** {st['error']}")
                continue
            lines += ["", f"**{st['from']}:** {st['say']}", "",
                      "> " + (st["reply"] or "(empty reply)").replace("\n", "\n> "), "",
                      f"_{st['secs']:.1f}s_"]
            lines += [f"- {'✅' if okk else '❌'} {msg}" for okk, msg in st["checks"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    data = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    scenarios, phones = data["scenarios"], data["phones"]
    if "--list" in argv:
        for sc in scenarios:
            print(f"{sc['id']:4} {sc['name']}")
        return 0
    wanted = {a.upper() for a in argv if not a.startswith("-")}
    if wanted:
        scenarios = [sc for sc in scenarios if sc["id"].upper() in wanted]
    real_key = config.ANTHROPIC_API_KEY
    if not real_key:
        print("ANTHROPIC_API_KEY is empty in backend/.env: only the 'Claude off' scenarios will pass.")
    print(f"Running {len(scenarios)} scenario(s) with {config.CLAUDE_MODEL}. Test database: {_tmp}\n")
    runs = []
    with TestClient(app) as client:
        for sc in scenarios:
            print(f"{sc['id']:4} {sc['name']} ... ", end="", flush=True)
            run = run_scenario(client, sc, phones, real_key)
            runs.append(run)
            print(f"{GREEN}pass{END}" if run["passed"] else f"{RED}FAIL{END}")
            if not run["passed"]:
                for st in run["steps"]:
                    for okk, msg in st["checks"]:
                        if not okk:
                            where = f"\"{st.get('say', '')[:50]}\"" if "say" in st else st.get("error", "")
                            print(f"     {RED}✗{END} {msg}  {DIM}{where}{END}")
    path = write_report(runs)
    ok = sum(r["passed"] for r in runs)
    print(f"\n{ok}/{len(runs)} scenarios passed. Full replies: {path}")
    return 0 if ok == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
