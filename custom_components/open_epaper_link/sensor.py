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

SENSOR_DESCRIPTIONS: dict[str, OpenEPaperLinkSensorEntityDescription] = {
    "ip": OpenEPaperLinkSensorEntityDescription(
        key="ip",
        name="IP Address",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("ip"),
        icon="mdi:ip",
    ),
    "wifi_ssid": OpenEPaperLinkSensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("wifi_ssid"),
        icon="mdi:wifi-settings",
    ),
    "record_count": OpenEPaperLinkSensorEntityDescription(
        key="record_count",
        name="Tag count",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("record_count"),
        icon="mdi:tag-multiple",
    ),
    "db_size": OpenEPaperLinkSensorEntityDescription(
        key="db_size",
        name="Database Size",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("db_size", 0)) / 1024, 1),
        icon="mdi:database-settings",
    ),
    "little_fs_free": OpenEPaperLinkSensorEntityDescription(
        key="little_fs_free",
        name="LittleFS Free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("little_fs_free", 0)) / 1024, 1),
        icon="mdi:folder",
    ),
    "ap_state": OpenEPaperLinkSensorEntityDescription(
        key="ap_state",
        name="AP State",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("ap_state"),
        icon="mdi:access-point",
    ),
    "run_state": OpenEPaperLinkSensorEntityDescription(
        key="run_state",
        name="Run State",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("run_state"),
        icon="mdi:cog",
    ),
    "wifi_rssi": OpenEPaperLinkSensorEntityDescription(
        key="wifi_rssi",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
        icon="mdi:wifi-strength-4",
    ),
    "heap": OpenEPaperLinkSensorEntityDescription(
        key="heap",
        name="Free Heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kB",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(int(data.get("heap", 0)) / 1024, 1),
        icon="mdi:chip",
    ),
    "sys_time": OpenEPaperLinkSensorEntityDescription(
        key="sys_time",
        name="System Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: datetime.fromtimestamp(data.get("sys_time", 0),tz=timezone.utc),
        icon="mdi:clock-outline",
    ),
    "temperature": OpenEPaperLinkSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=None,
        value_fn=lambda data: data.get("temperature"),
        icon="mdi:thermometer",
    ),
    "battery_voltage": OpenEPaperLinkSensorEntityDescription(
        key="battery",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("battery_mv"),
        icon="mdi:battery",
    ),
    "battery_percentage": OpenEPaperLinkSensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
        value_fn=lambda data: _calculate_battery_percentage(data.get("battery_mv", 0)),
        icon="mdi:battery",
    ),
    "last_seen": OpenEPaperLinkSensorEntityDescription(
        key="last_seen",
        name="Last Seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("last_seen", 0),tz=timezone.utc),
        icon="mdi:history",
    ),
    "next_update": OpenEPaperLinkSensorEntityDescription(
        key="next_update",
        name="Next Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_update", 0),tz=timezone.utc),
        icon="mdi:update",
    ),
    "next_checkin" : OpenEPaperLinkSensorEntityDescription(
        key="next_checkin",
        name="Next Checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_checkin", 0),tz=timezone.utc),
        icon="mdi:clock-check",
    ),
    "lqi": OpenEPaperLinkSensorEntityDescription(
        key="lqi",
        name="Link Quality Index",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lqi"),
        icon="mdi:signal-cellular-outline",
    ),
    "rssi": OpenEPaperLinkSensorEntityDescription(
        key="rssi",
        name="RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
        icon="mdi:signal-distance-variant",
    ),
    "pending_updates": OpenEPaperLinkSensorEntityDescription(
        key="pending_updates",
        name="Pending Updates",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("pending"),
        icon="mdi:sync-circle",
    ),
    "content_mode": OpenEPaperLinkSensorEntityDescription(
        key="content_mode",
        name="Content Mode",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=None,
        value_fn=lambda data: data.get("content_mode"),
        icon="mdi:view-grid-outline",
    ),
    "wakeup_reason": OpenEPaperLinkSensorEntityDescription(
        key="wakeup_reason",
        name="Wakeup Reason",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wakeup_reason"),
        icon="mdi:power",
    ),
    "capabilities": OpenEPaperLinkSensorEntityDescription(
        key="capabilities",
        name="Capabilities",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("capabilities"),
        icon="mdi:list-box-outline",
    ),
    "update_count": OpenEPaperLinkSensorEntityDescription(
        key="update_count",
        name="Update Count",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("update_count"),
        icon="mdi:counter",
    )
}

# Define which sensors belong to AP and Tags
AP_SENSORS = ["ip", "wifi_ssid", "record_count", "db_size", "little_fs_free","ap_state","run_state", "wifi_rssi", "heap", "sys_time"]
TAG_SENSORS = ["temperature", "battery_voltage", "battery_percentage", "last_seen", "next_update",
               "next_checkin", "lqi", "rssi", "pending_updates", "content_mode", "wakeup_reason", "capabilities", "update_count"]


def _calculate_battery_percentage(voltage: int) -> int:
    """Calculate battery percentage from voltage."""
    if not voltage:
        return 0
    percentage = ((voltage / 1000) - 2.20) * 250
    return max(0, min(100, int(percentage)))


class OpenEPaperLinkSensor(SensorEntity):
    """Base class for OpenEPaperLink sensors."""

    entity_description: OpenEPaperLinkSensorEntityDescription

    def __init__(
            self,
            hub: Hub,
            description: OpenEPaperLinkSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._hub = hub

        # These will be set by child classes
        self._attr_unique_id = None
        self._attr_device_info = None

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self._get_data())

    def _get_data(self) -> dict:
        """Get the data for this sensor."""
        raise NotImplementedError


class OpenEPaperLinkAPSensor(OpenEPaperLinkSensor):
    """Sensor representing AP status values."""

    def __init__(
            self,
            hub: Hub,
            description: OpenEPaperLinkSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hub, description)
        self._attr_unique_id = f"ap_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ap")},
            name="OpenEPaperLink AP",
            manufacturer="OpenEPaperLink",
            model="ESP32",
            configuration_url=f"http://{hub.host}",
        )

    def _get_data(self) -> dict:
        """Get the AP data."""
        return self._hub.ap_status

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_ap_update",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the AP."""
        self.async_write_ha_state()


class OpenEPaperLinkTagSensor(OpenEPaperLinkSensor):
    """Sensor representing tag values."""

    def __init__(
            self,
            hub: Hub,
            tag_mac: str,
            description: OpenEPaperLinkSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hub, description)
        self._tag_mac = tag_mac
        self._attr_unique_id = f"{tag_mac}_{description.key}"
        tag_data = hub.get_tag_data(tag_mac)
        # Fix tag name retrieval
        tag_name = tag_data.get("tag_name", tag_mac)
        if not tag_name:
            tag_name = tag_mac

        self._attr_name = f"{tag_name} {description.name}"

        hw_string = tag_data.get("hw_string", "Unknown")
        firmware_version = str(tag_data.get("ver"))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tag_mac)},
            name=tag_name,
            manufacturer="OpenEPaperLink",
            model=hw_string,
            sw_version=firmware_version,
            via_device=(DOMAIN, "ap"),
        )

    def _get_data(self) -> dict:
        """Get the tag data."""
        return self._hub.get_tag_data(self._tag_mac)

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_tag_update_{self._tag_mac}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the tag."""
        self.async_write_ha_state()

class OpenEPaperLinkSensorHandler:
    """Class to handle dynamic sensor creation."""

    def __init__(
            self,
            hass: HomeAssistant,
            hub: Hub,
            async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize the sensor handler."""
        self.hass = hass
        self.hub = hub
        self.async_add_entities = async_add_entities
        self.known_tag_sensors: set[str] = set()

        # Set up initial sensors
        self._setup_ap_sensors()
        self._setup_tag_sensors()

        # Listen for new tag discoveries
        async_dispatcher_connect(
            self.hass,
            f"{DOMAIN}_tag_discovered",
            self._async_process_new_tag
        )

    def _setup_ap_sensors(self) -> None:
        """Set up AP sensors."""
        entities = [
            OpenEPaperLinkAPSensor(self.hub, SENSOR_DESCRIPTIONS[key])
            for key in AP_SENSORS
        ]
        self.async_add_entities(entities)

    def _setup_tag_sensors(self) -> None:
        """Set up sensors for all known tags."""
        entities = []
        for tag_mac in self.hub.tags:
            if tag_mac not in self.known_tag_sensors:
                entities.extend(self._create_tag_sensors(tag_mac))
                self.known_tag_sensors.add(tag_mac)

        if entities:
            self.async_add_entities(entities)

    def _create_tag_sensors(self, tag_mac: str) -> list[SensorEntity]:
        """Create sensor entities for a tag."""
        return [
            OpenEPaperLinkTagSensor(self.hub, tag_mac, SENSOR_DESCRIPTIONS[key])
            for key in TAG_SENSORS
        ]

    @callback
    async def _async_process_new_tag(self, tag_mac: str) -> None:
        """Handle discovery of a new tag."""
        if tag_mac not in self.known_tag_sensors:
            _LOGGER.debug("Creating sensors for newly discovered tag: %s", tag_mac)
            entities = self._create_tag_sensors(tag_mac)
            self.known_tag_sensors.add(tag_mac)
            self.async_add_entities(entities)


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenEPaperLink sensors."""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]

    # Create sensor handler instance
    handler = OpenEPaperLinkSensorHandler(hass, hub, async_add_entities)

    # Store handler in hass.data to prevent garbage collection
    hass.data[DOMAIN][f"{config_entry.entry_id}_sensor_handler"] = handler