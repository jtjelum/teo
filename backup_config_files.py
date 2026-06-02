"""Kopier TEO config-filer til git-mappen og commit."""
import subprocess

files = [
    ("/config/teo_dashboard.yaml", "teo_dashboard.yaml"),
    ("/config/automations_teo_logsystem.yaml", "automations_teo_logsystem.yaml"),
    ("/config/get_match_rate.py", "get_match_rate.py"),
    ("/config/teo_read_report.py", "teo_read_report.py"),
    ("/config/teo_read_report.sh", "teo_read_report.sh"),
    ("/config/configuration.yaml", "configuration.yaml"),
    ("/config/teo_user_settings.yaml", "teo_user_settings.yaml"),
]

GIT_PATH = "/config/custom_components/teo"

for src, dst in files:
    result = subprocess.run(
        ["ssh", "teo-pi", f"sudo cp {src} {GIT_PATH}/{dst} 2>/dev/null && echo OK || echo SKIP: {src}"],
        capture_output=True, text=True, encoding="utf-8"
    )
    print(f"{dst}: {result.stdout.strip()}")

# Commit
result = subprocess.run(
    ["ssh", "teo-pi", f"sudo git -C {GIT_PATH} add . && sudo git -C {GIT_PATH} commit -m 'Tilfoej config-filer til git backup'"],
    capture_output=True, text=True, encoding="utf-8"
)
print("\nGit commit:")
print(result.stdout.strip())
