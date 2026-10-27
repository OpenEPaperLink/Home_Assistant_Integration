"""The OpenEPaperLink integration."""

from __future__ import annotations

import logging
from typing import TypeIs

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from py_atc_ble_oepl import ATCDevice, ATCError

from .atc_coordinator import ATCConfigEntry, ATCCoordinator, ATCRuntimeData
from .const import CONF_HOST, CONF_MAC_ADDRESS, SIGNAL_ENTRIES_CHANGED
from .coordinator import APConfigEntry, APCoordinator
from .migration import (
    async_migrate_entry_data,
    async_migrate_entry_title,
    async_migrate_registries,
)
from .services import async_register_services

type OpenEPaperLinkConfigEntry = APConfigEntry | ATCConfigEntry

_LOGGER = logging.getLogger(__name__)

ATC_PLATFORMS: list[Platform] = [
    Platform.IMAGE,
    Platform.SENSOR,
    Platform.UPDATE,
]

AP_PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]


def _is_ap_entry(entry: OpenEPaperLinkConfigEntry) -> TypeIs[APConfigEntry]:
    """Whether *entry* is an Access Point rather than a Bluetooth tag.

    An AP entry has a host; an ATC entry does not. That is the whole
    discriminator -- see migration.py for why the stored one was dropped.

    Returns TypeIs rather than bool so the two entry types, which carry
    different runtime_data, are told apart in both branches. TypeGuard would
    only narrow the true one.
    """
    return CONF_HOST in entry.data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Register actions, which exist independently of any config entry."""
    async_register_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> bool:
    """Set up an Access Point or an ATC tag from a config entry."""
    if not _is_ap_entry(entry):
        return await _async_setup_atc_entry(hass, entry)

    coordinator = APCoordinator(hass, entry)
    await coordinator.async_setup()

    # Re-key the entry onto the AP's own MAC now that we can ask for it. This
    # deliberately happens here rather than in async_migrate_entry: it needs a
    # round trip to the AP, and migrations should not do network I/O.
    async_migrate_entry_data(hass, entry, ap_mac=coordinator.ap_mac)
    async_migrate_entry_title(hass, entry, coordinator.ap_name)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, AP_PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Sibling entries re-run the mesh ownership rule when this one appears, so
    # a tag stops being shown twice as soon as its own AP is added.
    async_dispatcher_send(hass, SIGNAL_ENTRIES_CHANGED)
    return True


async def _async_setup_atc_entry(hass: HomeAssistant, entry: ATCConfigEntry) -> bool:
    """Set up a tag running ATC firmware.

    The tag is interrogated once here for its panel geometry, which cannot
    change and is then read from runtime data rather than costing a connection
    on every draw. A tag that cannot be reached leaves the entry not ready: it
    sleeps only seconds between advertisements, so this retries quickly, and a
    tag nobody can reach has nothing usable to offer.
    """
    address = entry.data[CONF_MAC_ADDRESS]
    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"{address} is not currently reachable")

    # auto_interrogate would query inside __aenter__ and hand back nothing:
    # the capabilities object is only obtainable as interrogate()'s return
    # value, so leaving it on would query twice.
    device = ATCDevice(address, ble_device=ble_device, auto_interrogate=False)
    try:
        async with device:
            capabilities = await device.interrogate()
    except ATCError as err:
        raise ConfigEntryNotReady(f"Could not interrogate {address}: {err}") from err

    coordinator = ATCCoordinator(hass, address)
    entry.runtime_data = ATCRuntimeData(
        coordinator=coordinator,
        device=device,
        capabilities=capabilities,
    )
    await hass.config_entries.async_forward_entry_setups(entry, ATC_PLATFORMS)
    # Started last, so entities are subscribed before advertisements arrive.
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
) -> bool:
    """Unload a config entry."""
    if not _is_ap_entry(entry):
        return await hass.config_entries.async_unload_platforms(entry, ATC_PLATFORMS)

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
