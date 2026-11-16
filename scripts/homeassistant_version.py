"""Print the Home Assistant version declared in hacs.json."""

import json
from pathlib import Path


manifest = json.loads((Path(__file__).parent.parent / "hacs.json").read_text())
version = manifest.get("homeassistant")
if not isinstance(version, str) or not version:
    raise SystemExit("hacs.json must declare a Home Assistant version")

print(version)
