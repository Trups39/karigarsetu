"""Shared Claude tool-use loop for both agents (Sales and Operations).

One call to run_agent_loop() handles one incoming WhatsApp message: it loads this person's chat memory,
calls Claude, runs any tools Claude asks for, and saves the memory again. If Claude fails, the person
gets a polite message instead of an error. Prompt caching keeps repeated calls cheap and fast.
"""
import json
import logging

from sqlmodel import Session

from ..core import config
from ..core.models import Conversation, utcnow

log = logging.getLogger("karigarsetu.agent")


def _trim(history: list, keep: int = 30) -> list:
    """Keep recent turns, starting on a plain user text message so tool_use/tool_result pairs stay intact."""
    if len(history) <= keep:
        return history
    for i in range(len(history) - keep, len(history)):
        m = history[i]
        if m["role"] == "user" and isinstance(m["content"], str):
            return history[i:]
    return history[-1:]


def whatsapp_format(text: str) -> str:
    """Turn website-style markdown into WhatsApp style: **bold** -> *bold*, drop # headings."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return text


def _clean_block(b) -> dict:
    """Keep only the fields the API accepts back as input (newer SDKs add extra output-only fields).
    Thinking blocks are passed back unchanged within a turn, as the API requires."""
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if b.type == "thinking":
        return {"type": "thinking", "thinking": b.thinking, "signature": b.signature}
    if b.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": b.data}
    return b.model_dump(exclude_none=True)


def _for_memory(history: list) -> list:
    """What we keep between messages: no thinking blocks. They are tied to the exact instructions and
    tools of the reply that made them, and the API allows dropping them from earlier turns."""
    out = []
    for m in history:
        content = m["content"]
        if isinstance(content, list):
            content = [c for c in content if c.get("type") not in ("thinking", "redacted_thinking")]
            if not content:
                continue
        out.append({"role": m["role"], "content": content})
    return out


CACHE = {"type": "ephemeral"}


def _cached_request(system: str, tools: list, history: list) -> dict:
    """Prompt caching: mark the tools, the system prompt and the conversation so far as cacheable.
    The next call (the next step of the tool loop, or the person's next message within a few minutes)
    re-reads them from Anthropic's cache: cheaper and faster. The saved history is not changed."""
    tools_c = [dict(t) for t in tools]
    if tools_c:
        tools_c[-1]["cache_control"] = CACHE
    messages = [dict(m) for m in history]
    if messages:
        last = messages[-1]
        content = last["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
        if blocks:
            blocks[-1]["cache_control"] = CACHE
            messages[-1] = {"role": last["role"], "content": blocks}
    return {"system": [{"type": "text", "text": system, "cache_control": CACHE}], "tools": tools_c,
            "messages": messages}


def _log_usage(resp) -> None:
    u = getattr(resp, "usage", None)
    if u is not None:
        log.info("Claude tokens: input %s, cache read %s, cache write %s, output %s",
                 getattr(u, "input_tokens", "?"), getattr(u, "cache_read_input_tokens", 0),
                 getattr(u, "cache_creation_input_tokens", 0), getattr(u, "output_tokens", "?"))


NUDGE = ("(Note from the system, not the customer: you ended without a message. Write your WhatsApp reply "
         "to the person now, in their language.)")


def _converse(client, system: str, tools: list, history: list, execute) -> str | None:
    """One user turn: call Claude, run any tools it asks for, until it answers. None = gave up.
    If Claude stops without any text (it ran out of room, or forgot), it is asked once for the reply."""
    nudged = False
    for _ in range(8):   # tool-use loop
        resp = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=config.CLAUDE_MAX_TOKENS,
                                      **_cached_request(system, tools, history))
        _log_usage(resp)
        if resp.stop_reason == "max_tokens":   # cut off: a half-written tool call can't be sent back
            log.warning("Claude hit max_tokens (%s); asking for the reply again", config.CLAUDE_MAX_TOKENS)
            blocks = [b for b in resp.content if b.type == "text"]
        else:
            blocks = list(resp.content)
        if blocks:
            history.append({"role": "assistant", "content": [_clean_block(b) for b in blocks]})
        if resp.stop_reason != "tool_use":
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if text and resp.stop_reason != "max_tokens":
                return whatsapp_format(text)
            if nudged:
                return whatsapp_format(text) if text else None
            nudged = True
            history.append({"role": "user", "content": NUDGE})
            continue
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = execute(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)})
        history.append({"role": "user", "content": results})
    return None


def run_agent_loop(session: Session, phone: str, text: str, system: str, tools: list, execute,
                   give_up: str, memory: str = "sales") -> str:
    """Shared Claude tool-use loop for both agents. execute(name, args) -> dict runs one tool.

    Chat memory is kept per agent and phone ("sales:<phone>" / "ops:<phone>") in the Conversation table.
    If anything fails, the person gets a polite message instead of an error, and the details go to the
    server log. If Claude rejects the saved history (status 400), it is cleared and the message retried once.
    """
    import anthropic

    key = f"{memory}:{phone}"   # separate memory per agent, so a number that changes role never mixes chats
    conv = session.get(Conversation, key) or Conversation(phone=key)
    saved = _for_memory(json.loads(conv.history))
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    history, reply = None, None
    for attempt, start in enumerate((saved, [])):
        history = start + [{"role": "user", "content": text}]
        try:
            reply = _converse(client, system, tools, history, execute)
            break
        except Exception as e:   # noqa: BLE001  (never crash the webhook)
            status = getattr(e, "status_code", None)
            if attempt == 0 and status == 400 and saved:
                log.warning("Claude rejected saved history for %s (%s); retrying with a fresh chat", phone, e)
                continue
            log.exception("Agent failed for %s", phone)
            session.rollback()
            return give_up

    if reply is None:
        reply = give_up
    conv = session.get(Conversation, key) or Conversation(phone=key)   # re-fetch: a tool may have rolled back
    conv.history = json.dumps(_trim(_for_memory(history)), default=str)
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()
    return reply or "👍"
