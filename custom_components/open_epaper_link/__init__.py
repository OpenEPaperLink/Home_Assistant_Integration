import asyncio
import logging
import os
from typing import Final

from homeassistant.helpers import issue_registry as ir
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er, device_registry as dr, storage
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.typing import ConfigType
from .ble import BLEDeviceMetadata
from .const import DOMAIN
from .coordinator import Hub
from .runtime_data import OpenEPaperLinkConfigEntry, OpenEPaperLinkBLERuntimeData
from .services import async_setup_services
from .tag_types import get_tag_types_manager
from .util import is_ble_entry

_LOGGER: Final = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
]

# BLE devices use a subset of platforms
BLE_PLATFORMS = [
    Platform.SENSOR,  # Battery, RSSI, last seen
    Platform.LIGHT,  # LED control
    Platform.BUTTON,  # Clock mode controls
    Platform.IMAGE, # Display content (captured from drawcustom)
    Platform.UPDATE
]


async def async_migrate_camera_entities(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Migrate old camera entities to image entities.

          Finds and removes camera entities that match our unique ID pattern,
          returns a list of removed entity IDs for notification.

          Returns:
              list[str]: List of removed camera entity IDs
    """
    entity_registry = er.async_get(hass)
    removed_entities = []

    # Find camera entities with OEPL domain and content in unique_id
    camera_entities = []
    for entity in entity_registry.entities.values():
        if entity.platform == DOMAIN and entity.domain == "camera" and entity.unique_id.endswith("_content"):
            camera_entities.append(entity)

    for entity in camera_entities:
        _LOGGER.info("Removing old camera entity: %s", entity.entity_id)
        entity_registry.async_remove(entity.entity_id)
        removed_entities.append(entity.entity_id)

    return removed_entities


async def async_remove_clock_mode_buttons(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Remove deprecated clock mode button entities.

    Clock mode was a tech demo feature that is no longer supported.
    This removes the old button entities from the entity registry.

    Returns:
        list[str]: List of removed button entity IDs
    """
    entity_registry = er.async_get(hass)
    removed_entities = []

    # Find clock mode button entities for this config entry
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.unique_id and ("_set_clock_mode" in entity.unique_id or "_disable_clock_mode" in entity.unique_id):
            _LOGGER.info("Removing deprecated clock mode button: %s", entity.entity_id)
            entity_registry.async_remove(entity.entity_id)
            removed_entities.append(entity.entity_id)

    return removed_entities


async def async_remove_invalid_ble_entities(
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_metadata: dict
) -> list[str]:
    """Remove BLE entities that are invalid for current device config.

    Checks device configuration and removes entities that shouldn't exist based on
    current hardware/firmware capabilities:
    - Battery sensors when power_mode == 2 (USB powered)
    - Future: LED entities when LED config missing
    - Future: Sensor entities based on sensor config

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        device_metadata: Current device metadata with OEPL config

    Returns:
        list[str]: List of removed entity IDs
    """
    entity_registry = er.async_get(hass)
    removed_entities = []
    mac_address = entry.data.get("mac_address", "")

    # Check power mode - remove battery sensors if not battery/solar powered
    from .ble import BLEDeviceMetadata
    metadata = BLEDeviceMetadata(device_metadata)
    if metadata.power_mode not in (1, 3):  # Not battery (1) or solar (3)
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if entity.unique_id and (
                    f"oepl_ble_{mac_address}_battery_percentage" in entity.unique_id or
                    f"oepl_ble_{mac_address}_battery_voltage" in entity.unique_id
            ):
                _LOGGER.info("Removing battery sensor (power_mode=%s): %s", metadata.power_mode, entity.entity_id)
                entity_registry.async_remove(entity.entity_id)
                removed_entities.append(entity.entity_id)

    # Future: Check LED config presence and remove LED entity if not present
    # Future: Check sensor configs and remove/add sensor entities accordingly

    return removed_entities


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """
    Migrate old config entries to new schema version.

    Version 2 -> 3: Add device type and protocol type fields to BLE entries and fix boolean rotate buffer.

    Version 3 -> 4: Fix color support.

    Returns:
        bool: True if migration was successful, False otherwise.
    """
    _LOGGER.debug(
        "Migrating config entry from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )
    if config_entry.version == 2:
        new_data = {**config_entry.data}

        # Check if this is a BLE entry
        if "mac_address" in config_entry.data:
            if "device_type" not in config_entry.data:
                new_data["device_type"] = "ble"
                _LOGGER.info(
                    "Adding device_type='ble' to BLE entry %s",
                    new_data.get("name", new_data.get("mac_address"))
                )

            if "protocol_type" not in config_entry.data:
                new_data["protocol_type"] = "atc"
                _LOGGER.info(
                    "Adding protocol_type='atc' to BLE entry %s",
                    new_data.get("name", new_data.get("mac_address"))
                )

            if "device_metadata" in new_data:
                device_metadata = new_data["device_metadata"]

                if "oepl_config" not in device_metadata and "rotatebuffer" in device_metadata:
                    rotatebuffer_value = device_metadata["rotatebuffer"]

                    if isinstance(rotatebuffer_value, bool):
                        new_metadata = {**device_metadata, "rotatebuffer": 1}
                        new_data["device_metadata"] = new_metadata

                        _LOGGER.info(
                            "Converting rotatebuffer from %s (bool) to %s (int) for BLE entry %s",
                            rotatebuffer_value,
                            new_metadata["rotatebuffer"],
                            new_data.get("name", new_data.get("mac_address"))
                        )

        # Update config entry with migrated data and new version
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=3,
            minor_version=0
        )
        _LOGGER.info("Successfully migrated config entry to version 3")

    if config_entry.version == 3:
        new_data = {**config_entry.data}

        # Only migrate BLE entries
        if "mac_address" in config_entry.data:
            device_metadata = dict(new_data.get("device_metadata", {}))

            # OEPL: No migration needed - color scheme is already in oepl_config.displays[0]
            # ATC: Need to add color_scheme at root level

            if "oepl_config" not in device_metadata and "color_scheme" not in device_metadata:
                hw_type = device_metadata.get("hw_type", 0)
                tag_types_manager = await get_tag_types_manager(hass)

                if tag_types_manager.is_in_hw_map(hw_type):
                    tag_type = await tag_types_manager.get_tag_info(hw_type)
                    color_table = tag_type.color_table

                    _LOGGER.info(
                        "Migrating color support for BLE entry %s based on hw_type=%s with colors: %s",
                        new_data.get("name", new_data.get("mac_address")),
                        hw_type,
                        color_table
                    )

                    if 'yellow' in color_table and 'red' in color_table:
                        color_scheme = 3  # BWRY
                    elif 'yellow' in color_table:
                        color_scheme = 2  # BWY
                    elif 'red' in color_table:
                        color_scheme = 1  # BWR
                    else:
                        color_scheme = 0  # BW

                    _LOGGER.info(
                        "Determined color_scheme=%s for BLE entry %s",
                        color_scheme,
                        new_data.get("name", new_data.get("mac_address"))
                    )
                else:
                    # Fallback from old color_support string
                    cs = device_metadata.get("color_support", "mono")
                    color_scheme = {"red": 1, "yellow": 2, "bwry": 3}.get(cs, 0)
                    _LOGGER.info(
                        "Fallback color_scheme=%s for BLE entry %s from color_support='%s'",
                        color_scheme,
                        new_data.get("name", new_data.get("mac_address")),
                        cs
                    )

                device_metadata["color_scheme"] = color_scheme
                new_data["device_metadata"] = device_metadata

                _LOGGER.info(
                    "Adding color_scheme=%s to BLE entry %s",
                    color_scheme,
                    new_data.get("name", new_data.get("mac_address"))
                )

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=4
        )
        _LOGGER.info("Successfully migrated config entry to version 4")

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the OpenEPaperLink integration."""

    # Services should be set up unconditionally
    await async_setup_services(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry) -> bool:
    """Set up OpenEPaperLink integration from a config entry.

    This is the main entry point for integration initialization, which handles both:
    - AP-based entries (traditional WebSocket-based integration)
    - BLE-based entries (direct Bluetooth communication)

    Args:
        hass: Home Assistant instance
        entry: Configuration Entry object with connection details

    Returns:
        bool: True if setup was successful, False otherwise
    """
    # Detect BLE vs AP entry type
    is_ble_device = entry.data.get("device_type") == "ble"

    if is_ble_device:
        # BLE device setup using simple callback approach
        _LOGGER.debug("Setting up BLE device entry: %s", entry.data.get("name"))

        from homeassistant.components import bluetooth
        from .ble import get_protocol_by_name
        from datetime import datetime, timezone

        mac_address = entry.data.get("mac_address")
        name = entry.data.get("name")
        device_metadata = entry.data.get("device_metadata", {})
        protocol_type = entry.data.get("protocol_type", "atc")  # Default to ATC for backward compatibility

        # Get protocol handler for this device
        protocol = get_protocol_by_name(protocol_type)
        _LOGGER.debug("Setting up BLE device with protocol: %s (manufacturer ID: 0x%04X)",
                      protocol_type, protocol.manufacturer_id)

        # Store BLE device config in runtime_data for entity access
        ble_data = OpenEPaperLinkBLERuntimeData(
            mac_address=mac_address,
            name=name,
            device_metadata=device_metadata,
            protocol_type=protocol_type,
            sensors={},
        )
        entry.runtime_data = ble_data

        # Lightweight presence check - only checks cached advertisement data
        if not bluetooth.async_address_present(hass, mac_address, connectable=False):
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="ble_device_not_detected",
                translation_placeholders={"name": name, "mac_address": mac_address},
            )

        if entry.data.get("send_welcome_image", False):
            new_data = dict(entry.data)
            new_data.pop("send_welcome_image", None)
            hass.config_entries.async_update_entry(entry, data=new_data)

            hass.async_create_task(
                    _send_welcome_image(
                        hass,
                        entry.entry_id,
                        name,
                    )
                )

        def _ble_device_found(
                service_info: bluetooth.BluetoothServiceInfoBleak,
                change: bluetooth.BluetoothChange,
        ) -> None:
            """Handle BLE advertising data updates.

            Uses protocol-specific parsing based on the device firmware type.
            """
            # Only process the specific device
            if service_info.address != mac_address:
                return

            # Parse manufacturer data using protocol-specific parser
            manufacturer_data = service_info.manufacturer_data.get(protocol.manufacturer_id)
            if not manufacturer_data:
                _LOGGER.debug(
                    "No manufacturer data for 0x%04X on %s (available: %s)",
                    protocol.manufacturer_id,
                    mac_address,
                    service_info.manufacturer_data.keys()
                )
                return

            try:
                advertising_data = protocol.parse_advertising_data(manufacturer_data)
                if not advertising_data:
                    _LOGGER.debug("parse_advertising_data returned None for %s", mac_address)
                    return
            except Exception as err:
                _LOGGER.debug("Failed to parse advertising data for %s: %s", mac_address, err, exc_info=True)
                return

            # Dynamically update device attributes (skip OEPL fw to avoid incorrect value)
            if advertising_data.fw_version and protocol_type != "oepl":
                device_registry = dr.async_get(hass)
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, f"ble_{mac_address}")}
                )
                new_fw_string = str(advertising_data.fw_version)
                if device_entry and device_entry.sw_version != new_fw_string:
                    _LOGGER.debug(
                        "Device %s firmware updated from %s to %s",
                        mac_address,
                        device_entry.sw_version,
                        new_fw_string,
                    )
                    device_registry.async_update_device(
                        device_entry.id,
                        sw_version=new_fw_string
                    )

            # Build sensor data
            sensor_data = {
                "battery_percentage": advertising_data.battery_pct,
                "battery_voltage": advertising_data.battery_mv if advertising_data.battery_mv > 0 else None,
                "rssi": service_info.rssi,
                "last_seen": datetime.now(timezone.utc),
                "temperature": advertising_data.temperature,
            }

            # Update all registered sensors
            for sensor in ble_data.sensors.values():
                sensor.update_from_advertising_data(sensor_data)

        # Remove deprecated clock mode button entities
        removed_clock_buttons = await async_remove_clock_mode_buttons(hass, entry)
        if removed_clock_buttons:
            _LOGGER.info("Removed deprecated clock mode buttons: %s", removed_clock_buttons)

        # Remove invalid entities based on the current device config
        removed_invalid = await async_remove_invalid_ble_entities(hass, entry, device_metadata)
        if removed_invalid:
            _LOGGER.info("Removed invalid BLE entities: %s", removed_invalid)

        # Set up BLE-specific platforms FIRST (before callback registration)
        # This ensures sensor entities exist before any advertising callbacks fire
        await hass.config_entries.async_forward_entry_setups(entry, BLE_PLATFORMS)

        # Register BLE advertising listener with protocol-specific manufacturer ID
        # This must happen AFTER platforms are set up so sensors can receive updates
        unregister_callback = bluetooth.async_register_callback(
            hass,
            _ble_device_found,
            {"manufacturer_id": protocol.manufacturer_id},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )

        entry.async_on_unload(unregister_callback)

    else:
        # Traditional AP setup
        _LOGGER.debug("Setting up AP entry: %s", entry.data.get(CONF_HOST, "unknown"))

        hub = Hub(hass, entry)

        # Do basic setup without WebSocket connection
        # Raises ConfigEntryNotReady if AP is unreachable
        await hub.async_setup_initial()

        entry.runtime_data = hub

        removed_entities = await async_migrate_camera_entities(hass, entry)
        if removed_entities:
            # Inform users via repairs that camera entities were migrated and dashboards need updates
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"camera_migration_{entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="camera_migration_needed",
                translation_placeholders={
                    "count": str(len(removed_entities)),
                    "entities": ", ".join(removed_entities),
                },
            )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        async def start_websocket(_):
            """Start WebSocket connection after HA is fully started."""
            await hub.async_start_websocket()

        if hass.is_running:
            # If HA is already running, start WebSocket immediately
            await hub.async_start_websocket()
        else:
            # Otherwise wait for the started event
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, start_websocket)


    # Listen for changes to options
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry) -> None:
    """Handle updates to integration options.

    Called when the user updates integration options through the UI.
    Only applies to AP-based entries (BLE devices don't have configurable options).

    Args:
        hass: Home Assistant instance
        entry: Updated configuration entry
    """
    entry_data = entry.runtime_data

    # Only AP entries have hub with reload_config method
    if is_ble_entry(entry_data):
        # BLE devices don't have configurable options yet
        return

    # Traditional AP entry
    hub = entry_data
    await hub.async_reload_config()


async def async_unload_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry) -> bool:
    """Unload the integration when removed or restarted.

    Handles both BLE and AP entries with appropriate cleanup.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry being unloaded

    Returns:
        bool: True if unload was successful, False otherwise
    """
    entry_data = entry.runtime_data

    # Determine if BLE or AP entry
    is_ble_device = is_ble_entry(entry_data)

    if is_ble_device:
        # BLE device cleanup
        unload_ok = await hass.config_entries.async_unload_platforms(entry, BLE_PLATFORMS)
    else:
        # AP entry cleanup
        hub = entry_data
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

        if unload_ok:
            await hub.shutdown()

    return unload_ok

async def async_remove_config_entry_device(
        hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow manual removal of stale BLE devices."""
    mac_address = None
    for domain, ident in device_entry.identifiers:
        if domain == DOMAIN and ident.startswith("ble_"):
            mac_address = ident[4:]
            break

    if not mac_address:
        return True  # Not a BLE device; let HA delete it.

    # Lean option: always allow removal so users can clean up.
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle complete removal of integration.

    Called when the integration is completely removed from Home Assistant
    (not during restarts). Performs cleanup of persistent storage files.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry being removed
    """
    # Only remove shared storage files if this is the last config entry
    remaining_entries = [
        config_entry for config_entry in hass.config_entries.async_entries(DOMAIN)
        if config_entry.entry_id != entry.entry_id
    ]

    if not remaining_entries:
        # This was the last entry, safe to remove shared storage
        await async_remove_storage_files(hass)


async def async_remove_storage_files(hass: HomeAssistant) -> None:
    """Remove persistent storage files when removing integration.

    Cleans up files created by the integration:

    1. Tag types file (open_epaper_link_tagtypes.json)
    2. Tag storage file (.storage/open_epaper_link_tags)
    3. Image directory (www/open_epaper_link)

    This prevents orphaned files when the integration is removed
    and ensures a clean reinstallation if needed.

    Args:
        hass: Home Assistant instance
    """
    from .tag_types import reset_tag_types_manager

    storage_dir = hass.config.path(".storage")

    # Remove tag types file
    tag_types_file = hass.config.path("open_epaper_link_tagtypes.json")
    if await hass.async_add_executor_job(os.path.exists, tag_types_file):
        try:
            await hass.async_add_executor_job(os.remove, tag_types_file)
            _LOGGER.debug("Removed tag types file")
        except OSError as err:
            _LOGGER.error("Error removing tag types file: %s", err)

    # Remove tag types storage entry
    try:
        await storage.async_remove_store(hass, "open_epaper_link_tagtypes")
        _LOGGER.debug("Removed tag types storage file")
    except Exception as err:
        _LOGGER.error("Error removing tag types storage file: %s", err)

    # Remove tag storage file
    tags_file = os.path.join(storage_dir, f"{DOMAIN}_tags")
    if await hass.async_add_executor_job(os.path.exists, tags_file):
        try:
            await hass.async_add_executor_job(os.remove, tags_file)
            _LOGGER.debug("Removed tag storage file")
        except OSError as err:
            _LOGGER.error("Error removing tag storage file: %s", err)

    # Remove image directory
    image_dir = hass.config.path("www/open_epaper_link")
    if await hass.async_add_executor_job(os.path.exists, image_dir):
        try:
            # Get file list in executor
            files = await hass.async_add_executor_job(os.listdir, image_dir)

            # Remove each file in executor
            for file in files:
                file_path = os.path.join(image_dir, file)
                await hass.async_add_executor_job(os.remove, file_path)

            # Remove directory in executor
            await hass.async_add_executor_job(os.rmdir, image_dir)
            _LOGGER.debug("Removed image directory")
        except OSError as err:
            _LOGGER.error("Error removing image directory: %s", err)

    # Reset the tag types manager singleton since its storage was deleted
    reset_tag_types_manager()
    _LOGGER.debug("Reset tag types manager singleton")



async def _send_welcome_image(
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
) -> None:
    try:
        for _ in range(10):
            if hass.services.has_service(DOMAIN, "drawcustom"):
                break
            await asyncio.sleep(0.5)
        else:
            _LOGGER.debug("Welcome image: drawcustom service not available")
            return
        device_registry = dr.async_get(hass)
        devices = [
            device
            for device in device_registry.devices.values()
            if entry_id in device.config_entries
        ]
        for _ in range(20):
            devices = dr.async_entries_for_config_entry(device_registry, entry_id)
            if devices:
                device_id = devices[0].id
                break
            await asyncio.sleep(0.5)

        if not device_id:
            _LOGGER.debug("Welcome image: No devices found for entry %s", entry_id)
            return

        device_id = devices[0].id

        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return

        device_metadata = entry.data.get("device_metadata", {})

        metadata = BLEDeviceMetadata(device_metadata)

        width = metadata.width
        height = metadata.height
        color_scheme = metadata.color_scheme

        colors = list(color_scheme.palette.colors.keys())

        title_y_pct = 10
        title_size = max(12, int(height * 0.08))
        logo_y_pct = 40
        logo_size = max(48, int(height * 0.25))
        color_box_y_pct = 80
        color_box_size = max(20, int(height * 0.12))

        payload = [
            {
                "type": "text",
                "value": f"Connected to HA {HA_VERSION}",
                "x": "50%",
                "y": f"{title_y_pct}%",
                "size": title_size,
                "color": "black",
                "anchor": "mt",
                "font": "ppb.ttf",
            },
            # Home Assistant logo (left side)
            {
                "type": "icon",
                "value": "mdi:home-assistant",
                "x": "35%",
                "y": f"{logo_y_pct}%",
                "size": logo_size,
                "color": "black",
                "anchor": "mm",
            },
            # Bluetooth icon (center)
            {
                "type": "icon",
                "value": "mdi:bluetooth-connect",
                "x": "50%",  # Center
                "y": f"{logo_y_pct}%",
                "size": int(logo_size * 0.5),
                "color": "black",
                "anchor": "mm",
            },
            # OEPL logo (right side)
            {
                "type": "dlimg",
                "url": "https://openepaperlink.org/logo_black.png",
                "x": int(width * 0.65 - logo_size // 2),
                "y": int(height * logo_y_pct / 100 - logo_size // 2),
                "xsize": logo_size,
                "ysize": logo_size,
                "resize_method": "contain",
            },
        ]

        num_colors = len(colors)
        spacing = 5
        total_width = num_colors * color_box_size + (num_colors - 1) * spacing
        start_x = (width - total_width) // 2
        box_y = int(height * color_box_y_pct / 100)

        for i, color in enumerate(colors):
            box_x = start_x + i * (color_box_size + spacing)
            payload.append({
                "type": "rectangle",
                "x_start": box_x,
                "y_start": box_y,
                "x_end": box_x + color_box_size,
                "y_end": box_y + color_box_size,
                "fill": color,
                "outline": "black",
                "width": 1,
            })

        _LOGGER.debug("Sending welcome image to %s", device_name)
        await hass.services.async_call(
            DOMAIN,
            "drawcustom",
            {
                "device_id": device_id,
                "payload": payload,
                "background": "white",
                "rotate": 0,
                "dither": 0,
                "ttl": 60,
            },
            blocking=False,
        )

    except Exception as err:
        _LOGGER.debug("Welcome image failed: %s", err, exc_info=True)
