"""Sensors for the Access Point and its tags."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from oepl import APStatus, Tag
from oepl.enums import enum_label

from .atc_coordinator import ATCConfigEntry, ATCRuntimeData
from .atc_sensor import ATC_SENSORS, ATCSensor
from .coordinator import APConfigEntry, APCoordinator
from .entity import OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TagSensorDescription(SensorEntityDescription):
    """Describes a sensor reading a value off a tag."""

    value_fn: Callable[[Tag], int | float | str | datetime | None]


@dataclass(frozen=True, kw_only=True)
class APSensorDescription(SensorEntityDescription):
    """Describes a sensor reading a value off the Access Point."""

    value_fn: Callable[[APStatus], int | float | str | datetime | None]


def _battery_percentage(tag: Tag) -> float | None:
    """Estimate charge from cell voltage.

    A coin cell sits near 3.0 V for most of its life and falls off a cliff, so
    this is a rough indicator rather than a measurement. Tags with no usable
    reading report a sentinel rather than a voltage, which py-oepl knows
    about; treating it as a measurement showed a flat battery on a tag that
    simply had nothing to report.
    """
    if not tag.has_battery_reading:
        return None
    volts = tag.battery_mv / 1000
    return round(max(0.0, min(100.0, (volts - 2.2) / (3.0 - 2.2) * 100)), 1)


TAG_SENSORS: tuple[TagSensorDescription, ...] = (
    TagSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda tag: tag.temperature or None,
    ),
    TagSensorDescription(
        key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: tag.battery_mv if tag.has_battery_reading else None,
    ),
    TagSensorDescription(
        key="battery_percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_battery_percentage,
    ),
    TagSensorDescription(
        key="lqi",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: tag.lqi or None,
    ),
    TagSensorDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: tag.rssi or None,
    ),
    TagSensorDescription(
        key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda tag: tag.last_seen_at,
    ),
    TagSensorDescription(
        key="next_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: tag.next_update_at,
    ),
    TagSensorDescription(
        key="next_checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: tag.next_checkin_at,
    ),
    TagSensorDescription(
        key="pending_updates",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda tag: tag.pending,
    ),
    TagSensorDescription(
        key="update_count",
        # Maintained by the Access Point itself, so it survives restarts of
        # Home Assistant rather than counting what we happened to observe.
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda tag: tag.update_count,
    ),
    TagSensorDescription(
        key="wakeup_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: enum_label(tag.wakeup_reason),
    ),
    TagSensorDescription(
        key="content_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: enum_label(tag.content_mode),
    ),
    TagSensorDescription(
        key="capabilities",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda tag: ", ".join(tag.capabilities_list) or None,
    ),
)

# Geometry comes from the tag type rather than the tag, so these are resolved
# through the coordinator instead of a plain value_fn.
TAG_GEOMETRY_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="width",
        native_unit_of_measurement="px",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="height",
        native_unit_of_measurement="px",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

AP_SENSORS: tuple[APSensorDescription, ...] = (
    APSensorDescription(
        key="ap_state",
        value_fn=lambda status: enum_label(status.ap_state),
    ),
    APSensorDescription(
        key="run_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: enum_label(status.run_state),
    ),
    APSensorDescription(
        key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.rssi or None,
    ),
    APSensorDescription(
        key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.wifi_ssid or None,
    ),
    APSensorDescription(
        key="record_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.record_count,
    ),
    APSensorDescription(
        key="db_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.KILOBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.db_size,
    ),
    APSensorDescription(
        key="little_fs_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.KILOBYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.little_fs_free,
    ),
    APSensorDescription(
        key="heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.heap,
    ),
    APSensorDescription(
        key="ps_ram_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Absent on Access Points without PSRAM.
        value_fn=lambda status: status.ps_ram_free,
    ),
    APSensorDescription(
        key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.uptime or None,
    ),
    APSensorDescription(
        key="low_battery_tag_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # The Access Point only includes this about once a minute.
        value_fn=lambda status: status.low_battery_count,
    ),
    APSensorDescription(
        key="timeout_tag_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.timeout_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: APConfigEntry | ATCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for an Access Point and its tags, or for an ATC tag."""
    if isinstance(entry.runtime_data, ATCRuntimeData):
        async_add_entities(
            ATCSensor(entry.runtime_data.coordinator, entry.entry_id, description)
            for description in ATC_SENSORS
        )
        return

    coordinator = entry.runtime_data

    async_add_entities(APSensor(coordinator, description) for description in AP_SENSORS)
    async_add_entities([APHostSensor(coordinator)])

    known: set[str] = set()

    @callback
    def _async_add_new_tags() -> None:
        """Create sensors for tags that have appeared since the last check."""
        if new := set(coordinator.data) - known:
            known.update(new)
            async_add_entities(
                TagSensor(coordinator, mac, description)
                for mac in new
                for description in TAG_SENSORS
            )
            async_add_entities(
                TagGeometrySensor(coordinator, mac, description)
                for mac in new
                for description in TAG_GEOMETRY_SENSORS
            )

    _async_add_new_tags()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_tags))


class TagSensor(OpenEPaperLinkTagEntity, SensorEntity):
    """A sensor reading a value off a tag."""

    entity_description: TagSensorDescription

    def __init__(
        self, coordinator: APCoordinator, mac: str, description: TagSensorDescription
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, mac, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | str | datetime | None:
        """Return the current value."""
        tag = self.tag
        return self.entity_description.value_fn(tag) if tag else None


class APSensor(OpenEPaperLinkAPEntity, SensorEntity):
    """A sensor reading a value off the Access Point."""

    entity_description: APSensorDescription

    def __init__(
        self, coordinator: APCoordinator, description: APSensorDescription
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | str | datetime | None:
        """Return the current value."""
        status = self.coordinator.ap_status
        return self.entity_description.value_fn(status) if status else None


class TagGeometrySensor(OpenEPaperLinkTagEntity, SensorEntity):
    """Reports a tag's display dimensions, taken from its tag type."""

    def __init__(
        self, coordinator: APCoordinator, mac: str, description: SensorEntityDescription
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, mac, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        """Return the dimension in pixels."""
        tag_type = self.coordinator.tag_type(self._mac)
        if tag_type is None:
            return None
        return int(getattr(tag_type, self.entity_description.key))


class APHostSensor(OpenEPaperLinkAPEntity, SensorEntity):
    """Reports the address the Access Point is reachable at.

    Tracked because DHCP can move it; the entry itself is keyed on the MAC.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: APCoordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "ip")

    @property
    def native_value(self) -> str:
        """Return the current host."""
        return self.coordinator.host
