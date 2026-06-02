# TEO — Tjelums Energy Optimisation

> Gratis, lokalt og transparent energistyring — du ejer dit system og dine data.

**[Dansk](#dansk) | [English](#english)**

---

<a name="dansk"></a>
## Dansk

TEO er et modulært energistyringssystem der kører lokalt på en Raspberry Pi. Det er bygget som et gratis, transparent alternativ til cloud-baserede abonnementstjenester.

TEO kombinerer **matematisk optimering** (Lineær Programmering) der planlægger energibrug 24–48 timer frem, **solcelleprognose** via Solcast, **Nord Pool spotprisbevidsthed** og **fuld transparens** — hver beslutning logges og forklares på klart sprog.

---

## Hvorfor TEO?

| Funktion | Typisk abonnementstjeneste | TEO |
|---|---|---|
| Månedligt abonnement | 100–200 DKK/md | **Gratis** |
| Cloud-afhængig | Ja — offline = ingen kontrol | **Nej — 100% lokal** |
| Forklarer sine beslutninger | Nej — sort boks | **Ja — fuld beslutningslog** |
| Virker med alle mærker | Begrænset liste | **Åbent integrationssystem** |
| Kildekode | Lukket | **Open source (MIT)** |

---

## Gratis — én model

### TEO — 0 kr for altid
- Kører lokalt på din Raspberry Pi
- Nord Pool DK/SE/NO/FI spotpriser
- Solcast solcelleprognose 48 timer frem
- LP-optimering med EMHASS
- Batteribeskyttelse mod EV-afladning
- Alle enhedsintegrationer inkluderet
- Fuld manuel styring og override
- Beslutningslog på dansk/engelsk
- Opt-in anonym datadeling — hjælper med at forbedre algoritmen for alle brugere

---

## Understøttede enheder

### Batterier
- Enphase IQ Battery 3T / 5P *(fuld kontrol)*
- Victron Energy — alle modeller med Venus OS *(fuld kontrol)*
- BYD Battery-Box HVS/HVM/HVL/LVS *(aflæsning)*
- SMA Sunny Boy Storage
- Huawei LUNA 2000
- Sonnen eco / ecoLinx
- Tesla Powerwall 2 / 3

### Invertere
- Enphase Envoy-S Metered
- SolarEdge HD-Wave
- Fronius Symo / Gen24
- Huawei SUN2000
- Goodwe
- Kostal Plenticore

### EV-ladere
- Easee Home / Charge / Base
- Zaptec Go / Pro
- go-e Charger Gemini *(100% lokal)*
- Wallbox Pulsar Plus
- KEBA P30

### Elmålere
- AMS/HAN-reader *(alle nordiske)*
- Shelly EM / 3EM / Pro 3EM *(100% lokal)*
- HomeWizard P1 Meter *(100% lokal)*
- Tibber Pulse
- Kamstrup / Iskra HAN P1

---

## Hardwarekrav

| Model | RAM | Understøtter |
|---|---|---|
| Raspberry Pi 3B/3B+ | 1 GB | TEO Local (minimum) |
| Raspberry Pi 4 (2 GB) | 2 GB | Local + Self-Hosted |
| **Raspberry Pi 4 (4 GB)** | **4 GB** | **Begge — anbefalet** |
| Raspberry Pi 5 | 4-8 GB | Begge — bedst |
| Intel NUC / x86 Linux | 4+ GB | Begge |
| Synology NAS (Docker) | 2+ GB | Begge |

---

## Installation

```bash
curl -sSL https://install.teo.energy | bash
```

Eller med specifik IP-adresse:

```bash
bash install.sh 192.168.1.xxx
```

Scriptet installerer Home Assistant OS, TEO-integrationen og alle afhængigheder automatisk. Åbn derefter TEO-wizard på `http://homeassistant.local:8123`.

### Manuel installation (avanceret)

1. Installer [Home Assistant OS](https://www.home-assistant.io/installation/) på Raspberry Pi
2. Kopier `custom_components/teo/` til `/config/custom_components/teo/`
3. Kopier `integrations/` til `/config/integrations/`
4. Genstart Home Assistant
5. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration → TEO**

---

## Beslutningsgennemsigtighed

Hver handling TEO foretager logges på klart dansk:

```
[16:00] BATTERI OPLADES FRA NET
  Pris 107 øre/kWh. Prognose viser 175 øre/kWh i aften (17-03).
  Forventet besparelse: 68 øre/kWh × 8,4 kWh = 5,71 kr.
  Batteriomkostning: 0,04 × 8,4 = 0,34 kr. Nettogevinst: 5,37 kr.

[23:00] INGEN NETLADNING I NAT
  Solcast forudsiger 14,2 kWh sol i morgen. Batteri er 45%.
  Solen vil fylde batteriet inden kl. 11. Netladning unødvendig.
```

---

## Datasikkerhed

TEO er bygget med privacy by design:

- Al energidata behandles lokalt på din Raspberry Pi
- Ingen personoplysninger forlader din Pi
- Anonym datadeling er opt-in og indeholder aldrig adresse, IP eller serienumre
- Installations-ID er anonymt og genereres lokalt
- Open source — du kan selv inspicere al kode

---

## Tilføj din egen enhedsintegration

TEO er bygget til at andre nemt kan tilføje nye enheder. Se [CONTRIBUTING.md](CONTRIBUTING.md) for en komplet guide med kodeeksempler.

Kort oversigt:
1. Opret mappe: `integrations/<kategori>/<mærke>/`
2. Implementér base-klassen (`BatteryBase`, `EVChargerBase` osv.)
3. Skriv `manifest.json` med enhedsmetadata
4. Tilføj tests
5. Send pull request

---

## Roadmap

- **v1.0** — Enphase + Easee + AMS + Nordpool + Solcast + EMHASS ✅
- **v1.1** — Victron, BYD, Zaptec, go-e, Shelly, HomeWizard ✅
- **v1.2** — Avanceret optimering, EV-afgangstidspunkt, ugentlige rapporter
- **v1.3** — Push-notifikationer og forbedret fjernadgang
- **v2.0** — Varmepumpeintegration (Nibe, Daikin, Mitsubishi)

---

## Licens

MIT License — se [LICENSE](LICENSE).

TEO er gratis at bruge, modificere og distribuere.

---

## Community

- [GitHub Discussions](https://github.com/jtjelum/teo/discussions) — spørgsmål og idéer
- [GitHub Issues](https://github.com/jtjelum/teo/issues) — fejlrapporter

---

<a name="english"></a>
## English

TEO is a modular home energy management system that runs locally on a Raspberry Pi. It is designed as a free, transparent alternative to cloud-dependent subscription services.

TEO combines **mathematical optimisation** (Linear Programming) to plan energy use 24–48 hours ahead, **solar forecasting** via Solcast, **Nord Pool spot price awareness** and **full transparency** — every decision is logged and explained in plain language.

### Why TEO?

| Feature | Typical subscription service | TEO |
|---|---|---|
| Monthly subscription | 100–200 DKK/month | **Free** |
| Cloud dependent | Yes — offline = no control | **No — 100% local** |
| Explains its decisions | No — black box | **Yes — full decision log** |
| Works with all brands | Limited list | **Open integration system** |
| Source code | Closed | **Open source (MIT)** |

### Installation

```bash
curl -sSL https://install.teo.energy | bash
```

See the Danish section above for full device support lists, hardware requirements and roadmap — they apply to both languages.

### License

MIT License — free to use, modify and distribute.

### Community

- [GitHub Discussions](https://github.com/jtjelum/teo/discussions) — questions and ideas
- [GitHub Issues](https://github.com/jtjelum/teo/issues) — bug reports

---

*Built by Jakob Tjelum, Denmark · Open source · MIT License*
