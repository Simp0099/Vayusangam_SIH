import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.engine import get_replay

out = Path(__file__).resolve().parents[1] / "demo" / "replay" / "delhi-winter-stagnation.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(get_replay(), indent=2))
print(f"Wrote deterministic demo replay: {out}")
