"""Re-attach the held-out block to data/drill.json. `python -m receipts drill` rebuilds drill.json from the 11 original
canaries and drops this block. Run this afterwards:  python3 canaries/heldout/merge_into_drill.py"""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
d = json.loads((root / "data" / "drill.json").read_text())
d["held_out"] = json.loads((root / "data" / "drill_heldout.json").read_text())
(root / "data" / "drill.json").write_text(json.dumps(d, indent=2))
print("held_out merged:", d["held_out"]["planted"], "planted,", d["held_out"]["caught_by_union"], "caught; original", d["overall"]["planted"], "canaries untouched")
