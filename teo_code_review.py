"""
TEO Kode-review via lokal Ollama (qwen2.5-coder:14b)
Henter alle Python-filer fra Pi via SSH og sender til Qwen til review.
Output: fejlliste i /teo_review_YYYY-MM-DD.txt

Krav:
- Ollama kørende lokalt med qwen2.5-coder:14b
- SSH-adgang til teo-pi (ssh teo-pi skal virke)
- pip install paramiko requests
"""

import subprocess
import requests
import json
from datetime import datetime
from pathlib import Path

# --- Konfiguration ---
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5-coder:14b"
PI_HOST = "teo-pi"
TEO_PATH = "/config/custom_components/teo"
OUTPUT_FILE = f"teo_review_{datetime.now().strftime('%Y-%m-%d')}.txt"

# Filer der skal reviewes (tilføj/fjern efter behov)
FILES_TO_REVIEW = [
    "__init__.py",
    "coordinator.py",
    "data_collector.py",
    "decision_tracker.py",
    "analyse_decisions.py",
    "cloud_uploader.py",
    "number.py",
    "switch.py",
    "sensor.py",
    "const.py",
    "version.py",
    "user_settings.py",
]

REVIEW_PROMPT = """Du er en senior Python-udvikler der reviewer Home Assistant custom integration kode.

Analyser følgende fil og returner KUN en nummereret liste med:
1. Syntaksfejl eller logikfejl
2. Steder hvor en fejl kan crashe integrationen
3. Manglende try/except på kritiske operationer
4. Inkonsistenser med andre filer (hvis du kender dem)
5. Hardcodede værdier der burde være konstanter

Vær præcis: angiv linjenummer og hvad problemet er.
Hvis ingen problemer: skriv "Ingen problemer fundet."

Fil: {filename}
---
{code}
"""


def fetch_file_from_pi(filename):
    """Hent fil fra Pi via SSH."""
    result = subprocess.run(
        ["ssh", PI_HOST, f"cat {TEO_PATH}/{filename}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30
    )
    if result.returncode != 0:
        return None, f"Fejl: {result.stderr}"
    return result.stdout, None


def review_file_with_ollama(filename, code):
    """Send fil til Ollama og få review tilbage."""
    prompt = REVIEW_PROMPT.format(filename=filename, code=code)
    
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Lav temperatur = mere deterministisk
                "num_predict": 1000,
            }
        },
        timeout=120
    )
    
    if response.status_code != 200:
        return f"Ollama fejl: {response.status_code}"
    
    return response.json().get("response", "Intet svar")


def main():
    print(f"TEO Kode-review — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Pi: {PI_HOST}:{TEO_PATH}")
    print("-" * 60)
    
    results = []
    results.append(f"TEO Kode-review — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    results.append(f"Model: {OLLAMA_MODEL}\n")
    
    for filename in FILES_TO_REVIEW:
        print(f"\nReviewer: {filename}...")
        
        code, error = fetch_file_from_pi(filename)
        if error:
            print(f"  SKIP: {error}")
            results.append(f"\n{'='*50}")
            results.append(f"FIL: {filename}")
            results.append(f"SKIP: {error}")
            continue
        
        review = review_file_with_ollama(filename, code)
        
        results.append(f"\n{'='*50}")
        results.append(f"FIL: {filename} ({len(code.splitlines())} linjer)")
        results.append(f"{review}")
        
        print(f"  Færdig.")
    
    # Gem rapport
    output_path = Path(OUTPUT_FILE)
    output_path.write_text("\n".join(results), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"Rapport gemt: {output_path.absolute()}")
    print("Send fejllisten til Claude Code for rettelse.")


if __name__ == "__main__":
    main()
