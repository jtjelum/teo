"""Skriv en ren nginx config for teo-api direkte."""
import subprocess

clean_config = r"""server {
    listen 443 ssl;
    server_name api.tjelum.dk;
    ssl_certificate /etc/letsencrypt/live/api.tjelum.dk/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/api.tjelum.dk/privkey.pem; # managed by Certbot
    location / {
        proxy_pass http://127.0.0.1:8051;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /admin {
        proxy_pass http://127.0.0.1:8050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location = /robots.txt {
        add_header Content-Type text/plain;
        return 200 "User-agent: *\nDisallow: /\n";
    }
}
server {
    if ($host = api.tjelum.dk) {
        return 301 https://$host$request_uri;
    } # managed by Certbot
    listen 80;
    server_name api.tjelum.dk;
    return 301 https://$host$request_uri;
}
"""

proc = subprocess.run(
    ["ssh", "teo-hetzner", "sudo tee /etc/nginx/sites-enabled/teo-api > /dev/null"],
    input=clean_config, text=True, encoding="utf-8"
)

if proc.returncode == 0:
    result = subprocess.run(
        ["ssh", "teo-hetzner", "sudo nginx -t && sudo systemctl reload nginx && echo OK"],
        capture_output=True, text=True, encoding="utf-8"
    )
    print(result.stdout)
    print(result.stderr)
else:
    print("FEJL ved skrivning")
