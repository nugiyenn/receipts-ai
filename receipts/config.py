"""Paths and settings. Everything is local; nothing here talks to the network."""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent                       # .../receipts
REPO = Path(os.environ.get("RECEIPTS_REPO", ROOT.parent / "repo")).resolve()
RUNS = ROOT / "runs"
DATA = ROOT / "data"
POLICY = ROOT / "policy"
REQS = ROOT / "requirements"
WEB = ROOT / "web"
DOCS = ROOT / "docs"
CANARIES = ROOT / "canaries"

# change id -> branch holding the single agent-written commit on top of BASE_PARENT
BRANCHES = {
    "2283": "origin/ju26-issue-2283",
    "2234": "origin/ju26-issue-2234",
    "2129": "origin/ju26-issue-2129",
    "2297": "origin/ju26-issue-2297",
}

OWNER_NAME = os.environ.get("OWNER_NAME", "OWNER_NAME")   # placeholder until the presenter is chosen
REPLAY = os.environ.get("RECEIPTS_MODE", "replay") == "replay"
DEMO_PORT = int(os.environ.get("RECEIPTS_PORT", "8765"))

LANE_ORDER = ["L0", "L1", "L2", "L3"]


def run_dir(change_id: str) -> Path:
    d = RUNS / str(change_id)
    d.mkdir(parents=True, exist_ok=True)
    return d
