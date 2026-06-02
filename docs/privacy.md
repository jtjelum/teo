# TEO — Datasikkerhed og privacy

**[Dansk](#dansk) | [English](#english)**

---

<a name="dansk"></a>
## Dansk

### Dine data tilhører dig

TEO er bygget med **privacy by design** som et grundlæggende princip. Al energidata behandles lokalt på din Raspberry Pi. Ingen personoplysninger forlader din Pi uden din eksplicitte godkendelse.

---

### Hvad gemmes lokalt

Følgende data gemmes i `/config/teo_data.db` på din Pi:

| Data | Formål | Opbevaring |
|---|---|---|
| Batteriniveau (SOC %) | Optimering og log | 3 år |
| Solproduktion (kW) | Optimering og prognosevalidering | 3 år |
| Husets forbrug (kW) | Lastprognose | 3 år |
| Nord Pool spotpris | Optimering | 3 år |
| TEO's beslutninger | Transparens og analyse | 3 år |
| EV-ladeeffekt | Optimering | 3 år |

Disse data forlader aldrig din Pi med mindre du aktiverer anonym datadeling.

---

### Anonym datadeling (opt-in)

TEO kan sende et **stærkt aggregeret, anonymiseret døgnresumé** til TEO's server én gang dagligt (kl. 04:30). Dette er **frivilligt** og slået **fra som standard**.

**Formål:** At forbedre TEO's algoritmer for alle brugere ved at lære af mønstre på tværs af installationer.

#### Hvad sendes (ved opt-in)

| Felt | Eksempel | Bemærkning |
|---|---|---|
| Installations-ID | `d80e4214-...` | Anonymt UUID — ingen personoplysninger |
| Elzone | `DK2` | Kun zone, ikke adresse |
| Systemkonfiguration | `battery_kwh: 10.5` | Kun hardware-specs |
| Energiresumé | `solar_kwh: 14.2` | Aggregeret over hele dagen |
| Vejrtype | `sunny` | Vejrkategori, ikke præcis placering |
| Modelperformance | `saving_dkk: 12.4` | Estimeret besparelse |
| Normaliserede lastprofiler | `[0.3, 0.4, ...]` | 0-1 normaliseret, ikke absolutte tal |
| Algoritmeversion | `0.0.14` | Hvilken version der kører |

#### Hvad sendes ALDRIG

- Din adresse eller præcise placering
- IP-adresse
- Serienumre på enheder
- Adgangskoder eller tokens
- Rå 5-minutters data
- Absolutte kWh per rum eller apparat
- Navn eller email

#### Aktivér/deaktiver datadeling

I `teo_config.yaml`:
```yaml
data_sharing:
  opt_in: true   # Skift til false for at deaktivere
```

Eller via TEO-dashboardet under **Indstillinger → Datadeling**.

---

### Tredjepartstjenester

TEO kommunikerer med følgende eksterne tjenester:

| Tjeneste | Formål | Data der sendes | Kan deaktiveres |
|---|---|---|---|
| Nord Pool | Spotpriser | Kun elzone (DK2 osv.) | Nej — kræves til optimering |
| Solcast | Solprognose | Panelkoordinater, azimut, tilt | Ja — TEO kører uden |
| Easee API | EV-laderstyring | Lader-ID, kommandoer | Nej — kræves til Easee-styring |
| Zaptec API | EV-laderstyring | Lader-ID, kommandoer | Nej — kræves til Zaptec-styring |
| TEO API | Anonym datadeling | Se tabel ovenfor | Ja — opt-in |

Alle andre enheder (Enphase, Victron, BYD, Shelly, HomeWizard, AMS) kommunikerer **100% lokalt** uden internetforbindelse.

---

### Enphase og cloud-konflikter

Enphase Enlighten cloud kan periodisk overskrive TEO's batteristyring. TEO modvirker dette ved at gen-håndhæve sine indstillinger hvert 30. sekund.

Hvis du oplever at Enphase-cloud overtager kontrollen:
1. Log ind på [enlighten.enphaseenergy.com](https://enlighten.enphaseenergy.com)
2. Gå til dit system → **Settings → Grid Services**
3. Deaktiver **Auto Charge** og **Grid Profile**

---

### Open source

TEO er fuldstændig open source under MIT-licensen. Du kan selv inspicere al kode på [GitHub](https://github.com/jtjelum/teo). Der er ingen skjulte dataoverførsler eller bagdøre.

---

<a name="english"></a>
## English

### Your data belongs to you

TEO is built with **privacy by design** as a core principle. All energy data is processed locally on your Raspberry Pi. No personal information leaves your Pi without your explicit consent.

### What is stored locally

All measurements are stored in `/config/teo_data.db` on your Pi: battery SOC, solar production, house consumption, Nord Pool prices, TEO decisions and EV charge power. This data never leaves your Pi unless you enable anonymous data sharing.

### Anonymous data sharing (opt-in)

TEO can send a **heavily aggregated, anonymised daily summary** to TEO's server once per day. This is **voluntary** and **disabled by default**.

**Purpose:** To improve TEO's algorithms for all users by learning patterns across installations.

**What is NEVER sent:** address, IP address, device serial numbers, passwords, raw 5-minute data, absolute kWh per room or appliance, name or email.

**Enable/disable in `teo_config.yaml`:**
```yaml
data_sharing:
  opt_in: true   # Change to false to disable
```

### Third-party services

TEO communicates with Nord Pool (spot prices — grid area only), Solcast (solar forecast — panel coordinates), and optionally Easee/Zaptec APIs for EV charger control. All other devices communicate 100% locally with no internet connection required.

### Open source

TEO is fully open source under the MIT license. You can inspect all code at [GitHub](https://github.com/jtjelum/teo). There are no hidden data transfers or backdoors.
