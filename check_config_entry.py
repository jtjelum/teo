"""Tjek hvad HA har gemt i config entry for TEO."""
import subprocess
import json

result = subprocess.run(
    ["ssh", "teo-pi", "sudo cat /config/.storage/core.config_entries"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)

data = json.loads(result.stdout)
for e in data["data"]["entries"]:
    if e.get("domain") == "teo":
        print("TEO config entry data:")
        print(json.dumps(e.get("data", {}), indent=2))
