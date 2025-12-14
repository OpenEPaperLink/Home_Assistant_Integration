"""Diagnostics support for OpenEPaperLink."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import Hub
from .runtime_data import OpenEPaperLinkConfigEntry, OpenEPaperLinkBLERuntimeData

# Sensitive fields to redact
TO_REDACT = {
    CONF_HOST,  # AP IP address
    "wifi_ssid",  # WiFi network name
    "ip",  # AP IP in status
}


# Partial redaction for MAC addresses (show last 4 chars)
def _clean_mac(mac: str) -> str:
    return mac.replace(":", "").replace("-", "").upper()


def _redact_mac(mac: str) -> str:
    if not mac:
        return "**REDACTED**"
    clean = _clean_mac(mac)
    suffix = clean[-4:] if len(clean) >= 4 else clean
    return f"**REDACTED**{suffix}"


def _redact_name_if_mac(name: str | None, mac: str) -> str | None:
    if not name:
        return name
    if _clean_mac(name) == _clean_mac(mac):
        return _redact_mac(mac)
    return name


def _redact_tag_data(tags: dict[str, dict]) -> dict[str, dict]:
    result = {}
    for mac, data in tags.items():
        redacted_mac = _redact_mac(mac)
        redacted_data = dict(data)
        redacted_data["tag_mac"] = redacted_mac
        if "tag_name" in redacted_data:
            redacted_data["tag_name"] = _redact_name_if_mac(redacted_data["tag_name"], mac)
        if "modecfgjson" in redacted_data:
            redacted_data["modecfgjson"] = "**REDACTED**"
        result[redacted_mac] = redacted_data
    return result


async def async_get_config_entry_diagnostics(
        hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    title = entry.title
    host = entry.data.get(CONF_HOST)
    if host and host in title:
        title = title.replace(host, "**REDACTED**")

    # Common entry info
    diag: dict[str, Any] = {
        "config_entry": {
            "title": title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }

    runtime_data = entry.runtime_data

    if isinstance(runtime_data, Hub):
        # AP-based entry
        hub = runtime_data
        diag["device_type"] = "ap"
        diag["ap"] = {
            "online": hub.online,
            "model": hub.ap_model,
            "environment": hub.ap_env,
            "status": async_redact_data(hub.ap_status, TO_REDACT),
            "config": async_redact_data(hub.ap_config, TO_REDACT),
        }
        diag["tags"] = {
            "count": len(hub.tags),
            "blacklisted_count": len(hub.get_blacklisted_tags()),
            "data": _redact_tag_data({
                mac: hub.get_tag_data(mac) for mac in hub.tags
            }),
        }

    elif isinstance(runtime_data, OpenEPaperLinkBLERuntimeData):
        # BLE device entry
        ble_data = runtime_data
        diag["device_type"] = "ble"
        diag["ble"] = {
            "mac_address": _redact_mac(ble_data.mac_address),
            "name": _redact_name_if_mac(ble_data.name, ble_data.mac_address),
            "protocol_type": ble_data.protocol_type,
            "device_metadata": ble_data.device_metadata,  # Hardware specs (not sensitive)
            "sensor_count": len(ble_data.sensors),
        }

    return diag
