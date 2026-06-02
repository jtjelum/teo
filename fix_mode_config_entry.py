"""Ret mode til self_hosted i HA's config entry for TEO."""
import subprocess
import json

result = subprocess.run(
    ["ssh", "teo-pi", "sudo cat /config/.storage/core.config_entries"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)

data = json.loads(result.stdout)
changed = False
for e in data["data"]["entries"]:
    if e.get("domain") == "teo":
        before = e["data"]["installation"]["mode"]
        e["data"]["installation"]["mode"] = "self_hosted"
        print(f"Ændret mode: {before} -> self_hosted")
        changed = True

if changed:
    new_content = json.dumps(data)
    proc = subprocess.run(
        ["ssh", "teo-pi", "sudo tee /config/.storage/core.config_entries > /dev/null"],
        input=new_content, text=True, encoding="utf-8"
    )
    if proc.returncode == 0:
        print("Gemt. Genstart HA for at aktivere.")
    else:
        print("FEJL ved skrivning")
else:
    print("Ingen TEO config entry fundet")
