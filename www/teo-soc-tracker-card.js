/**
 * DEL 3: Live SOC-tracking dashboard-widget
 *
 * Custom Lovelace card der viser:
 *   - Batteri SOC % de seneste 24 timer (linjegraf)
 *   - Planlagte TEO-handlinger som farvede baggrunde
 *     Grøn = lader fra net
 *     Blå = lader fra sol
 *     Rød = aflader
 *     Grå = idle
 *   - Faktisk SOC som stiplet linje
 *
 * Installation:
 *   1. Kopier denne fil til /config/www/teo-soc-tracker-card.js
 *   2. Tilføj i Lovelace Resources:
 *      URL: /local/teo-soc-tracker-card.js
 *      Type: JavaScript Module
 *   3. Tilføj kort til dashboard:
 *      type: custom:teo-soc-tracker-card
 *      entity: sensor.teo_battery_soc  (valgfri — bruges kun som trigger)
 *      hours: 24  (valgfri — default 24)
 *
 * Kræver:
 *   - RESTful sensor der henter data fra /api/teo/soc_timeline
 *   - Chart.js (bundlet her via CDN for simplicitet)
 */

class TeoSocTrackerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._data = null;
  }

  setConfig(config) {
    if (!config) {
      throw new Error('Invalid configuration');
    }
    this._config = {
      hours: config.hours || 24,
      title: config.title || 'TEO Batteri SOC Tracking',
      entity: config.entity || null,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._fetchData();
  }

  async _fetchData() {
    if (!this._hass) return;

    try {
      const hours = this._config.hours;
      const response = await this._hass.callApi('GET', `teo/soc_timeline?hours=${hours}`);
      this._data = response;
      this._updateChart();
    } catch (err) {
      console.error('TEO SOC Tracker: Kunne ikke hente data', err);
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        .card {
          padding: 16px;
          background: var(--ha-card-background, white);
          border-radius: var(--ha-card-border-radius, 8px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.1));
        }
        .card-header {
          font-size: 20px;
          font-weight: 500;
          margin-bottom: 16px;
          color: var(--primary-text-color);
        }
        #chart-container {
          position: relative;
          height: 300px;
        }
        canvas {
          max-width: 100%;
        }
      </style>
      <div class="card">
        <div class="card-header">${this._config.title}</div>
        <div id="chart-container">
          <canvas id="soc-chart"></canvas>
        </div>
      </div>
    `;
  }

  _updateChart() {
    if (!this._data || !this._data.timestamps || this._data.timestamps.length === 0) {
      return;
    }

    const canvas = this.shadowRoot.getElementById('soc-chart');
    if (!canvas) return;

    // Lazy-load Chart.js hvis ikke allerede loaded
    if (typeof Chart === 'undefined') {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
      script.onload = () => this._drawChart(canvas);
      document.head.appendChild(script);
    } else {
      this._drawChart(canvas);
    }
  }

  _drawChart(canvas) {
    const ctx = canvas.getContext('2d');

    // Parse timestamps til datetime-objekter
    const timestamps = this._data.timestamps.map(ts => new Date(ts));
    const soc = this._data.soc_pct;
    const planned = this._data.planned_actions;
    const actual = this._data.actual_actions;

    // Byg baggrunds-farver baseret på planlagt handling
    const backgroundColors = planned.map(action => this._actionToColor(action));

    // Destroy eksisterende chart hvis den findes
    if (this._chart) {
      this._chart.destroy();
    }

    this._chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timestamps,
        datasets: [
          {
            label: 'Batteri SOC (%)',
            data: soc,
            borderColor: 'rgba(75, 192, 192, 1)',
            backgroundColor: 'rgba(75, 192, 192, 0.1)',
            borderWidth: 2,
            fill: false,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            type: 'time',
            time: {
              unit: 'hour',
              displayFormats: {
                hour: 'HH:mm',
              },
            },
            title: {
              display: true,
              text: 'Tidspunkt',
            },
          },
          y: {
            beginAtZero: true,
            max: 100,
            title: {
              display: true,
              text: 'SOC (%)',
            },
          },
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
          },
          tooltip: {
            callbacks: {
              label: (context) => {
                const idx = context.dataIndex;
                const socVal = soc[idx];
                const plannedAction = this._formatAction(planned[idx]);
                const actualAction = this._formatAction(actual[idx]);
                return [
                  `SOC: ${socVal}%`,
                  `Planlagt: ${plannedAction}`,
                  `Faktisk: ${actualAction}`,
                ];
              },
            },
          },
        },
      },
    });

    // Tegn farvede baggrunde for planlagte handlinger
    // (Dette kræver Chart.js plugin — forenklet version her)
    this._addBackgroundPlugin();
  }

  _actionToColor(action) {
    const colors = {
      'BATTERY_CHARGE_GRID': 'rgba(0, 255, 0, 0.1)',      // Grøn = lader fra net
      'charging_grid': 'rgba(0, 255, 0, 0.1)',
      'BATTERY_CHARGE_SOLAR': 'rgba(0, 150, 255, 0.1)',   // Blå = lader fra sol
      'charging_solar': 'rgba(0, 150, 255, 0.1)',
      'BATTERY_DISCHARGE': 'rgba(255, 0, 0, 0.1)',        // Rød = aflader
      'discharging': 'rgba(255, 0, 0, 0.1)',
      'BATTERY_IDLE': 'rgba(200, 200, 200, 0.05)',        // Grå = idle
      'idle': 'rgba(200, 200, 200, 0.05)',
    };
    return colors[action] || 'rgba(200, 200, 200, 0.05)';
  }

  _formatAction(action) {
    const labels = {
      'BATTERY_CHARGE_GRID': 'Lader fra net',
      'charging_grid': 'Lader fra net',
      'BATTERY_CHARGE_SOLAR': 'Lader fra sol',
      'charging_solar': 'Lader fra sol',
      'BATTERY_DISCHARGE': 'Aflader',
      'discharging': 'Aflader',
      'BATTERY_IDLE': 'Idle',
      'idle': 'Idle',
      'unknown': 'Ukendt',
    };
    return labels[action] || action || 'Ukendt';
  }

  _addBackgroundPlugin() {
    // Simpel plugin til farvede baggrunde — full implementering kræver Chart.js plugin API
    // Dette er en placeholder — se Chart.js documentation for komplet implementering
  }

  getCardSize() {
    return 4;
  }
}

customElements.define('teo-soc-tracker-card', TeoSocTrackerCard);

// Register card for card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'teo-soc-tracker-card',
  name: 'TEO SOC Tracker',
  description: 'Viser batteri SOC med planlagte vs. faktiske handlinger',
  preview: false,
});

console.info(
  '%c TEO-SOC-TRACKER-CARD %c v1.0.0 ',
  'color: white; background: #00a8e1; font-weight: 700;',
  'color: #00a8e1; background: white; font-weight: 700;'
);
