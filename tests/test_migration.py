"""Tests for the registry migration.

This is the riskiest code in the rewrite: a mistake here silently orphans a
user's entire setup. Every old identifier shape gets an explicit case.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN
from custom_components.open_epaper_link.migration import (
    async_migrate_entry_data,
    async_migrate_registries,
    migrate_unique_id,
)

from .conftest import AP_HOST, AP_MAC

ENTRY_ID = "01JABCDEF0123456789"
TAG = "00000335042F3E10"
ATC_MAC = "AA:BB:CC:DD:EE:01"


# ---------------------------------------------------------------------------
# Pure unique_id mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "expected"),
    [
        # Tag entities: bare MAC prefix, no domain or entry scoping.
        (f"{TAG}_temperature", f"{ENTRY_ID}_{TAG}_temperature"),
        (f"{TAG}_battery_voltage", f"{ENTRY_ID}_{TAG}_battery_voltage"),
        (f"{TAG}_alias", f"{ENTRY_ID}_{TAG}_alias"),
        (f"{TAG}_display_content", f"{ENTRY_ID}_{TAG}_display_content"),
        (f"{TAG}_clear_pending", f"{ENTRY_ID}_{TAG}_clear_pending"),
        # AP entities were already entry-scoped and must not change.
        (f"{ENTRY_ID}_ap_state", f"{ENTRY_ID}_ap_state"),
        (f"{ENTRY_ID}_reboot_ap", f"{ENTRY_ID}_reboot_ap"),
        (f"{ENTRY_ID}_channel", f"{ENTRY_ID}_channel"),
        # BLE entities carried an oepl_ble_ prefix.
        (f"oepl_ble_{ATC_MAC}_light", f"{ENTRY_ID}_light"),
        (f"oepl_ble_{ATC_MAC}_display_content", f"{ENTRY_ID}_display_content"),
        (f"oepl_ble_{ATC_MAC}_battery", f"{ENTRY_ID}_battery"),
    ],
)
def test_migrate_unique_id(old: str, expected: str) -> None:
    """Every old shape maps to exactly one new shape."""
    assert migrate_unique_id(old, ENTRY_ID) == expected


def test_migrate_unique_id_is_idempotent() -> None:
    """Running the migration twice must not double-prefix."""
    once = migrate_unique_id(f"{TAG}_temperature", ENTRY_ID)
    assert migrate_unique_id(once, ENTRY_ID) == once


def test_migrate_unique_id_never_collides() -> None:
    """Distinct old ids must never map onto the same new id."""
    olds = [
        f"{TAG}_temperature",
        f"{TAG}_alias",
        f"{ENTRY_ID}_ap_state",
        f"oepl_ble_{ATC_MAC}_light",
    ]
    news = [migrate_unique_id(o, ENTRY_ID) for o in olds]
    assert len(set(news)) == len(news)


# ---------------------------------------------------------------------------
# Config entry re-keying
# ---------------------------------------------------------------------------


async def test_entry_rekeyed_from_host_to_mac(hass: HomeAssistant) -> None:
    """unique_id moves from the host string to the AP MAC.

    Keying on the host meant the same AP at a new address re-added as a
    duplicate entry.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=AP_HOST,
        data={"host": AP_HOST},
        version=4,
    )
    entry.add_to_hass(hass)

    async_migrate_entry_data(hass, entry, ap_mac=AP_MAC)

    assert entry.unique_id == dr.format_mac(AP_MAC)
    assert entry.data["host"] == AP_HOST
    assert entry.data["ap_mac"] == dr.format_mac(AP_MAC)


async def test_obsolete_discriminators_are_dropped(hass: HomeAssistant) -> None:
    """device_type and protocol_type are redundant and get stripped.

    An AP entry has a host and an ATC entry does not, which already tells them
    apart; protocol_type existed only to choose between two Bluetooth
    protocols, and the other was removed in 3.0.0.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=ATC_MAC,
        data={"mac_address": ATC_MAC, "device_type": "ble", "protocol_type": "atc"},
        version=4,
    )
    entry.add_to_hass(hass)

    async_migrate_entry_data(hass, entry, ap_mac=None)

    assert "device_type" not in entry.data
    assert "protocol_type" not in entry.data
    assert entry.data["mac_address"] == ATC_MAC


async def test_atc_entry_keeps_its_own_identity(hass: HomeAssistant) -> None:
    """An ATC entry has no host, so it must not be re-keyed onto an AP MAC."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=ATC_MAC,
        data={"mac_address": ATC_MAC, "device_type": "ble"},
        version=4,
    )
    entry.add_to_hass(hass)

    async_migrate_entry_data(hass, entry, ap_mac=AP_MAC)

    assert entry.unique_id == ATC_MAC
    assert "ap_mac" not in entry.data


async def test_entry_rekey_is_idempotent(hass: HomeAssistant) -> None:
    """A second run must not corrupt an already-migrated entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=dr.format_mac(AP_MAC),
        data={"host": AP_HOST, "ap_mac": dr.format_mac(AP_MAC)},
        version=5,
    )
    entry.add_to_hass(hass)

    async_migrate_entry_data(hass, entry, ap_mac=AP_MAC)

    assert entry.unique_id == dr.format_mac(AP_MAC)
    assert entry.data["host"] == AP_HOST


# ---------------------------------------------------------------------------
# Entity and device registries
# ---------------------------------------------------------------------------


async def test_entities_are_rekeyed_not_orphaned(hass: HomeAssistant) -> None:
    """Every pre-existing entity survives with a new unique_id."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    temperature = registry.async_get_or_create(
        "sensor", DOMAIN, f"{TAG}_temperature", config_entry=entry
    )
    ap_state = registry.async_get_or_create(
        "sensor", DOMAIN, f"{ENTRY_ID}_ap_state", config_entry=entry
    )

    async_migrate_registries(hass, entry)

    assert registry.async_get(temperature.entity_id).unique_id == (
        f"{ENTRY_ID}_{TAG}_temperature"
    )
    assert registry.async_get(ap_state.entity_id).unique_id == f"{ENTRY_ID}_ap_state"


async def test_removed_sensors_are_deleted(hass: HomeAssistant) -> None:
    """The four derived counters are gone; their entities must not linger."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    stale = [
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{TAG}_{key}", config_entry=entry
        )
        for key in ("runtime", "boot_count", "checkin_count", "block_requests")
    ]
    kept = registry.async_get_or_create(
        "sensor", DOMAIN, f"{TAG}_update_count", config_entry=entry
    )

    async_migrate_registries(hass, entry)

    for entity in stale:
        assert registry.async_get(entity.entity_id) is None
    assert registry.async_get(kept.entity_id) is not None


async def test_entity_ids_are_left_alone(hass: HomeAssistant) -> None:
    """Existing entity ids must survive so automations keep working.

    The old code pinned tag sensors to ``open_epaper_link.<mac>_<key>``, but
    entity_platform discards that domain and keeps only the object id, so the
    registry always held a correctly-domained ``sensor.<mac>_<key>``. There is
    nothing to repair, and re-slugging would break users' automations for no
    gain.
    """
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{TAG}_temperature",
        config_entry=entry,
        suggested_object_id=f"{TAG.lower()}_temperature",
    )
    original_entity_id = entity.entity_id
    assert original_entity_id == f"sensor.{TAG.lower()}_temperature"

    async_migrate_registries(hass, entry)

    migrated = registry.async_get(original_entity_id)
    assert migrated is not None
    assert migrated.entity_id == original_entity_id
    assert migrated.unique_id == f"{ENTRY_ID}_{TAG}_temperature"


async def test_device_identifiers_are_entry_scoped(hass: HomeAssistant) -> None:
    """Device identifiers gain the entry id, unblocking multi-AP setups.

    The AP device used a hardcoded (DOMAIN, "ap"), so two APs collided.
    """
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)

    ap = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "ap")}, name="AP"
    )
    tag = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, TAG)}, name="Tag"
    )

    async_migrate_registries(hass, entry)

    assert registry.async_get(ap.id).identifiers == {(DOMAIN, f"{ENTRY_ID}_ap")}
    assert registry.async_get(tag.id).identifiers == {(DOMAIN, f"{ENTRY_ID}_{TAG}")}


async def test_via_device_link_survives(hass: HomeAssistant) -> None:
    """Tags hang off the AP; re-identifying must not sever that."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)

    ap = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "ap")}, name="AP"
    )
    tag = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, TAG)},
        via_device=(DOMAIN, "ap"),
        name="Tag",
    )
    assert registry.async_get(tag.id).via_device_id == ap.id

    async_migrate_registries(hass, entry)

    assert registry.async_get(tag.id).via_device_id == registry.async_get(ap.id).id


async def test_migration_is_idempotent(hass: HomeAssistant) -> None:
    """Running twice must leave the registries unchanged the second time."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{TAG}_temperature", config_entry=entry
    )
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, TAG)}, name="Tag"
    )

    async_migrate_registries(hass, entry)
    first_entities = {e.entity_id: e.unique_id for e in ent_reg.entities.values()}
    first_devices = {d.id: d.identifiers for d in dev_reg.devices.values()}

    async_migrate_registries(hass, entry)

    assert {e.entity_id: e.unique_id for e in ent_reg.entities.values()} == first_entities
    assert {d.id: d.identifiers for d in dev_reg.devices.values()} == first_devices


async def test_other_integrations_untouched(hass: HomeAssistant) -> None:
    """Migration must only ever touch this config entry's own registry rows."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID, version=4)
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain="other", entry_id="OTHERENTRY")
    other.add_to_hass(hass)
    registry = er.async_get(hass)

    foreign = registry.async_get_or_create(
        "sensor", "other", f"{TAG}_temperature", config_entry=other
    )

    async_migrate_registries(hass, entry)

    assert registry.async_get(foreign.entity_id).unique_id == f"{TAG}_temperature"
