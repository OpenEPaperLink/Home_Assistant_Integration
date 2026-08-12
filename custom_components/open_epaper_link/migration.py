"""One-shot migration from the pre-4.0 identifier scheme.

The old scheme was inconsistent and in places actively harmful:

- Tag entities used a bare ``{MAC}_{key}`` unique_id with no domain or entry
  scoping, so they could collide with any other integration.
- ATC (Bluetooth) entities used an ``oepl_ble_`` prefix set via a ``unique_id``
  property override rather than ``_attr_unique_id``, and repeated the MAC even
  though the config entry already *is* the device.
- The AP device used a hardcoded ``(DOMAIN, "ap")`` identifier, so a second AP
  collided with the first. That permanently blocked multi-AP setups.
- Config entries were keyed on the host string, so the same AP at a new
  address re-added as a duplicate entry.

Nothing is preserved for its own sake: the identifiers are redesigned and the
registries rewritten to match.

Entity ids are deliberately *not* touched. The old code pinned tag sensors to
``open_epaper_link.<mac>_<key>``, but ``entity_platform`` splits that and keeps
only the object id, so the registry always held a correctly-domained
``sensor.<mac>_<key>``. Existing entity ids therefore stay valid and keep
working; only newly discovered tags get name-derived slugs.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_AP_MAC,
    CONF_DEVICE_TYPE,
    CONF_HOST,
    DOMAIN,
    REMOVED_SENSOR_KEYS,
)

_LOGGER = logging.getLogger(__name__)

# Pre-4.0 unique_id prefix for what are now called ATC tags.
_LEGACY_ATC_PREFIX = "oepl_ble_"


def migrate_unique_id(old: str, entry_id: str) -> str:
    """Map a pre-4.0 unique_id onto the new entry-scoped scheme.

    Idempotent: an already-migrated id is returned unchanged, so a partially
    completed migration can safely be re-run.
    """
    if old.startswith(f"{entry_id}_"):
        # AP entities were already entry-scoped, as is anything we migrated on
        # an earlier pass.
        return old

    if old.startswith(_LEGACY_ATC_PREFIX):
        # oepl_ble_<MAC>_<key>. The MAC is redundant because an ATC entry *is*
        # the device, so drop it and keep the key.
        remainder = old[len(_LEGACY_ATC_PREFIX) :]
        _, _, key = remainder.partition("_")
        return f"{entry_id}_{key}" if key else f"{entry_id}_{remainder}"

    # Everything else is a tag entity keyed as <MAC>_<key>.
    return f"{entry_id}_{old}"


def _removed_sensor_key(unique_id: str) -> bool:
    """Whether *unique_id* belongs to one of the dropped derived counters."""
    return any(unique_id.endswith(f"_{key}") for key in REMOVED_SENSOR_KEYS)


@callback
def async_migrate_entry_data(hass: HomeAssistant, entry, ap_mac: str | None) -> None:
    """Bring a config entry's stored data up to the 4.0 shape."""
    data = dict(entry.data)
    unique_id = entry.unique_id
    changed = False

    # Drop both stored discriminators. An AP entry has a host and an ATC entry
    # does not, which already tells them apart, and after setup the runtime data
    # type says so with real type information. protocol_type existed only to
    # choose between two Bluetooth protocols; the other went in 3.0.0.
    is_ap = CONF_HOST in data
    for obsolete in (CONF_DEVICE_TYPE, "protocol_type"):
        if data.pop(obsolete, None) is not None:
            changed = True

    # The host is mutable -- DHCP moves it -- so it was never a valid identity.
    # The MAC comes from the AP's own wifi config and is stable, and DHCP
    # discovery reports the same value, letting a discovery match an entry that
    # was originally added by hand.
    if ap_mac and is_ap:
        formatted = dr.format_mac(ap_mac)
        if unique_id != formatted or data.get(CONF_AP_MAC) != formatted:
            unique_id = formatted
            data[CONF_AP_MAC] = formatted
            changed = True

    if not changed:
        return

    hass.config_entries.async_update_entry(entry, unique_id=unique_id, data=data)
    _LOGGER.debug("Migrated config entry data for %s", entry.entry_id)


@callback
def async_migrate_registries(hass: HomeAssistant, entry) -> None:
    """Rewrite this entry's entity and device registry rows.

    Only rows belonging to *entry* are touched.
    """
    _async_migrate_entities(hass, entry)
    _async_migrate_devices(hass, entry)


def _async_migrate_entities(hass: HomeAssistant, entry) -> None:
    """Drop removed sensors, then re-key whatever remains."""
    registry = er.async_get(hass)

    for record in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        if _removed_sensor_key(record.unique_id):
            _LOGGER.debug("Removing dropped sensor %s", record.entity_id)
            registry.async_remove(record.entity_id)
            continue

        new_unique_id = migrate_unique_id(record.unique_id, entry.entry_id)
        if new_unique_id == record.unique_id:
            continue

        if registry.async_get_entity_id(record.domain, DOMAIN, new_unique_id) not in (
            None,
            record.entity_id,
        ):
            _LOGGER.warning(
                "Skipping migration of %s: unique_id %s is already taken",
                record.entity_id,
                new_unique_id,
            )
            continue

        registry.async_update_entity(record.entity_id, new_unique_id=new_unique_id)


def _async_migrate_devices(hass: HomeAssistant, entry) -> None:
    """Scope device identifiers to the config entry.

    ``via_device`` links survive because the registry tracks them by internal
    device id, not by identifier tuple.
    """
    registry = dr.async_get(hass)

    for device in list(dr.async_entries_for_config_entry(registry, entry.entry_id)):
        new_identifiers = set()
        changed = False

        for domain, value in device.identifiers:
            if domain != DOMAIN or value.startswith(f"{entry.entry_id}_"):
                new_identifiers.add((domain, value))
                continue

            # (DOMAIN, "ap") -> the AP itself; (DOMAIN, "ble_<MAC>") and
            # (DOMAIN, "<MAC>") -> a tag.
            suffix = value[4:] if value.startswith("ble_") else value
            new_identifiers.add((domain, f"{entry.entry_id}_{suffix}"))
            changed = True

        if changed:
            registry.async_update_device(device.id, new_identifiers=new_identifiers)
