"""TEO Config Sync — kør dette inden git pull for at sikre backup af config-filer.

Hvad scriptet gør:
1. Kopierer config-filer fra /config/ til git-mappen på Pi
2. Committer hvis der er ændringer
3. Puller til lokal C:\teo_git
"""
import subprocess
import sys

FILES = [
    ("/config/teo_dashboard.yaml", "teo_dashboard.yaml"),
    ("/config/automations_teo_logsystem.yaml", "automations_teo_logsystem.yaml"),
    ("/config/get_match_rate.py", "get_match_rate.py"),
    ("/config/teo_read_report.py", "teo_read_report.py"),
    ("/config/teo_read_report.sh", "teo_read_report.sh"),
    ("/config/configuration.yaml", "configuration.yaml"),
    ("/config/teo_user_settings.yaml", "teo_user_settings.yaml"),
]

GIT_PATH = "/config/custom_components/teo"

print("TEO Config Sync")
print("-" * 40)

# Kopier filer til git-mappen
for src, dst in FILES:
    result = subprocess.run(
        ["ssh", "teo-pi", f"sudo cp {src} {GIT_PATH}/{dst} 2>/dev/null && echo OK || echo SKIP"],
        capture_output=True, text=True, encoding="utf-8"
    )
    status = result.stdout.strip()
    print(f"  {dst}: {status}")

# Check om der er noget at committe
result = subprocess.run(
    ["ssh", "teo-pi", f"sudo git -C {GIT_PATH} status --porcelain"],
    capture_output=True, text=True, encoding="utf-8"
)

if result.stdout.strip():
    # Der er ændringer — commit
    result = subprocess.run(
        ["ssh", "teo-pi", f"sudo git -C {GIT_PATH} add . && sudo git -C {GIT_PATH} commit -m 'Sync config-filer'"],
        capture_output=True, text=True, encoding="utf-8"
    )
    print(f"\nCommit: {result.stdout.strip()}")
else:
    print("\nIngen ændringer — intet at committe.")

# Git pull lokalt
print("\nPuller til lokal mappe...")
result = subprocess.run(
    ["git", "pull", "teo-pi", "master"],
    capture_output=True, text=True, encoding="utf-8",
    cwd="C:\\teo_git"
)
print(result.stdout.strip())
if result.returncode != 0:
    print("FEJL ved pull:", result.stderr.strip())
    sys.exit(1)

print("\nSync faerdig.")
