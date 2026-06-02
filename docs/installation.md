# TEO — Installationsguide

**[Dansk](#dansk) | [English](#english)**

---

<a name="dansk"></a>
## Dansk

### Hvad du skal have i forvejen

**Hardware:**
- Raspberry Pi 4 (4 GB) — anbefalet
- USB SSD minimum 64 GB (fx Kingston XS1000) — brug ALDRIG SD-kort
- Officiel Pi strømforsyning (USB-C, 5V/3A)
- Netværkskabel (ethernet til Pi)

**Konti og adgange:**
- Solcast API-nøgle (gratis) — registrer på [solcast.com](https://solcast.com/free-rooftop-solar-forecasting)
- IP-adresser på dine energienheder (find dem i din routers admin-panel)
- Enphase-brugere: DIY-konto på [Enlighten Manager](https://enlighten.enphaseenergy.com)

---

### Inden du starter — find disse 4 ting frem

1. IP-adresser på alle energienheder (batteri, inverter, lader, måler)
2. Din elzone: DK1, DK2, SE3, NO1 osv.
3. Solcast API-nøgle (registrer først hvis du ikke har)
4. Adgang til router-admin (for at finde IP-adresser)

---

### Trin-for-trin installation

#### Trin 1 — Flash Home Assistant OS (~10 min)

1. Download [Raspberry Pi Imager](https://rpi.io/imager) på din computer
2. Klik **Choose OS** → **Other specific purpose OS** → **Home Assistant**
3. Vælg din USB SSD som destination
4. Klik **Write** og vent til det er færdigt

> **Vigtigt:** Brug ALDRIG SD-kort som systemdisk — kun USB SSD

#### Trin 2 — Start Pi og vent på Home Assistant (~5 min)

1. Sæt USB SSD i Pi'ens **blå** USB 3.0-port (ikke den grå)
2. Tilslut netværkskabel og strømforsyning
3. Åbn browser og gå til: `http://homeassistant.local:8123`
4. Vent 3-8 minutter på første opstart
5. Opret en Home Assistant-bruger (brugernavn + adgangskode til HA)

> Siden opdateres automatisk når HA er klar — vent blot

#### Trin 3 — Kør TEO installationsscript (~5 min)

```bash
curl -sSL https://install.teo.energy | bash
```

Eller med specifik IP-adresse hvis `homeassistant.local` ikke virker:

```bash
bash install.sh 192.168.1.xxx
```

Scriptet gør automatisk:
- Installerer TEO custom integration
- Installerer HACS
- Installerer Mosquitto MQTT broker
- Opretter standard konfigurationsfiler
- Genstarter Home Assistant

#### Trin 4 — Åbn TEO setup wizard (~3 min)

1. Gå til Home Assistant: `http://homeassistant.local:8123`
2. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration**
3. Søg efter **TEO** og klik på den
4. Følg opsætningsguiden

#### Trin 5 — Konfigurer i wizard (~5 min)

**Vælg elzone:**
- DK2 — Danmark Øst (Sjælland, Bornholm)
- DK1 — Danmark Vest (Jylland, Fyn)
- SE1–SE4, NO1–NO5, FI

**Scan netværk:**
TEO finder automatisk dine energienheder. Enheder der ikke opdages kan tilføjes manuelt med IP-adresse.

**Systemparametre** (standardværdier virker fint for de fleste):

| Parameter | Standard | Beskrivelse |
|---|---|---|
| Minimum batteriniveau | 20% | TEO aflader aldrig batteriet under dette |
| Stop EV-ladning under | 30% | EV-laderen pauses hvis batteriet falder under dette |
| Lad fra net hvis pris under | 60 øre/kWh | TEO lader batteriet når strøm er billig |
| Brug batteri hvis pris over | 100 øre/kWh | TEO bruger batteriet ved dyre timer |
| Batterislid | 0,04 DKK/kWh | Inkluderes i optimeringen |

**Solcast API-nøgle** (valgfri men anbefalet):
Giv TEO din Solcast nøgle for bedre solcelleprognose. Gratis på [solcast.com](https://solcast.com).

#### Trin 6 — Verificer at alt virker

Når TEO er installeret, åbnes dashboardet automatisk. Tjek at dine enheder vises:
- **Grønt** = forbundet og kører
- **Rødt** = tjek IP-adresse og netværksforbindelse

---

### Hvad sker der automatisk?

| Tidspunkt | Handling |
|---|---|
| Kl. 13:00 dagligt | Nord Pool henter næste dags priser og TEO genberegner 24-timers energiplan |
| Kl. 23:00 dagligt | TEO opdaterer natplanen med de nyeste priser og solprognose |
| Hvert 5. minut | TEO tjekker batteri-SOC og justerer EV-ladning hvis nødvendigt |
| Hvert 6. time | Solcast opdaterer solprognosen for de næste 48 timer |
| Kl. 04:30 dagligt | Anonym datadeling (kun ved opt-in) |
| Kl. 06:00 dagligt | Daglig afvigelses-analyse og rapport |

---

### Manuel installation (avanceret)

Hvis du foretrækker at installere manuelt uden scriptet:

```bash
# SSH til Pi
ssh root@homeassistant.local -p 22222

# Opret integration-mappe
mkdir -p /config/custom_components/teo

# Kopiér filer (fra dit lokale system)
# scp virker ikke med HAOS — brug cat/pipe metoden:
cat local_file.py | ssh root@homeassistant.local -p 22222 \
  "cat > /config/custom_components/teo/local_file.py"

# Genstart HA
ha core restart
```

---

### Fejlfinding

**`homeassistant.local` virker ikke**
Find Pi'ens IP i din routers admin-panel og brug den i stedet.

**TEO-integration vises ikke i HA**
Genstart Home Assistant og vent 2-3 minutter.

**Enhed ikke fundet ved netværksscan**
Indtast IP-adressen manuelt. Find IP i din routers enhedsliste.

**Enphase: kun aflæsning, ingen kontrol**
Du mangler en DIY-konto på Enlighten Manager. Se [teo-guide til Enphase](enphase.md).

---

<a name="english"></a>
## English

### Prerequisites

**Hardware:**
- Raspberry Pi 4 (4 GB) — recommended
- USB SSD minimum 64 GB (e.g. Kingston XS1000) — NEVER use SD card
- Official Pi power supply (USB-C, 5V/3A)
- Ethernet cable

**Accounts and access:**
- Solcast API key (free) — register at [solcast.com](https://solcast.com/free-rooftop-solar-forecasting)
- IP addresses of your energy devices (find them in your router's admin panel)
- Enphase users: DIY account on [Enlighten Manager](https://enlighten.enphaseenergy.com)

### Installation

```bash
curl -sSL https://install.teo.energy | bash
```

Or with a specific IP address:

```bash
bash install.sh 192.168.1.xxx
```

After installation, open the TEO setup wizard at `http://homeassistant.local:8123` → Settings → Devices & services → Add integration → TEO.

See the Danish section above for the full step-by-step guide and troubleshooting — the process is identical in both languages.
