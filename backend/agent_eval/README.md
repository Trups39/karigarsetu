# Agent tests (real Claude)

Checks that the Sales Agent and Operations Agent do the right thing, by sending WhatsApp-style
messages and checking the **database** afterwards (order created or not, status, price, stock),
not only the reply text.

```powershell
cd E:\karigarsetu\backend
python -m agent_eval.run            # all scenarios (about 26; takes a few minutes)
python -m agent_eval.run S1 S7      # only some
python -m agent_eval.run --list     # list them
```

- **Safe:** each scenario starts from a fresh temporary SQLite database with the sample data
  (Kolhapur Chappal Kendra, Patil Chappal Udyog, sample shops, past orders KS-1036 to KS-1040).
  Your real database and WhatsApp are never touched.
- **Uses your Claude key** (`ANTHROPIC_API_KEY` and `CLAUDE_MODEL` from `backend/.env`): roughly
  1-3 Claude calls per message.
- **Report:** `agent_eval/reports/report-<date>.md` has every message, the full reply and every check.

## Adding a case
Edit `cases.json` (the `_help` at the top lists every option). Example:

```json
{"id": "S20", "name": "Hinglish order",
 "steps": [{"from": "shop", "say": "Kolhapur Chappal Kendra se Paytan 30 pair chahiye, size 8",
            "expect": {"new_order": true, "order": {"design": "paytan", "total_pairs": 30}}}]}
```

## Reading results
Claude's wording changes from run to run, so the checks look at **what happened** (database) first,
and only at a few words in the reply. If a case fails, open the report and read the reply: either
the agent made a real mistake (tell Claude in chat), or the case expects too much (adjust it).
`language` is only a guess from common words.
