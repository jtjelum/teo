#!/usr/bin/env python3
"""Helper script til at læse seneste TEO rapport for command_line sensor."""
from pathlib import Path

try:
    reports_dir = Path("/config/teo_reports")
    files = sorted(reports_dir.glob("*.txt"))
    
    if not files:
        print("Ingen rapport tilgængelig")
    else:
        content = files[-1].read_text(encoding="utf-8").strip()
        # Erstat alle newlines med | for single-line output
        single_line = content.replace("\n", "|")
        print(single_line)
except Exception as e:
    print(f"Fejl: {e}")
