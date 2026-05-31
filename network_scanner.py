"""Netværksscanner — auto-discovery til wizard trin 4 (spec §3.6).

To-trins opdagelse:
  1. mDNS/Zeroconf (øjeblikkelig)
  2. API-fingerprints via parallel scanning af brugerens eget /24-subnet

Designprincip: scanner KUN brugerens eget subnet. Ingen ekstern scanning.
Timeout pr. IP: 500 ms. Kører parallelt (asyncio). Max 254 hosts.

Modulet degraderer pænt: mangler aiohttp eller zeroconf, springes det
pågældende trin over med en advarsel frem for at kaste fejl.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import socket
from typing import Any, Optional

from .const import (
    CATEGORY_BATTERY,
    CATEGORY_GRID_METER,
    DEFAULT_MQTT_PORT,
    DISCOVERY_FINGERPRINT,
    DISCOVERY_MDNS,
    FINGERPRINT_EASEE,
    FINGERPRINT_ENPHASE,
    FINGERPRINT_GOE,
    FINGERPRINT_ZAPTEC,
    MDNS_SERVICE_TYPES,
    SCAN_MAX_HOSTS,
    SCAN_MAX_WORKERS,
    SCAN_TIMEOUT_PER_IP_SEC,
)

_LOGGER = logging.getLogger(__name__)

# HTTP-fingerprints: (port, sti, søgetekst, kategori, mærke, kræver_https)
_HTTP_FINGERPRINTS: tuple[tuple, ...] = (
    (*FINGERPRINT_ENPHASE, True),   # 443 /info  "envoy"
    (*FINGERPRINT_EASEE, False),    # 4123 /api/charger "easee"
    (*FINGERPRINT_ZAPTEC, False),   # 80 /api "zaptec"
    (*FINGERPRINT_GOE, False),      # 80 /api/info "go-e"
)


def get_local_subnet(own_ip: Optional[str] = None) -> Optional[ipaddress.IPv4Network]:
    """Find brugerens eget /24-subnet ud fra Pi'ens udgående interface-IP.

    Bruger en UDP-socket til at bestemme kilde-IP uden at sende pakker.
    """
    ip = own_ip or _detect_own_ip()
    if not ip:
        return None
    try:
        return ipaddress.ip_network(f"{ip}/24", strict=False)
    except ValueError:
        return None


def _detect_own_ip() -> Optional[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Forbindelsen sender ingen datagrammer; vælger blot udgående interface.
        sock.connect(("192.168.1.1", 9))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    finally:
        sock.close()


async def scan_all(zeroconf: Any = None,
                   own_ip: Optional[str] = None) -> list[dict[str, Any]]:
    """Kør fuld opdagelse og returnér en dedupliceret enhedsliste."""
    results: list[dict[str, Any]] = []

    with contextlib.suppress(Exception):
        results.extend(await scan_mdns(zeroconf))

    subnet = get_local_subnet(own_ip)
    if subnet is not None:
        with contextlib.suppress(Exception):
            results.extend(await scan_fingerprints(subnet))
    else:
        _LOGGER.warning("Kunne ikke bestemme eget subnet — springer fingerprint over")

    return _dedupe(results)


async def scan_mdns(zeroconf: Any) -> list[dict[str, Any]]:
    """mDNS/Zeroconf-opdagelse. Returnerer tom liste hvis zeroconf mangler."""
    if zeroconf is None:
        return []
    try:
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo
    except ImportError:
        _LOGGER.debug("zeroconf ikke tilgængelig — springer mDNS over")
        return []

    found: list[dict[str, Any]] = []
    discovered: list[tuple[str, str]] = []

    def _on_change(zc, service_type, name, state_change):  # noqa: ANN001
        discovered.append((service_type, name))

    browsers = [
        AsyncServiceBrowser(zeroconf, st, handlers=[_on_change])
        for st in MDNS_SERVICE_TYPES
    ]
    try:
        await asyncio.sleep(2)  # kort lyttevindue
        for service_type, name in discovered:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(zeroconf, 2000):
                continue
            for addr in info.parsed_addresses():
                category, brand = _classify_mdns(service_type, name)
                if category:
                    found.append(_device(category, brand, addr,
                                          info.port or 80, DISCOVERY_MDNS))
    finally:
        for b in browsers:
            with contextlib.suppress(Exception):
                await b.async_cancel()
    return found


def _classify_mdns(service_type: str, name: str) -> tuple[Optional[str], str]:
    lowered = f"{service_type} {name}".lower()
    if "enphase" in lowered or "envoy" in lowered:
        return CATEGORY_BATTERY, "enphase"
    return None, ""


async def scan_fingerprints(
    subnet: ipaddress.IPv4Network,
) -> list[dict[str, Any]]:
    """Scan alle hosts i subnettet parallelt mod kendte API-fingerprints."""
    hosts = [str(h) for h in subnet.hosts()][:SCAN_MAX_HOSTS]
    semaphore = asyncio.Semaphore(SCAN_MAX_WORKERS)

    try:
        import aiohttp
    except ImportError:
        _LOGGER.warning("aiohttp ikke tilgængelig — springer fingerprint over")
        return []

    connector = aiohttp.TCPConnector(ssl=False, limit=SCAN_MAX_WORKERS)
    timeout = aiohttp.ClientTimeout(total=SCAN_TIMEOUT_PER_IP_SEC)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async def probe(ip: str) -> list[dict[str, Any]]:
            async with semaphore:
                return await _probe_host(session, ip)

        nested = await asyncio.gather(*(probe(ip) for ip in hosts),
                                      return_exceptions=True)

    results: list[dict[str, Any]] = []
    for item in nested:
        if isinstance(item, list):
            results.extend(item)
    return results


async def _probe_host(session: Any, ip: str) -> list[dict[str, Any]]:
    """Prøv alle HTTP-fingerprints + en let TCP-check for MQTT (AMS) mod én host."""
    found: list[dict[str, Any]] = []

    for port, path, needle, category, brand, https in _HTTP_FINGERPRINTS:
        scheme = "https" if https else "http"
        url = f"{scheme}://{ip}:{port}{path}"
        try:
            async with session.get(url) as resp:
                text = (await resp.text()).lower()
        except Exception:  # noqa: BLE001 — lukket port/timeout er normalt
            continue
        if needle in text:
            found.append(_device(category, brand, ip, port, DISCOVERY_FINGERPRINT,
                                  requires_auth=(brand == "enphase")))
            # Enphase Envoy huser også batteriet — tilbyd begge i wizarden.
            if brand == "enphase":
                found.append(_device(CATEGORY_BATTERY, "enphase", ip, port,
                                      DISCOVERY_FINGERPRINT, requires_auth=True))

    # AMS/HAN-reader: MQTT-broker-port åben (selve topic'et verificeres senere).
    if await _tcp_open(ip, DEFAULT_MQTT_PORT):
        found.append(_device(CATEGORY_GRID_METER, "ams_han", ip,
                             DEFAULT_MQTT_PORT, DISCOVERY_FINGERPRINT))

    return found


async def _tcp_open(ip: str, port: int) -> bool:
    """True hvis en TCP-port svarer inden for timeout."""
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout=SCAN_TIMEOUT_PER_IP_SEC)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def _device(category: str, brand: str, ip: str, port: int, method: str,
            requires_auth: bool = False) -> dict[str, Any]:
    return {
        "category": category,
        "brand": brand,
        "model": None,
        "ip": ip,
        "port": port,
        "discovery_method": method,
        "requires_auth": requires_auth,
        "auth_instructions": None,  # wizarden slår per-mærke vejledning op i translations
    }


def _dedupe(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fjern dubletter på (kategori, ip, mærke). mDNS-fund foretrækkes."""
    seen: dict[tuple, dict] = {}
    for dev in devices:
        key = (dev["category"], dev["ip"], dev["brand"])
        if key not in seen or dev["discovery_method"] == DISCOVERY_MDNS:
            seen[key] = dev
    return list(seen.values())
