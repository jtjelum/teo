#!/bin/bash
/usr/bin/python3 << 'EOFPYTHON'
from pathlib import Path
try:
    files = sorted(Path("/config/teo_reports").glob("*.txt"))
    if files:
        content = files[-1].read_text(encoding="utf-8").strip()
        print(content.replace("\n", " | "))
    else:
        print("Ingen rapport")
except Exception as e:
    print(f"Fejl: {e}")
EOFPYTHON
