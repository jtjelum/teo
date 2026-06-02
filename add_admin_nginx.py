"""Tilføj /admin location til nginx teo-api config."""
import subprocess

new_location = """    location /admin {
        proxy_pass http://127.0.0.1:8050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    # Block robots"""

# Læs nuværende config
result = subprocess.run(
    ["ssh", "teo-hetzner", "cat /etc/nginx/sites-enabled/teo-api"],
    capture_output=True, text=True, encoding="utf-8"
)
content = result.stdout

# Erstat
new_content = content.replace("    # Block robots", new_location)

# Skriv tilbage
proc = subprocess.run(
    ["ssh", "teo-hetzner", "sudo tee /etc/nginx/sites-enabled/teo-api > /dev/null"],
    input=new_content, text=True, encoding="utf-8"
)

if proc.returncode == 0:
    # Test og reload
    result2 = subprocess.run(
        ["ssh", "teo-hetzner", "sudo nginx -t && sudo systemctl reload nginx"],
        capture_output=True, text=True, encoding="utf-8"
    )
    print(result2.stdout)
    print(result2.stderr)
else:
    print("FEJL ved skrivning")
