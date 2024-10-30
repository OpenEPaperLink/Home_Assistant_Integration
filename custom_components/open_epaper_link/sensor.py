"""Sensor implementation for OpenEPaperLink integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

import logging

from .tag_types import get_hw_string

_LOGGER: Final = logging.getLogger(__name__)

from .const import DOMAIN
from .hub import Hub

@dataclass( kw_only=True)
class OpenEPaperLinkSensorEntityDescription(SensorEntityDescription):
    """Class describing OpenEPaperLink sensor entities."""
    key: str
    name: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    native_unit_of_measurement : str | None
    entity_category: EntityCategory | None
    value_fn: Callable[[dict], Any]
    icon: str

AP_SENSOR_TYPES: tuple[OpenEPaperLinkSensorEntityDescription, ...] = (
    OpenEPaperLinkSensorEntityDescription(
        key="ip",
        name="IP Address",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("ip"),
        icon="mdi:ip",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("wifi_ssid"),
        icon="mdi:wifi-settings",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="record_count",
        name="Tag count",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("record_count"),
        icon="mdi:tag-multiple",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="db_size",
        name="Database Size",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("db_size", 0)) / 1024, 1),
        icon="mdi:database-settings",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="little_fs_free",
        name="LittleFS Free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("little_fs_free", 0)) / 1024, 1),
        icon="mdi:folder",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="ap_state",
        name="AP State",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("ap_state"),
        icon="mdi:access-point",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="run_state",
        name="Run State",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("run_state"),
        icon="mdi:cog",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wifi_rssi",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
        icon="mdi:wifi-strength-4",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="heap",
        name="Free Heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("heap", 0)) / 1024, 1),
        icon="mdi:chip",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="sys_time",
        name="System Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: datetime.fromtimestamp(data.get("sys_time", 0),tz=timezone.utc),
        icon="mdi:clock-outline",
    )
)
TAG_SENSOR_TYPES: tuple[OpenEPaperLinkSensorEntityDescription, ...] = (
    OpenEPaperLinkSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=None,
        value_fn=lambda data: data.get("temperature"),
        icon="mdi:thermometer",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("battery_mv"),
        icon="mdi:battery",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
        value_fn=lambda data: _calculate_battery_percentage(data.get("battery_mv", 0)),
        icon="mdi:battery",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="last_seen",
        name="Last Seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("last_seen", 0),tz=timezone.utc),
        icon="mdi:history",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="next_update",
        name="Next Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_update", 0),tz=timezone.utc),
        icon="mdi:update",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="next_checkin",
        name="Next Checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_checkin", 0),tz=timezone.utc),
        icon="mdi:clock-check",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="lqi",
        name="Link Quality Index",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lqi"),
        icon="mdi:signal-cellular-outline",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="rssi",
        name="RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
        icon="mdi:signal-distance-variant",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="pending_updates",
        name="Pending Updates",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("pending"),
        icon="mdi:sync-circle",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="content_mode",
        name="Content Mode",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("content_mode"),
        icon="mdi:view-grid-outline",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wakeup_reason",
        name="Wakeup Reason",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wakeup_reason"),
        icon="mdi:power",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="capabilities",
        name="Capabilities",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("capabilities"),
        icon="mdi:list-box-outline",
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="update_count",
        name="Update Count",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("update_count"),
        icon="mdi:counter",
    )
)

def _calculate_battery_percentage(voltage: int) -> int:
    """Calculate battery percentage from voltage."""
    if not voltage:
        return 0
    percentage = ((voltage / 1000) - 2.20) * 250
    return max(0, min(100, int(percentage)))


class OpenEPaperLinkBaseSensor(SensorEntity):
    """Base class for all OpenEPaperLink sensors."""

    entity_description: OpenEPaperLinkSensorEntityDescription

    def __init__(self, hub, description: OpenEPaperLinkSensorEntityDescription) -> None:
        """Initialize the sensor."""
        self._hub = hub
        self.entity_description = description

class OpenEPaperLinkTagSensor(OpenEPaperLinkBaseSensor):
    def __init__(self, hub, tag_mac: str, description: OpenEPaperLinkSensorEntityDescription) -> None:
        super().__init__(hub, description)
        self._tag_mac = tag_mac

        name_base = self._hub.get_tag_data(tag_mac).get("tag_name", tag_mac)
        self._attr_name = f"{name_base} {description.name}"

        # Set unique ID without domain
        self._attr_unique_id = f"{tag_mac}_{description.key}"

        # Set entity_id with the sensor type included
        self.entity_id = f"{DOMAIN}.{tag_mac.lower()}_{description.key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._tag_mac)},
            name=name_base,
            manufacturer="OpenEPaperLink",
            model=get_hw_string(self._hub.get_tag_data(tag_mac).get("hw_type", 0)),
            via_device=(DOMAIN, "ap"),
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._tag_mac in self._hub.tags

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.available or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self._hub.get_tag_data(self._tag_mac))

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to register update signal handler."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_tag_update_{self._tag_mac}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

class OpenEPaperLinkAPSensor(OpenEPaperLinkBaseSensor):
    """Sensor class for OpenEPaperLink AP."""

    def __init__(self, hub, description: OpenEPaperLinkSensorEntityDescription) -> None:
        """Initialize the AP sensor."""
        super().__init__(hub, description)

        # Set name and unique_id
        self._attr_name = f"AP {description.name}"
        self._attr_unique_id = f"{self._hub.entry.entry_id}_{description.key}"

        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ap")},
            name="OpenEPaperLink AP",
            model="esp32",
            manufacturer="OpenEPaperLink",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._hub.online

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.available or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self._hub.ap_status)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to register update signal handler."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_ap_update",
                self._handle_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connection_status",
                self._handle_connection_status,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @callback
    def _handle_connection_status(self, is_online: bool) -> None:
        """Handle connection status updates."""
        self.async_write_ha_state()

# class OpenEPaperLinkSensorHandler:
#     """Class to handle dynamic sensor creation."""
#
#     def __init__(
#             self,
#             hass: HomeAssistant,
#             hub: Hub,
#             async_add_entities: AddEntitiesCallback,
#     ) -> None:
#         """Initialize the sensor handler."""
#         self.hass = hass
#         self.hub = hub
#         self.async_add_entities = async_add_entities
#         self.known_tag_sensors: set[str] = set()
#
#         # Set up initial sensors
#         self._setup_ap_sensors()
#         self._setup_tag_sensors()
#
#         # Listen for new tag discoveries
#         async_dispatcher_connect(
#             self.hass,
#             f"{DOMAIN}_tag_discovered",
#             self._async_process_new_tag
#         )
#
#     def _setup_ap_sensors(self) -> None:
#         """Set up AP sensors."""
#         entities = [
#             OpenEPaperLinkAPSensor(self.hub, SENSOR_DESCRIPTIONS[key])
#             for key in AP_SENSORS
#         ]
#         self.async_add_entities(entities)
#
#     def _setup_tag_sensors(self) -> None:
#         """Set up sensors for all known tags."""
#         entities = []
#         for tag_mac in self.hub.tags:
#             if tag_mac not in self.known_tag_sensors:
#                 entities.extend(self._create_tag_sensors(tag_mac))
#                 self.known_tag_sensors.add(tag_mac)
#
#         if entities:
#             self.async_add_entities(entities)
#
#     def _create_tag_sensors(self, tag_mac: str) -> list[SensorEntity]:
#         """Create sensor entities for a tag."""
#         return [
#             OpenEPaperLinkTagSensor(self.hub, tag_mac, SENSOR_DESCRIPTIONS[key])
#             for key in TAG_SENSORS
#         ]
#
#     @callback
#     async def _async_process_new_tag(self, tag_mac: str) -> None:
#         """Handle discovery of a new tag."""
#         if tag_mac not in self.known_tag_sensors:
#             _LOGGER.debug("Creating sensors for newly discovered tag: %s", tag_mac)
#             entities = self._create_tag_sensors(tag_mac)
#             self.known_tag_sensors.add(tag_mac)
#             self.async_add_entities(entities)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the OpenEPaperLink sensors."""
    hub = hass.data[DOMAIN][entry.entry_id]

    # Set up AP sensors
    ap_sensors = [OpenEPaperLinkAPSensor(hub, description) for description in AP_SENSOR_TYPES]
    async_add_entities(ap_sensors)

    @callback
    def async_add_tag_sensor(tag_mac: str) -> None:
        """Add sensors for a new tag."""
        entities = []

        for description in TAG_SENSOR_TYPES:
            sensor = OpenEPaperLinkTagSensor(hub, tag_mac, description)
            entities.append(sensor)

        async_add_entities(entities)

    # Set up sensors for existing tags
    for tag_mac in hub.tags:
        async_add_tag_sensor(tag_mac)

    # Register callback for new tag discovery
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_tag_sensor
        )
    )