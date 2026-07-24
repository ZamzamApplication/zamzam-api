"""Export the FastAPI contract for web/mobile TypeScript generation."""
import json
import sys
from pathlib import Path

from app.main import app


if len(sys.argv) != 2:
    raise SystemExit("usage: python scripts/export_openapi.py OUTPUT.json")

output = Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
