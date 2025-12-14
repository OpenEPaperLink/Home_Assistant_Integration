from __future__ import annotations

PARALLEL_UPDATES = 0

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfElectricPotential, UnitOfInformation, UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
import logging

from . import Hub
from .entity import OpenEPaperLinkTagEntity, OpenEPaperLinkAPEntity, OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkConfigEntry
from .const import DOMAIN
from .util import is_ble_entry
from .tag_types import get_hw_string, get_hw_dimensions

_LOGGER: Final = logging.getLogger(__name__)


@dataclass(kw_only=True, frozen=True)
class OpenEPaperLinkSensorEntityDescription(SensorEntityDescription):
    """Class describing OpenEPaperLink sensor entities.

    Extends the standard Home Assistant sensor description with
    additional fields specific to OpenEPaperLink sensors, particularly
    the value extraction function that pulls data from the raw state.

    This class acts as a blueprint for creating sensor entities with
    consistent behavior and appearance across the integration.

    Attributes:
        key: Unique identifier for the sensor type
        name: Human-readable name for the sensor
        device_class: Device class for standardized behavior
        state_class: State class for statistics and history
        native_unit_of_measurement: Unit for the sensor value
        suggested_unit_of_measurement: Preferred unit for display
        suggested_display_precision: Number of decimal places to display
        entity_category: Category for UI organization
        entity_registry_enabled_default: Whether enabled by default
        value_fn: Function to extract the value from raw state data
        attr_fn: Optional function to extract extra attributes
        icon: Material Design Icons identifier
    """
    key: str
    name: str
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    native_unit_of_measurement: str | None = None
    suggested_unit_of_measurement: UnitOfInformation | None = None
    suggested_display_precision: int | None = None
    entity_category: EntityCategory | None = None
    entity_registry_enabled_default: bool = False
    value_fn: Callable[[dict], Any]
    attr_fn: Callable[[dict], Any] = None


AP_SENSOR_TYPES: tuple[OpenEPaperLinkSensorEntityDescription, ...] = (
    OpenEPaperLinkSensorEntityDescription(
        key="ip",
        name="IP Address",
        value_fn=lambda data: data.get("ip"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        value_fn=lambda data: data.get("wifi_ssid"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="record_count",
        name="Tag count",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data.get("record_count"),
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="db_size",
        name="Database Size",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(data.get("db_size", 0)),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="little_fs_free",
        name="LittleFS Free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(data.get("little_fs_free", 0)),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="ap_state",
        name="State",
        value_fn=lambda data: data.get("ap_state"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="run_state",
        name="Run State",
        value_fn=lambda data: data.get("run_state"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wifi_rssi",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="heap",
        name="Free Heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(data.get("heap", 0)),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="sys_time",
        name="System Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: datetime.fromtimestamp(data.get("sys_time", 0), tz=timezone.utc),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("uptime"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="low_battery_tag_count",
        name="Low Battery Tags",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("low_battery_count"),
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="timeout_tag_count",
        name="Timed out Tags",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        value_fn=lambda data: data.get("timeout_count"),
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="ps_ram_free",
        name="PSRAM Free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(data.get("ps_ram_free", 0)),
    )
)
"""Definitions for all AP-related sensor entities.

This tuple defines all the sensor entities created for the Access Point.
Each entry is an OpenEPaperLinkSensorEntityDescription that specifies
how to create and populate a sensor entity from AP data.

Sensor types include:

- Network information (IP, WiFi SSID, RSSI)
- System metrics (heap, database size, uptime)
- Tag statistics (count, low battery, timeout)
- Operational state (AP state, run state)

Each sensor uses a value_fn to extract the relevant data from
the hub's AP status dictionary.
"""
TAG_SENSOR_TYPES: tuple[OpenEPaperLinkSensorEntityDescription, ...] = (
    OpenEPaperLinkSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: data.get("temperature"),
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery_voltage",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("battery_mv"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: _calculate_battery_percentage(data.get("battery_mv", 0)),
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="last_seen",
        name="Last Seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: datetime.fromtimestamp(data.get("last_seen", 0), tz=timezone.utc),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="next_update",
        name="Next Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_update", 0), tz=timezone.utc),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="next_checkin",
        name="Next Checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: datetime.fromtimestamp(data.get("next_checkin", 0), tz=timezone.utc),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="lqi",
        name="Link Quality Index",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lqi"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="rssi",
        name="RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rssi"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="pending_updates",
        name="Pending Updates",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("pending"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="content_mode",
        name="Content Mode",
        value_fn=lambda data: data.get("content_mode"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="wakeup_reason",
        name="Wakeup Reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wakeup_reason"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="capabilities",
        name="Capabilities",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("capabilities"),
        attr_fn=lambda data: {
            "raw_value": data.get("capabilities", 0),
            "binary_value": format(data.get("capabilities", 0), '08b'),
            "capabilities": get_capabilities(data.get("capabilities", 0))
        },
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="update_count",
        name="Update Count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("update_count"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="width",
        name="Width",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("width"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="height",
        name="Height",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("height"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="runtime",
        name="Runtime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("runtime", 0),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="boot_count",
        name="Boot Count",
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("boot_count", 0),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="checkin_count",
        name="Checkin Count",
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("checkin_count", 0),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="block_requests",
        name="Block Requests",
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("block_requests", 0),
    ),

)


BLE_SENSOR_TYPES: tuple[OpenEPaperLinkSensorEntityDescription, ...] = (
    OpenEPaperLinkSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: data.get("temperature"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.get("battery_percentage"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="battery_voltage",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("battery_voltage"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="rssi",
        name="RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("rssi"),
    ),
    OpenEPaperLinkSensorEntityDescription(
        key="last_seen",
        name="Last Seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("last_seen"),
    ),
)
"""Definitions for all BLE tag-related sensor entities.

These sensors are created for BLE devices and track:
- Battery level and voltage from advertising data
- RSSI signal strength from Bluetooth
- Last seen timestamp from advertising updates
"""

"""Definitions for all tag-related sensor entities.

This tuple defines all the sensor entities created for each ESL.
Each entry is an OpenEPaperLinkSensorEntityDescription that specifies
how to create and populate a sensor entity from tag data.

Sensor types include:

- Telemetry data (temperature, battery, signal strength)
- Status information (last seen, next update, pending)
- Hardware capabilities (runtime, boot count, display size)
- Technical details (wakeup reason, capabilities flags)

Each sensor uses a value_fn to extract the relevant data from
the hub's tag data dictionary.
"""


def _calculate_battery_percentage(voltage: int) -> int:
    """Calculate battery percentage from raw voltage.

    Converts a battery voltage reading in millivolts to an estimated
    percentage based on the known discharge curve of a typical
    lithium battery used in ESL tags.

    The formula approximates:

    - 100% at around 3.0V
    - 0% at around 2.2V

    Args:
        voltage: Battery voltage in millivolts

    Returns:
        int: Battery percentage (0-100), clamped to valid range
    """
    if not voltage:
        return 0
    percentage = ((voltage / 1000) - 2.20) * 250
    return max(0, min(100, int(percentage)))


def _tag_has_battery(tag_data: dict) -> bool:
    """Check if a tag is battery-powered."""
    if not tag_data:
        return True  # Default to creating sensors when data is missing

    if tag_data.get("is_external"):
        return False

    battery_mv = tag_data.get("battery_mv")
    return battery_mv is not None and battery_mv > 0


def _remove_battery_sensors(
    hass: HomeAssistant, entry_id: str, tag_mac: str
) -> None:
    """Remove battery entities for a non-battery tag."""
    entity_registry = er.async_get(hass)
    unique_ids = {
        f"{tag_mac}_battery_percentage",
        f"{tag_mac}_battery_voltage",
    }

    for entity in er.async_entries_for_config_entry(entity_registry, entry_id):
        if entity.unique_id in unique_ids:
            _LOGGER.info("Removing battery sensor for external-power tag: %s", entity.entity_id)
            entity_registry.async_remove(entity.entity_id)


class OpenEPaperLinkTagSensor(OpenEPaperLinkTagEntity, SensorEntity):
    """Sensor class for OpenEPaperLink tag data."""
    entity_description: OpenEPaperLinkSensorEntityDescription

    def __init__(self, hub: Hub, tag_mac: str, description: OpenEPaperLinkSensorEntityDescription) -> None:
        """Initialize the tag sensor."""
        super().__init__(hub, tag_mac)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{tag_mac}_{description.key}"
        self.entity_id = f"{DOMAIN}.{tag_mac.lower()}_{description.key}"
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.available or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self._hub.get_tag_data(self._tag_mac))

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self._hub.get_tag_data(self._tag_mac))

class OpenEPaperLinkAPSensor(OpenEPaperLinkAPEntity, SensorEntity):
    """Sensor class for OpenEPaperLink AP data."""

    entity_description: OpenEPaperLinkSensorEntityDescription

    def __init__(self, hub, description: OpenEPaperLinkSensorEntityDescription) -> None:
        """Initialize the AP sensor."""
        super().__init__(hub)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{self._hub.entry.entry_id}_{description.key}"

    async def async_added_to_hass(self) -> None:
        """Register update signal handlers."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_ap_update",
                self._handle_update,
            )
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.available or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self._hub.ap_status)



class OpenEPaperLinkBLESensor(OpenEPaperLinkBLEEntity, SensorEntity):
    """BLE sensor entity for OpenEPaperLink tags."""

    _attr_entity_registry_enabled_default = True

    def __init__(
            self,
            hass: HomeAssistant,
            mac_address: str,
            name: str,
            device_metadata: dict,
            entry: OpenEPaperLinkConfigEntry,
            description: OpenEPaperLinkSensorEntityDescription,
    ) -> None:
        """Initialize the BLE sensor entity."""
        super().__init__(mac_address, name, entry)
        self._hass = hass
        self._device_metadata = device_metadata
        self._description = description
        self._sensor_data = {}
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default
        self._attr_translation_key = description.key

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"oepl_ble_{self._mac_address}_{self._description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self._description.value_fn:
            return self._description.value_fn(self._sensor_data)
        return self._sensor_data.get(self._description.key)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        return self._description.native_unit_of_measurement

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class."""
        return self._description.device_class

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return the state class."""
        return self._description.state_class

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return the entity category."""
        return self._description.entity_category


    def update_from_advertising_data(self, data: dict) -> None:
        """Update sensor state from BLE advertising data."""
        self._sensor_data = data
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Called when entity is added to hass."""
        if self._sensor_data:
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the sensor state."""
        pass


async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the OpenEPaperLink sensors.

    Creates sensor entities for both AP-based and BLE-based entries:

    1. For AP entries: AP sensors and tag sensors based on existing types
    2. For BLE entries: BLE sensor entities for battery, RSSI, last seen

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        async_add_entities: Callback to register new entities
    """
    entry_data = entry.runtime_data
    
    # Check if this is a BLE device entry
    if is_ble_entry(entry_data):
        # Set up BLE sensors with a simple callback approach
        mac_address = entry_data.mac_address
        name = entry_data.name
        device_metadata = entry_data.device_metadata
        protocol_type = entry_data.protocol_type  # Default to ATC for backward compatibility

        # Create sensors for each description
        from .ble import BLEDeviceMetadata
        metadata = BLEDeviceMetadata(device_metadata)
        sensors = []
        for description in BLE_SENSOR_TYPES:
            # Handle battery sensors based on device protocol
            if description.key in ("battery_percentage", "battery_voltage"):
                if protocol_type == "atc":
                    # ATC devices always have batteries
                    pass  # Continue to create sensor
                elif protocol_type == "oepl":
                    # OEPL devices: only create battery sensors for battery/solar power
                    if metadata.power_mode not in (1, 3):  # Not battery (1) or solar (3)
                        continue  # Skip battery sensors

            sensor = OpenEPaperLinkBLESensor(
                hass=hass,
                mac_address=mac_address,
                name=name,
                device_metadata=device_metadata,
                entry=entry,
                description=description,
            )
            sensors.append(sensor)

            # Register the sensor in the sensors registry so callback can update it
            entry_data.sensors[description.key] = sensor
        
        # Add the sensors
        async_add_entities(sensors)
        return
    
    # Traditional AP setup
    hub = entry_data  # For AP entries, entry_data is the Hub instance

    # Set up AP sensors
    ap_sensors = [OpenEPaperLinkAPSensor(hub, description) for description in AP_SENSOR_TYPES]
    async_add_entities(ap_sensors)

    @callback
    def async_add_tag_sensor(tag_mac: str) -> None:
        """Add sensors for a new tag.

        Creates sensor entities for a newly discovered tag based on the
        TAG_SENSOR_TYPES definitions. Called when a new tag is discovered
        by the integration.

        Args:
            tag_mac: MAC address of the newly discovered tag
        """
        entities = []

        tag_data = hub.get_tag_data(tag_mac)
        has_battery = _tag_has_battery(tag_data)

        for description in TAG_SENSOR_TYPES:
            if description.key in ("battery_percentage", "battery_voltage") and not has_battery:
                continue
            sensor = OpenEPaperLinkTagSensor(hub, tag_mac, description)
            entities.append(sensor)

        if not has_battery:
            _remove_battery_sensors(hass, entry.entry_id, tag_mac)

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


def get_capabilities(capabilities_value: int) -> list[str]:
    """Convert a capabilities number into a list of capabilities.

    Translates the binary capabilities flags from the tag into a
    human-readable list of capability names. Each bit in the value
    represents a different capability.

    Capabilities include:

    - SUPPORTS_COMPRESSION: Tag supports compressed image data
    - SUPPORTS_CUSTOM_LUTS: Tag supports custom display LUTs
    - HAS_EXT_POWER: Tag has external power connection
    - HAS_WAKE_BUTTON: Tag has physical wake button
    - HAS_NFC: Tag has NFC capability
    - NFC_WAKE: Tag can wake from NFC scan

    Args:
        capabilities_value: Integer with capability flags

    Returns:
        list[str]: List of capability string names
    """
    capability_map = {
        0x02: "SUPPORTS_COMPRESSION",
        0x04: "SUPPORTS_CUSTOM_LUTS",
        0x08: "ALT_LUT_SIZE",
        0x10: "HAS_EXT_POWER",
        0x20: "HAS_WAKE_BUTTON",
        0x40: "HAS_NFC",
        0x80: "NFC_WAKE"
    }

    capabilities = []
    for flag, name in capability_map.items():
        if capabilities_value & flag:
            capabilities.append(name)

    return capabilities
