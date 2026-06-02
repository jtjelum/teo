"""Test cloud upload direkte fra Pi via SSH."""
import subprocess

script = """
import asyncio, yaml, sys
sys.path.insert(0, '/config/custom_components/teo')

with open('/config/teo_config.yaml') as f:
    config = yaml.safe_load(f)

from cloud_uploader import CloudUploader
from datetime import date

uploader = CloudUploader(config, db_path='/config/teo_data.db')

inst = config.get('installation', {})
mode = inst.get('mode', 'local')
installation_id = inst.get('id', 'unknown')

print(f'Mode: {mode}')
print(f'Installation ID: {installation_id}')
print(f'Is enabled: {uploader.is_enabled(mode)}')

if uploader.is_enabled(mode):
    payload = uploader.build_payload(installation_id, mode, date(2026, 6, 1))
    print(f'Payload installation_id: {payload.get(\"installation_id\")}')
    print(f'Payload date: {payload.get(\"date\")}')
    print(f'Payload zone: {payload.get(\"zone\")}')
    
    import urllib.request, json, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        'https://api.tjelum.dk/v1/telemetry',
        data=body, method='POST',
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            print(f'API svar: {resp.read().decode()}')
    except Exception as e:
        print(f'FEJL: {e}')
else:
    print('Upload ikke aktiveret')
"""

result = subprocess.run(
    ["ssh", "teo-pi", f"python3 << 'PYEOF'\n{script}\nPYEOF"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:500])
