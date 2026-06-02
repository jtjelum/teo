"""Upload teo_dashboard.yaml til Pi med korrekt UTF-8 encoding."""
import subprocess

content = """# TEO Dashboard
views:
  - title: Live
    path: live
    icon: mdi:chart-line
    cards:
      - type: vertical-stack
        cards:
          - type: gauge
            entity: sensor.teo_batteriniveau
            name: Batteri
            min: 0
            max: 100
            severity:
              green: 50
              yellow: 30
              red: 20
          - type: horizontal-stack
            cards:
              - type: statistic
                entity: sensor.teo_aktuel_spotpris
                name: Spotpris
                icon: mdi:cash
                stat_type: mean
                period:
                  calendar:
                    period: hour
              - type: statistic
                entity: sensor.teo_solproduktion
                name: Sol
                icon: mdi:solar-power
                stat_type: mean
                period:
                  calendar:
                    period: hour
              - type: statistic
                entity: sensor.teo_neteffekt
                name: Net
                icon: mdi:transmission-tower
                stat_type: mean
                period:
                  calendar:
                    period: hour
      - type: entities
        title: Aktuel TEO beslutning
        show_header_toggle: false
        entities:
          - entity: sensor.teo_beslutning
            name: Beslutning
          - entity: sensor.teo_planlagt_batterihandling
            name: Planlagt handling
          - entity: sensor.teo_optimerings_status
            name: Status

  - title: Beslutninger
    path: decisions
    icon: mdi:robot
    cards:
      - type: entities
        title: Seneste beslutninger
        entities:
          - entity: sensor.teo_beslutning

  - title: Styring
    path: control
    icon: mdi:cog
    cards:
      - type: entities
        title: Batteristyring og energistrategi
        show_header_toggle: false
        entities:
          - entity: switch.teo_automatik_aktiv
            name: TEO Automatik aktiv
          - type: divider
          - entity: number.teo_batteri_minimum_soc
            name: Minimum-SOC (gulv for optimering)
          - entity: number.teo_enphase_reserve_soc
            name: Reserve-SOC (Envoy)
          - entity: switch.teo_enphase_charge_from_grid
            name: Netladning af batteri (Envoy)
          - entity: switch.teo_sell_at_negative_price
            name: "S\u00e6lg ved negativ pris"
          - entity: switch.teo_charge_from_grid_allowed
            name: Netladning tilladt i optimering
          - entity: switch.teo_ev_kun_sol_og_net
            name: EV lader kun fra sol og net

      - type: markdown
        content: >
          **TEO Automatik aktiv TIL** \u2014 TEO styrer alt automatisk baseret p\u00e5
          priser og sol. Dine indstillinger nedenfor bruges som gr\u00e6nser.

          **TEO Automatik aktiv FRA** \u2014 Du styrer alt manuelt.
          Alle knapper nedenfor respekteres permanent uden at TEO overskrider dem.

          ---

          **Minimum-SOC:** Den laveste batteriprocent LP-optimizeren m\u00e5 aflade
          til. S\u00e6t til 5% for maksimal udnyttelse \u2014 du har ingen backup-funktion.

          **Reserve-SOC (Envoy):** Mindste batteriniveau Envoy holder. Skrives
          direkte til Envoy og omg\u00e5r Enphase cloud-overstyring.
          S\u00e6t til 5% da du ikke har backup-funktion.

          **Netladning af batteri (Envoy):** Manuel kommando \u2014 lad batteriet op
          fra nettet lige nu. Skriver direkte til Envoy.
          Bruges n\u00e5r du manuelt vil fylde batteriet op uden for TEOs plan.

          **S\u00e6lg ved negativ pris:** N\u00e5r sl\u00e5et FRA stopper TEO salg til nettet
          i timer hvor spotprisen er negativ. Undg\u00e5r at du betaler for at
          levere str\u00f8m til nettet.

          **Netladning tilladt i optimering:** H\u00e5rd gr\u00e6nse til LP-optimizeren.
          N\u00e5r FRA m\u00e5 TEO aldrig planl\u00e6gge at k\u00f8be str\u00f8m til batteriet \u2014
          batteriet lades kun via sol. Forskellig fra knappen ovenfor:
          denne styrer TEOs fremtidige plan, ikke hvad der sker lige nu.

          **EV lader kun fra sol og net:** N\u00e5r TIL s\u00e6tter TEO Envoy reserve
          til 100% s\u00e5 batteriet ikke aflades til EV-laderen.
          EV forts\u00e6tter med at lade men kun fra sol og net.
          N\u00e5r FRA kan EV igen tr\u00e6kke fra batteriet.

  - title: "\u00d8konomi"
    path: economy
    icon: mdi:cash-multiple
    cards:
      - type: markdown
        title: Din besparelse
        content: >
          ## {{ states('sensor.teo_saving_today_dkk') }} DKK sparet i dag

          Denne dag betalte du i gennemsnit
          **{{ states('sensor.teo_avg_price_paid_ore') }} \u00f8re/kWh.**

          Uden TEO havde du betalt
          **{{ states('sensor.teo_avg_price_baseline_ore') }} \u00f8re/kWh.**

          **Besparelse denne m\u00e5ned:**
          {{ states('sensor.teo_saving_month_dkk') }} DKK.

      - type: entities
        title: Omkostninger
        entities:
          - entity: sensor.teo_cost_actual_today_dkk
            name: Faktisk omkostning i dag
          - entity: sensor.teo_cost_baseline_today_dkk
            name: Baseline omkostning
          - entity: sensor.teo_grid_cost_month_dkk
            name: "Net-omkostning denne m\u00e5ned"

  - title: Indstillinger
    path: settings
    icon: mdi:cog-outline
    cards:
      - type: entities
        title: TEO System
        entities:
          - entity: sensor.teo_installations_id
            name: Installations-ID
          - entity: sensor.teo_algoritme_version
            name: Algoritme-version

      - type: markdown
        content: >
          **Om TEO-systemet**

          TEO (Tjelums Energy Optimisation) optimerer batteriforbrug baseret
          p\u00e5 Nord Pool spotpriser og solprognoser.
          Optimering k\u00f8rer automatisk kl. 13:00 og 23:00.

          Styr TEO manuelt under Styring-fanen ved at sl\u00e5
          TEO Automatik aktiv FRA.

  - title: Status
    path: status
    icon: mdi:information
    cards:
      - type: entities
        title: Status-oversigt
        entities:
          - entity: sensor.teo_batteriniveau
          - entity: sensor.teo_solproduktion
          - entity: sensor.teo_neteffekt
          - entity: sensor.teo_ev_ladeeffekt
"""

proc = subprocess.run(
    ["ssh", "teo-pi", "sudo tee /config/teo_dashboard.yaml > /dev/null"],
    input=content, text=True, encoding="utf-8"
)

if proc.returncode == 0:
    print("Dashboard uploadet med korrekt UTF-8 encoding.")
else:
    print("FEJL")
