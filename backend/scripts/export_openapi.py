"""Write the API's OpenAPI schema (the phone app's typed client is generated from it).

uv run python scripts/export_openapi.py ../frontend/openapi.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

logging.disable(logging.WARNING)  # the dev-secret warning is irrelevant here
schema = create_app(Settings(frontend_dist="off")).openapi()
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
out.write_text(json.dumps(schema, indent=1, sort_keys=True) + "\n")
print(f"wrote {out}")
