"""Tjek hvad coordinator læser fra teo_config.yaml."""
import subprocess

result = subprocess.run(
    ["ssh", "teo-pi", "python3 -c 'import yaml; c=yaml.safe_load(open(\"/config/teo_config.yaml\")); print(c.get(\"installation\",{}))'"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print("Installation sektion:", result.stdout)
if result.stderr:
    print("Fejl:", result.stderr[:200])
