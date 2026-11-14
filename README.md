# Receipts

Review of agent-written pull requests by claims and evidence. Junction 2026, Tieto challenge "Earned Trust in AI Code". Runs against the `ju26-issue-*` branches of Tieto's MessagePack-CSharp copy.

## Run

Python 3.12, `pip install -r requirements.txt`. Replay works offline with no API key.

```bash
python -m receipts demo                      # serve the walkthrough on localhost
python -m receipts review --change 2283      # also 2234, 2297, 2129
python -m receipts pr-comment --change 2283
```

You can also open `web/index.html` directly. `P` starts presenter mode.

## Layout

| Path | Contents |
|---|---|
| `web/` | Walkthrough UI |
| `runs/<change>/` | Evidence: test logs, claims, refusals, receipts |
| `data/` | Canary drill, baseline, backtest, cost, synthetic ledger |
| `receipts/` | Python package |
| `requirements/`, `policy/`, `canaries/` | Inputs |
| `integration/` | Reference GitHub workflow (never run) |
| `docs/` | Concept card, deck, logs, Q&A |

`runs/2283/receipt.*` is a rehearsal receipt, not a real sign-off. The ledger history is synthetic.
