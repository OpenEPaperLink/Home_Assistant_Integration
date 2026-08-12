"""The OpenEPaperLink integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import CONF_HOST, SIGNAL_ENTRIES_CHANGED
from .coordinator import APCoordinator
from .migration import async_migrate_entry_data, async_migrate_registries
from .runtime_data import OpenEPaperLinkConfigEntry

_LOGGER = logging.getLogger(__name__)

AP_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]


def _is_ap_entry(entry: OpenEPaperLinkConfigEntry) -> bool:
    """Whether *entry* is an Access Point rather than a Bluetooth tag.

    An AP entry has a host; an ATC entry does not. That is the whole
    discriminator -- see migration.py for why the stored one was dropped.
    """
    return CONF_HOST in entry.data


async def async_setup_entry(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> bool:
    """Set up an Access Point from a config entry."""
    if not _is_ap_entry(entry):
        # ATC (Bluetooth) tags are set up separately; see atc_coordinator.
        raise NotImplementedError("ATC entries are not yet supported")

    coordinator = APCoordinator(hass, entry)
    await coordinator.async_setup()

    # Re-key the entry onto the AP's own MAC now that we can ask for it. This
    # deliberately happens here rather than in async_migrate_entry: it needs a
    # round trip to the AP, and migrations should not do network I/O.
    async_migrate_entry_data(hass, entry, ap_mac=coordinator.ap_mac)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, AP_PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Sibling entries re-run the mesh ownership rule when this one appears, so
    # a tag stops being shown twice as soon as its own AP is added.
    async_dispatcher_send(hass, SIGNAL_ENTRIES_CHANGED)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> bool:
    """Unload a config entry."""
    if not _is_ap_entry(entry):
        return True

    unloaded = await hass.config_entries.async_unload_platforms(entry, AP_PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
        # Remaining entries may now own tags this one was claiming.
        async_dispatcher_send(hass, SIGNAL_ENTRIES_CHANGED)
    return unloaded


async def async_migrate_entry(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> bool:
    """Migrate an entry from the pre-4.0 identifier scheme.

    Only registry and stored-data changes happen here. Re-keying the entry onto
    the AP's MAC needs to talk to the AP, so it runs during setup instead.
    """
    if entry.version >= 5:
        return True

    _LOGGER.debug(
        "Migrating config entry %s from version %s", entry.entry_id, entry.version
    )
    async_migrate_entry_data(hass, entry, ap_mac=None)
    async_migrate_registries(hass, entry)
    hass.config_entries.async_update_entry(entry, version=5)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
