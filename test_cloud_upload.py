"""Test cloud upload direkte mod api.tjelum.dk."""
import subprocess
import json

# Test at api.tjelum.dk modtager en minimal payload
result = subprocess.run(
    ["ssh", "teo-pi", """curl -s -X POST https://api.tjelum.dk/v1/telemetry \
-H 'Content-Type: application/json' \
-d '{"installation_id":"test","date":"2026-06-02","teo_version":"1.0.0","zone":"DK2"}'"""],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print("API svar:", result.stdout)

# Tjek om data kom frem på Hetzner
result2 = subprocess.run(
    ["ssh", "teo-hetzner", "sqlite3 /opt/teo/data_commons/commons.db 'SELECT COUNT(*) FROM telemetry;'"],
    capture_output=True, text=True, encoding="utf-8"
)
print("Antal rækker i Hetzner DB:", result2.stdout.strip())
