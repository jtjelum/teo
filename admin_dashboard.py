"""Admin-dashboard — spec DEL 7.3 (kun localhost, tilgås via SSH-tunnel).

Flask-app på 127.0.0.1:8050 med fem sektioner:

1. Overblik — aktive installationer pr. zone, gns. besparelse, seneste model.
2. Zone-kalibrering — solfaktorer og prisbuffer pr. zone.
3. Mønstre til review — afventende fund med [Godkend] / [Afvis]. Godkendelse
   sætter status='approved' og offentliggør straks en ny modelversion.
4. Feedback — aggregerede brugerrapporter; typer med >20 rapporter fremhæves.
5. Kalibreringsstatus per installation — antal uploads, seneste dato, algo-version.

Tunnel fra din maskine:  ``ssh -L 8050:127.0.0.1:8050 teo-hetzner``  →  http://localhost:8050
Kør på serveren:        ``python3 /opt/teo/data_commons/admin_dashboard.py``
"""

from __future__ import annotations

import json

from flask import Flask, redirect, render_template_string, request, url_for

import model_publisher
from config import (
    ADMIN_HOST,
    ADMIN_PORT,
    PATTERN_STATUS_APPROVED,
    PATTERN_STATUS_PENDING,
    PATTERN_STATUS_REJECTED,
)
from db import connect, init_schema

app = Flask(__name__)

_FEEDBACK_HIGHLIGHT_THRESHOLD = 20

_PAGE = """
<!doctype html><html lang="da"><head><meta charset="utf-8">
<title>TEO Data Commons — Admin</title>
<style>
 body{font-family:system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e6e6}
 h1{color:#7ad}h2{border-bottom:1px solid #333;padding-bottom:.3rem;margin-top:2rem}
 table{border-collapse:collapse;width:100%;margin:.5rem 0}
 th,td{border:1px solid #333;padding:.4rem .6rem;text-align:left}
 th{background:#1b1f27}.card{display:inline-block;background:#1b1f27;border-radius:8px;
 padding:1rem 1.5rem;margin:.4rem;min-width:9rem}.big{font-size:1.6rem;color:#7d7}
 .hl{background:#3a2a00}button{padding:.3rem .8rem;border:0;border-radius:5px;cursor:pointer}
 .ok{background:#2e7d32;color:#fff}.no{background:#a33;color:#fff}
 .fresh{color:#7d7}.stale{color:#fa6}.dead{color:#a33}
 .mono{font-family:monospace;font-size:.85rem}
</style></head><body>
<h1>TEO Data Commons — Admin</h1>

<h2>1 · Overblik</h2>
{% for z,n in installs %}<div class="card">{{z}}<br><span class="big">{{n}}</span><br>installationer</div>{% endfor %}
<div class="card">Gns. besparelse<br><span class="big">{{avg_saving}}</span><br>DKK/dag</div>
<div class="card">Seneste model<br><span class="big">{{model_version}}</span></div>

<h2>2 · Zone-kalibrering</h2>
<table><tr><th>Zone</th><th>Vejrtype</th><th>Solfaktor</th><th>Installationer</th><th>Opdateret</th></tr>
{% for r in calibration %}<tr><td>{{r.zone}}</td><td>{{r.weather_category}}</td>
<td>{{r.solar_factor}}</td><td>{{r.installation_count}}</td><td>{{r.updated}}</td></tr>{% endfor %}
{% if not calibration %}<tr><td colspan="5">Ingen kalibrering endnu (afventer ≥ tærskel-installationer).</td></tr>{% endif %}
</table>

<h2>3 · Mønstre til review</h2>
<table><tr><th>ID</th><th>Beskrivelse</th><th>Parameter</th><th>Forslag</th>
<th>Konfidens</th><th>Berørt %</th><th>Handling</th></tr>
{% for p in patterns %}<tr>
 <td>{{p.pattern_id}}</td><td>{{p.description_da}}</td><td>{{p.parameter}}</td>
 <td>{{p.recommended_value}}</td><td>{{p.confidence}}</td><td>{{p.affected_pct}}%</td>
 <td><form method="post" action="{{url_for('approve',pid=p.id)}}" style="display:inline">
   <button class="ok">Godkend</button></form>
 <form method="post" action="{{url_for('reject',pid=p.id)}}" style="display:inline">
   <button class="no">Afvis</button></form></td></tr>{% endfor %}
{% if not patterns %}<tr><td colspan="7">Ingen mønstre afventer review.</td></tr>{% endif %}
</table>

<h2>4 · Feedback-rapporter</h2>
<table><tr><th>Type</th><th>Antal</th></tr>
{% for t,c in feedback %}<tr class="{{'hl' if c>threshold else ''}}"><td>{{t}}</td><td>{{c}}</td></tr>{% endfor %}
{% if not feedback %}<tr><td colspan="2">Ingen feedback endnu.</td></tr>{% endif %}
</table>

<h2>5 · Kalibreringsstatus per installation</h2>
<p style="color:#888;font-size:.9rem">
  Farver: <span class="fresh">■</span> Aktiv (upload seneste 7 dage)
  &nbsp;<span class="stale">■</span> Inaktiv (8–30 dage)
  &nbsp;<span class="dead">■</span> Tabt (>30 dage / aldrig uploadet)
</p>
<table>
  <tr>
    <th>Installation ID</th><th>Zone</th><th>Uploads</th>
    <th>Seneste upload</th><th>Algo-version</th><th>TEO-version</th>
    <th>Gns. besparelse</th><th>Første gang set</th>
  </tr>
  {% for inst in calibration_status %}
  <tr>
    <td class="mono">{{inst.short_id}}</td>
    <td>{{inst.zone or "–"}}</td>
    <td>{{inst.upload_count}}</td>
    <td class="{{inst.freshness_class}}">{{inst.latest_upload or "aldrig"}}</td>
    <td class="mono">{{inst.algorithm_version or "–"}}</td>
    <td class="mono">{{inst.teo_version or "–"}}</td>
    <td>{{inst.avg_saving_dkk}} DKK</td>
    <td>{{inst.first_seen[:10] if inst.first_seen else "–"}}</td>
  </tr>
  {% endfor %}
  {% if not calibration_status %}
  <tr><td colspan="8">Ingen installationer endnu — afventer første telemetri-upload.</td></tr>
  {% endif %}
</table>

</body></html>
"""


def _freshness_class(latest_upload: str | None) -> str:
    """Returnér CSS-klasse baseret på antal dage siden seneste upload."""
    if not latest_upload:
        return "dead"
    from datetime import date
    try:
        last = date.fromisoformat(latest_upload)
        days = (date.today() - last).days
        if days <= 7:
            return "fresh"
        if days <= 30:
            return "stale"
        return "dead"
    except ValueError:
        return "dead"


@app.get("/")
def index():
    with connect() as conn:
        installs = conn.execute(
            "SELECT zone, COUNT(*) n FROM installations GROUP BY zone").fetchall()
        sav = conn.execute(
            """SELECT AVG(json_extract(payload,'$.model_performance.estimated_saving_dkk'))
               FROM telemetry""").fetchone()
        avg_saving = round(sav[0], 2) if sav and sav[0] is not None else "–"
        mv = conn.execute(
            "SELECT version FROM model_versions WHERE is_latest=1").fetchone()
        model_version = mv["version"] if mv else "–"
        calibration = conn.execute(
            "SELECT * FROM zone_calibration ORDER BY zone, weather_category").fetchall()
        patterns = conn.execute(
            "SELECT * FROM discovered_patterns WHERE status=? ORDER BY id",
            (PATTERN_STATUS_PENDING,)).fetchall()
        feedback = conn.execute(
            """SELECT issue_type, COUNT(*) c FROM feedback
               GROUP BY issue_type ORDER BY c DESC""").fetchall()

        # Sektion 5: kalibreringsstatus per installation
        raw_status = conn.execute(
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

    calibration_status = []
    for r in raw_status:
        iid = r["installation_id"]
        calibration_status.append({
            "short_id": iid[:8] + "…" if len(iid) > 8 else iid,
            "zone": r["zone"],
            "first_seen": r["first_seen"],
            "upload_count": r["upload_count"],
            "latest_upload": r["latest_upload"],
            "freshness_class": _freshness_class(r["latest_upload"]),
            "algorithm_version": r["algorithm_version"],
            "teo_version": r["teo_version"],
            "avg_saving_dkk": round(r["avg_saving_dkk"], 2) if r["avg_saving_dkk"] else "–",
        })

    return render_template_string(
        _PAGE,
        installs=[(r["zone"], r["n"]) for r in installs],
        avg_saving=avg_saving, model_version=model_version,
        calibration=calibration, patterns=patterns,
        feedback=[(r["issue_type"], r["c"]) for r in feedback],
        threshold=_FEEDBACK_HIGHLIGHT_THRESHOLD,
        calibration_status=calibration_status)


@app.post("/approve/<int:pid>")
def approve(pid: int):
    with connect() as conn:
        conn.execute("UPDATE discovered_patterns SET status=? WHERE id=?",
                     (PATTERN_STATUS_APPROVED, pid))
    model_publisher.publish(changelog_da="Mønster godkendt af admin",
                            changelog_en="Pattern approved by admin")
    return redirect(url_for("index"))


@app.post("/reject/<int:pid>")
def reject(pid: int):
    with connect() as conn:
        conn.execute("UPDATE discovered_patterns SET status=? WHERE id=?",
                     (PATTERN_STATUS_REJECTED, pid))
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_schema()
    app.run(host=ADMIN_HOST, port=ADMIN_PORT)
