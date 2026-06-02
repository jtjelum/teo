#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

db_path = "/config/teo_data.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT 
            date(timestamp)||':'||ROUND(100.0*SUM(
                CASE 
                    WHEN (teo_action = 'BATTERY_IDLE' AND teo_actual_action = 'idle')
                      OR (teo_action = 'BATTERY_CHARGE_GRID' AND teo_actual_action = 'charging_grid')
                      OR (teo_action = 'BATTERY_DISCHARGE' AND teo_actual_action = 'discharging')
                      OR (teo_action = 'BATTERY_CHARGE_SOLAR' AND teo_actual_action = 'charging_solar')
                    THEN 1 
                    ELSE 0 
                END
            )/COUNT(*),1)
        FROM measurements 
        WHERE timestamp > datetime('now','-7 days') 
          AND teo_actual_action IS NOT NULL
        GROUP BY date(timestamp) 
        ORDER BY date(timestamp) DESC
    """)
    results = cursor.fetchall()
    conn.close()
    
    if results:
        for row in results:
            print(row[0])
    else:
        print("Ingen data")
except Exception as e:
    print(f"Fejl: {e}")
