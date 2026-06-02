"""Public API for TEO Data Commons — spec DEL 6/7.4.

To endpoints, bag reverse proxy på api.tjelum.dk:

* ``POST /v1/telemetry``          — modtag et anonymt døgnresumé fra en installation.
* ``GET  /v1/model/latest``       — udlever den nyeste offentliggjorte model.
* ``GET  /v1/calibration-status`` — kalibreringsstatus per installation (til admin-log).

Bevidst minimal (Flask). Ingen autentificering her — installationer er
anonyme, og payloaden indeholder per design ingen personoplysninger. Sæt evt.
rate-limiting i reverse proxy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from db import connect, init_schema

app = Flask(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.post("/v1/telemetry")
def receive_telemetry():
    payload = request.get_json(silent=True)
    if not payload or "installation_id" not in payload or "date" not in payload:
        return jsonify({"error": "ugyldig payload"}), 400

    iid = payload["installation_id"]
    zone = payload.get("zone")
    with connect() as conn:
        conn.execute(
            """INSERT INTO installations (installation_id, zone, system_config,
                                          first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(installation_id) DO UPDATE SET
                   zone=excluded.zone,
                   system_config=excluded.system_config,
                   last_seen=excluded.last_seen""",
            (iid, zone, json.dumps(payload.get("system_config", {})),
             _now(), _now()),
        )
        conn.execute(
            """INSERT INTO telemetry (installation_id, date, zone, payload, received_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(installation_id, date) DO UPDATE SET
                   payload=excluded.payload, received_at=excluded.received_at""",
            (iid, payload["date"], zone, json.dumps(payload), _now()),
        )
    return jsonify({"status": "ok"}), 200


@app.get("/v1/model/latest")
def model_latest():
    with connect() as conn:
        row = conn.execute(
            "SELECT calibration FROM model_versions WHERE is_latest = 1 LIMIT 1"
        ).fetchone()
    if row is None:
        return jsonify({"error": "ingen model offentliggjort endnu"}), 404
    return app.response_class(row["calibration"], mimetype="application/json")


@app.get("/v1/calibration-status")
def calibration_status():
    """Kalibreringsstatus per installation — bruges af admin-dashboard og ekstern log.

    Returnerer for hver installation:
    - installation_id, zone, first_seen, last_seen
    - antal dage med telemetri (uploads)
    - seneste upload-dato
    - estimeret daglig besparelse (gns. fra payload)
    - algoritme-version fra seneste payload
    """
    with connect() as conn:
        rows = conn.execute(
            """SELECT
                i.installation_id,
                i.zone,
                i.first_seen,
                i.last_seen,
                COUNT(t.id)                                          AS upload_count,
                MAX(t.date)                                          AS latest_upload,
                AVG(json_extract(t.payload,
                    '$.model_performance.estimated_saving_dkk'))    AS avg_saving_dkk,
                MAX(json_extract(t.payload, '$.algorithm_version')) AS algorithm_version,
                MAX(json_extract(t.payload, '$.teo_version'))       AS teo_version
               FROM installations i
               LEFT JOIN telemetry t USING (installation_id)
               GROUP BY i.installation_id
               ORDER BY i.last_seen DESC"""
        ).fetchall()

    result = []
    for r in rows:
        result.append({
            "installation_id": r["installation_id"],
            "zone": r["zone"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "upload_count": r["upload_count"],
            "latest_upload": r["latest_upload"],
            "avg_saving_dkk": round(r["avg_saving_dkk"], 2) if r["avg_saving_dkk"] else None,
            "algorithm_version": r["algorithm_version"],
            "teo_version": r["teo_version"],
        })

    return jsonify({
        "generated": _now(),
        "installation_count": len(result),
        "installations": result,
    })


if __name__ == "__main__":
    import config
    init_schema()
    app.run(host=config.API_HOST, port=config.API_PORT)
