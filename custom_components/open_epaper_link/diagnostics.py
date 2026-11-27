"""Diagnostics for OpenEPaperLink Access Points and ATC tags."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from . import OpenEPaperLinkConfigEntry, _is_ap_entry
from .atc_coordinator import ATCConfigEntry
from .const import CONF_AP_MAC, CONF_HOST, CONF_MAC_ADDRESS, OPT_BLACKLISTED_TAGS
from .coordinator import APConfigEntry

# Fields that locate the network or the Access Point on it. MACs are handled
# separately, so tags stay distinguishable from one another.
TO_REDACT = {
    CONF_HOST,
    "ap_ip",
    "wifi_ssid",
    # A tag's content configuration can carry URLs and tokens for the
    # Access Point's own content modes.
    "modecfgjson",
}


def _redact_mac(mac: str) -> str:
    """Hide a MAC but keep its last four digits, which tell tags apart."""
    clean = mac.replace(":", "").replace("-", "").upper()
    return f"{REDACTED}{clean[-4:]}" if clean else REDACTED


def _as_dict(obj: object) -> dict[str, Any] | None:
    """Turn a library model into a dict, without the raw payload it came from.

    ``raw`` holds every key the device sent, including ones not modelled, so
    nothing in it could be redacted by name.
    """
    if obj is None or not is_dataclass(obj) or isinstance(obj, type):
        return None
    data = asdict(obj)
    data.pop("raw", None)
    return async_redact_data(data, TO_REDACT)


def _entry_info(entry: OpenEPaperLinkConfigEntry) -> dict[str, Any]:
    """Describe the config entry itself."""
    data = dict(entry.data)
    for key in (CONF_AP_MAC, CONF_MAC_ADDRESS):
        if key in data:
            data[key] = _redact_mac(str(data[key]))
    options = dict(entry.options)
    if OPT_BLACKLISTED_TAGS in options:
        options[OPT_BLACKLISTED_TAGS] = [
            _redact_mac(str(mac)) for mac in options[OPT_BLACKLISTED_TAGS]
        ]
    return {
        "title": entry.title,
        "version": entry.version,
        "minor_version": entry.minor_version,
        "data": async_redact_data(data, TO_REDACT),
        "options": async_redact_data(options, TO_REDACT),
    }


def _ap_diagnostics(entry: APConfigEntry) -> dict[str, Any]:
    """Describe an Access Point and the tags it shows."""
    coordinator = entry.runtime_data
    tags: dict[str, Any] = {}
    for mac, tag in coordinator.data.items():
        info = _as_dict(tag) or {}
        info["mac"] = _redact_mac(mac)
        if info.get("alias", "").replace(":", "").upper() == mac.upper():
            info["alias"] = info["mac"]
        info["tag_type"] = coordinator.tag_type_name(mac)
        info["is_ap_display"] = coordinator.is_ap_display(mac)
        tags[info["mac"]] = info
    return {
        "type": "access_point",
        "online": coordinator.online,
        "last_update_success": coordinator.last_update_success,
        "info": _as_dict(coordinator.ap_info),
        "config": _as_dict(coordinator.ap_config),
        "status": _as_dict(coordinator.ap_status),
        # The Access Point lists every tag in the mesh; this entry shows only
        # the ones it owns and the user has not hidden.
        "tags_reported": len(coordinator.client.tags),
        "tags_shown": len(tags),
        "tags": tags,
    }


def _atc_diagnostics(entry: ATCConfigEntry) -> dict[str, Any]:
    """Describe an ATC tag from what it reported at setup and advertises."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    update = coordinator.data
    return {
        "type": "atc",
        "available": coordinator.available,
        "capabilities": _as_dict(runtime.capabilities),
        "device_config": _as_dict(coordinator.device_config),
        "advertisement": _as_dict(update.advertisement) if update else None,
        "has_rendered_image": coordinator.rendered is not None,
        "upload_in_progress": (
            runtime.upload_task is not None and not runtime.upload_task.done()
        ),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: OpenEPaperLinkConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    device = _ap_diagnostics(entry) if _is_ap_entry(entry) else _atc_diagnostics(entry)
    return {"entry": _entry_info(entry), "device": device}
