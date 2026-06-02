# TEO — Systemkrav og understøttede enheder

**[Dansk](#dansk) | [English](#english)**

---

<a name="dansk"></a>
## Dansk

### Hardwarekrav

| Model | RAM | Understøtter | Bemærkning |
|---|---|---|---|
| Raspberry Pi 3B/3B+ | 1 GB | TEO Local | Minimum — kræver USB SSD |
| Raspberry Pi 4 (2 GB) | 2 GB | Alle funktioner | God til de fleste |
| **Raspberry Pi 4 (4 GB)** | **4 GB** | **Alle funktioner** | **Anbefalet** |
| Raspberry Pi 5 (4 GB) | 4 GB | Alle funktioner | Bedste ydelse |
| Raspberry Pi 5 (8 GB) | 8 GB | Alle funktioner | Fremtidssikret |
| Intel NUC / x86 Linux | 4+ GB | Alle funktioner | Alternativ til Pi |
| Synology NAS (Docker) | 2+ GB | Alle funktioner | Kører i Docker |

> **Vigtigt:** Brug altid USB SSD som systemdisk. SD-kort slides hurtigt ned ved 24/7-drift.

---

### Understøttede enheder

#### Batterier

| Mærke / Model | Protokol | Lokal kontrol | Kræver konto |
|---|---|---|---|
| Enphase IQ Battery 3T / 5P | Lokal HTTP API | ✅ Fuld | DIY Enlighten |
| Victron Energy (alle med Venus OS) | MQTT | ✅ Fuld | Nej |
| BYD Battery-Box HVS/HVM/HVL/LVS | Modbus TCP | 🔍 Kun aflæsning | Nej |
| SMA Sunny Boy Storage | Modbus TCP | ✅ Fuld | Nej |
| Huawei LUNA 2000 | Modbus TCP | 🔍 Kun aflæsning | Nej |
| Sonnen eco / ecoLinx | Lokal REST API | ✅ Fuld | Nej |
| Tesla Powerwall 2 / 3 | Lokal API | ✅ Fuld | Nej |

#### Invertere

| Mærke / Model | Protokol | Auto-discovery |
|---|---|---|
| Enphase Envoy-S Metered | Lokal HTTP API | mDNS (envoy.local) |
| SolarEdge HD-Wave | Modbus TCP | Netværksscan |
| Fronius Symo / Gen24 | SunSpec Modbus | mDNS |
| Huawei SUN2000 | Modbus TCP | Netværksscan |
| Goodwe | SolarmanV5 | Netværksscan |
| Kostal Plenticore | Modbus TCP | mDNS |

#### EV-ladere

| Mærke / Model | Protokol | Lokal/Cloud | Kræver konto |
|---|---|---|---|
| Easee Home / Charge / Base | Cloud REST API | Cloud | Easee-konto |
| Zaptec Go / Pro | Cloud REST API | Cloud | Zaptec-konto |
| go-e Charger Gemini | Lokal REST API | **100% lokal** | Nej |
| Wallbox Pulsar Plus | Lokal REST API | **100% lokal** | Nej |
| KEBA P30 | UDP + Modbus | **100% lokal** | Nej |
| OCPP 1.6 kompatible | OCPP WebSocket | Afhænger | Afhænger |

#### Elmålere

| Mærke / Model | Protokol | Lokal/Cloud | Kræver konto |
|---|---|---|---|
| AMS/HAN-reader (alle nordiske) | MQTT | **100% lokal** | Nej |
| Shelly EM / 3EM / Pro 3EM | Lokal REST API | **100% lokal** | Nej |
| HomeWizard P1 Meter | Lokal REST API | **100% lokal** | Nej* |
| Tibber Pulse | Cloud API | Cloud | Tibber-konto |
| Kamstrup / Iskra (HAN P1-port) | HAN P1 | **100% lokal** | Nej |

> *HomeWizard: aktiver "Local API" i HomeWizard Energy-appen før brug.

---

### Særlige krav per enhed

#### Enphase IQ Battery
Fuld batteristyring (reserve + netladning) kræver en **DIY Enlighten Manager-konto**:
1. Gå til [enlighten.enphaseenergy.com](https://enlighten.enphaseenergy.com)
2. Log ind med din Enphase-konto
3. Aktivér DIY-adgang under dit system
4. Indtast email og adgangskode i TEO-wizard

Uden DIY-konto: TEO kan kun aflæse batteriniveau og solproduktion.

#### Victron Energy
Kræver Venus OS med MQTT aktiveret:
1. Åbn Venus OS Remote Console
2. Gå til **Settings → Services → MQTT on LAN (plaintext)**
3. Aktivér
4. Find system serial under **System → Serial**

#### BYD Battery-Box
- Forbind batteriet med **netværkskabel** (WiFi deaktiverer sig efter timeout)
- Standard IP: `192.168.16.254` — eller find den i din router
- Kun aflæsning — ingen lokal styring via TEO

#### HomeWizard P1 Meter
Aktiver Local API i appen:
**Indstillinger → Målere → P1 Meter → Local API → Aktiver**

#### AMS/HAN-reader
Konfigurér din reader til at sende til lokal MQTT-broker:
- Server: Pi'ens IP-adresse
- Port: 1883
- Topic: `ams/power`

---

### Softwarekrav

TEO installerer automatisk alle afhængigheder via installationsscriptet. Ved manuel installation:

- Home Assistant OS 2024.1 eller nyere
- HACS (Home Assistant Community Store)
- Mosquitto MQTT broker (HA add-on)
- Python-pakker: `scipy>=1.11`, `holidays>=0.40` (installeres automatisk)

---

<a name="english"></a>
## English

### Hardware requirements

| Model | RAM | Supports | Notes |
|---|---|---|---|
| Raspberry Pi 3B/3B+ | 1 GB | All features | Minimum — requires USB SSD |
| **Raspberry Pi 4 (4 GB)** | **4 GB** | **All features** | **Recommended** |
| Raspberry Pi 5 | 4-8 GB | All features | Best performance |
| Intel NUC / x86 Linux | 4+ GB | All features | Alternative to Pi |
| Synology NAS (Docker) | 2+ GB | All features | Docker container |

### Supported devices

See the Danish section above for complete device tables — they apply to both languages.

Key notes for English-speaking users:
- **Enphase**: requires DIY Enlighten Manager account for full battery control
- **Victron**: requires Venus OS with MQTT enabled
- **HomeWizard**: enable Local API in the HomeWizard Energy app before use
- **AMS/HAN readers**: configure to send MQTT to your Pi's IP on port 1883, topic `ams/power`
