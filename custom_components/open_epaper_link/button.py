PARALLEL_UPDATES = 1

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import logging

from .ble import get_protocol_by_name
from .entity import OpenEPaperLinkTagEntity, OpenEPaperLinkAPEntity, OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkConfigEntry
from .tag_types import get_tag_types_manager
from .util import is_ble_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _compare_configs(old: any, new: any, path: str = "") -> list[tuple[str, any, any]]:
    """Recursively compare two configs and return a list of changes.

    Compares two configuration structures (dicts, lists, or values) and identifies
    all fields that have changed between them. Handles nested structures by building
    dot-notation paths (e.g., "power.power_mode") and list indices (e.g., "displays[0].width").

    Args:
        old: Old configuration value (dict, list, or primitive)
        new: New configuration value (dict, list, or primitive)
        path: Current path in the configuration tree (used for recursion)

    Returns:
        List of tuples: (field_path, old_value, new_value) for each changed field
    """
    changes = []

    # Handle None cases
    if old is None and new is None:
        return changes
    if old is None:
        changes.append((path or "root", None, new))
        return changes
    if new is None:
        changes.append((path or "root", old, None))
        return changes

    # If types differ, treat as changed value
    if type(old) is not type(new):
        changes.append((path or "root", old, new))
        return changes

    # Handle dict comparison
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            new_path = f"{path}.{key}" if path else key

            if key not in old:
                # Key added
                changes.append((new_path, None, new[key]))
            elif key not in new:
                # Key removed
                changes.append((new_path, old[key], None))
            else:
                # Key exists in both, recurse
                changes.extend(_compare_configs(old[key], new[key], new_path))
        return changes

    # Handle list comparison
    if isinstance(old, list) and isinstance(new, list):
        max_len = max(len(old), len(new))
        for i in range(max_len):
            new_path = f"{path}[{i}]" if path else f"[{i}]"

            if i >= len(old):
                # Item added
                changes.append((new_path, None, new[i]))
            elif i >= len(new):
                # Item removed
                changes.append((new_path, old[i], None))
            else:
                # Item exists in both, recurse
                changes.extend(_compare_configs(old[i], new[i], new_path))
        return changes

    # Handle primitive values (str, int, float, bool, bytes)
    if old != new:
        changes.append((path or "root", old, new))

    return changes


def _format_value(value: any) -> str:
    """Format a configuration value for logging.

    Converts configuration values to human-readable strings for log output.
    Handles special cases like None, bytes, and large nested structures.

    Args:
        value: Configuration value to format

    Returns:
        Formatted string representation of the value
    """
    if value is None:
        return "None"
    if isinstance(value, bytes):
        # Show hex for bytes, truncate if too long
        hex_str = value.hex()
        return f"0x{hex_str[:16]}..." if len(hex_str) > 16 else f"0x{hex_str}"
    if isinstance(value, (dict, list)):
        # For complex structures, show type and length
        if isinstance(value, dict):
            return f"{{...}} ({len(value)} keys)"
        return f"[...] ({len(value)} items)"
    # For primitives, just convert to string
    return str(value)


async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up button entities from a config entry.

    Creates button entities based on device type:
    
    For BLE devices:
    - Set clock mode button
    - Disable clock mode button

    For AP devices and tags:
    - Clear pending updates button
    - Force refresh button
    - Reboot tag button
    - Scan channels button
    - Deep sleep button
    - Reboot AP button
    - Refresh tag types button

    Also sets up listeners for new tag discovery and blacklist updates
    to dynamically add and remove buttons as needed.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        async_add_entities: Callback to register new entities
    """
    entry_data = entry.runtime_data

    # Check if this is a BLE device
    is_ble_device = is_ble_entry(entry_data)

    if is_ble_device:
        # BLE device setup - create clock mode buttons
        mac_address = entry_data.mac_address
        name = entry_data.name
        device_metadata = entry_data.device_metadata
        protocol_type = entry_data.protocol_type  # Default to ATC for backward compatibility

        ble_buttons = []

        # Add refresh config button for OEPL devices only
        if protocol_type == "oepl":
            ble_buttons.append(
                RefreshConfigButton(mac_address, name, device_metadata, protocol_type, entry)
            )

        async_add_entities(ble_buttons)
        return

    # AP device setup (original logic)
    hub = entry_data

    # Track added tags to prevent duplicates
    added_tags = set()

    async def async_add_tag_buttons(tag_mac: str) -> None:
        """Add buttons for a newly discovered tag.

        Creates and registers button entities for a specific tag:

        - Clear pending updates button
        - Force refresh button
        - Reboot tag button
        - Scan channels button
        - Deep sleep button

        This function is called both during initial setup for existing
        tags and dynamically when new tags are discovered.

        The function includes deduplication logic to prevent creating
        multiple button sets for the same tag, and filtering to avoid
        creating buttons for blacklisted tags.

        Args:
            tag_mac: MAC address of the tag to create buttons for
        """

        # Skip if tag is blacklisted
        if tag_mac in hub.get_blacklisted_tags():
            _LOGGER.debug("Skipping button creation for blacklisted tag: %s", tag_mac)
            return

        if tag_mac in added_tags:
            return

        added_tags.add(tag_mac)
        new_buttons = [
            OpenEPaperLinkTagButton(hass, tag_mac, hub, description)
            for description in TAG_BUTTON_TYPES
        ]
        async_add_entities(new_buttons)

    # Add buttons for existing tags
    for tag_mac in hub.tags:
        await async_add_tag_buttons(tag_mac)

    # Add AP-level buttons
    async_add_entities([
        RebootAPButton(hass, hub),
        RefreshTagTypesButton(hass, hub),
    ])

    # Listen for new tag discoveries
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_tag_buttons
        )
    )

    # Listen for blacklist updates
    async def handle_blacklist_update() -> None:
        """Handle blacklist updates by removing buttons for blacklisted tags.

        When tags are added to the blacklist, this removes their
        associated button entities and devices from Home Assistant.

        This ensures that blacklisted tags don't appear in the UI
        and don't consume resources in Home Assistant.
        """
        # Get all buttons registered for this entry
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Track which devices need to be removed
        devices_to_remove = set()

        # Find and remove entities for blacklisted tags
        entities_to_remove = []
        for entity in entity_registry.entities.values():
            if entity.config_entry_id == entry.entry_id:
                # Check if this entity belongs to a blacklisted tag
                device = device_registry.async_get(entity.device_id) if entity.device_id else None
                if device:
                    for identifier in device.identifiers:
                        if identifier[0] == DOMAIN and identifier[1] in hub.get_blacklisted_tags():
                            entities_to_remove.append(entity.entity_id)
                            # Add device to removal list
                            devices_to_remove.add(device.id)
                            break

        # Remove the entities
        for entity_id in entities_to_remove:
            entity_registry.async_remove(entity_id)
            _LOGGER.debug("Removed entity %s for blacklisted tag", entity_id)

        # Remove the devices
        for device_id in devices_to_remove:
            device_registry.async_remove_device(device_id)
            _LOGGER.debug("Removed device %s for blacklisted tag", device_id)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_blacklist_update",
            handle_blacklist_update
        )
    )


@dataclass(frozen=True, kw_only=True)
class OpenEPaperLinkTagButtonDescription(ButtonEntityDescription):
    """Describes an OpenEPaperLink tag button."""
    command: str


TAG_BUTTON_TYPES: tuple[OpenEPaperLinkTagButtonDescription, ...] = (
    OpenEPaperLinkTagButtonDescription(
        key="clear_pending",
        translation_key="clear_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="clear",
        entity_registry_enabled_default=True
    ),
    OpenEPaperLinkTagButtonDescription(
        key="force_refresh",
        translation_key="force_refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="refresh",
        entity_registry_enabled_default=True
    ),
    OpenEPaperLinkTagButtonDescription(
        key="reboot_tag",
        translation_key="reboot_tag",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="reboot",
    ),
    OpenEPaperLinkTagButtonDescription(
        key="scan_channels",
        translation_key="scan_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="scan",
    ),
    OpenEPaperLinkTagButtonDescription(
        key="deep_sleep",
        translation_key="deep_sleep",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="deepsleep",
    ),
)


class OpenEPaperLinkTagButton(OpenEPaperLinkTagEntity, ButtonEntity):
    """Generic tag button entity."""

    entity_description: OpenEPaperLinkTagButtonDescription

    def __init__(self, hass: HomeAssistant, tag_mac: str, hub, description: OpenEPaperLinkTagButtonDescription) -> None:
        """Initialize the button entity."""
        super().__init__(hub, tag_mac)
        self.hass = hass
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self.entity_description = description
        self._attr_unique_id = f"{tag_mac}_{description.key}"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.send_tag_cmd(self._entity_id, self.entity_description.command)


class RebootAPButton(OpenEPaperLinkAPEntity, ButtonEntity):
    """Button to reboot the Access Point."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button entity."""
        super().__init__(hub)
        self.hass = hass
        self._attr_translation_key = "reboot_ap"
        self._attr_unique_id = f"{hub.entry.entry_id}_reboot_ap"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.reboot_ap()


class RefreshTagTypesButton(OpenEPaperLinkAPEntity, ButtonEntity):
    """Button to manually refresh tag types from GitHub."""

    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button entity."""
        super().__init__(hub)
        self._hass = hass
        self._attr_translation_key = "refresh_tag_types"
        self._attr_unique_id = f"{hub.entry.entry_id}_refresh_tag_types"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        """Handle the button press.

        Triggers a refresh of tag type definitions from GitHub
        and displays a notification with the result.

        The refresh process:

        1. Clears the cache timestamp to force a new GitHub fetch
        2. Calls the tag types manager to load the latest definitions
        3. Shows a notification with the number of tag types loaded
        """
        manager = await get_tag_types_manager(self._hass)
        # Force a refresh by clearing the last update timestamp
        manager._last_update = None
        await manager.ensure_types_loaded()
        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag types from GitHub"
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refreshed",
                "message": message,
                "notification_id": "tag_types_refresh_notification",
            },
        )


class RefreshConfigButton(OpenEPaperLinkBLEEntity, ButtonEntity):
    """
    Button to refresh OEPL device configuration.

    Creates a button entity that re-interrogates an OEPL device to fetch
    updated configuration and update the device metadata in Home Assistant.
    This is useful when the device configuration has been changed externally.
    """

    _attr_entity_registry_enabled_default = True

    def __init__(self,
                 mac_address: str,
                 name: str,
                 device_metadata: dict,
                 protocol_type: str,
                 entry: OpenEPaperLinkConfigEntry
                 ) -> None:
        """Initialize the button entity.

        Args:
            mac_address: MAC address of the BLE device
            name: Human-readable name for the device
            device_metadata: Device metadata dictionary
            protocol_type: BLE protocol type (should be "oepl")
            entry: Configuration entry for the device
        """
        super().__init__(mac_address, name, entry)

        self._device_metadata = device_metadata
        self._entry_id = entry.entry_id
        self._protocol_type = protocol_type
        self._attr_translation_key = "refresh_config"
        self._attr_unique_id = f"ble_{mac_address}_refresh_config"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Get protocol handler for service UUID
        self._protocol = get_protocol_by_name(protocol_type)
        self._service_uuid = self._protocol.service_uuid

    async def async_press(self) -> None:
        """Re-interrogate device and update configuration."""
        from .ble import BLEConnection, get_protocol_by_name
        from .ble.tlv_parser import config_to_dict, generate_model_name
        from homeassistant.helpers import device_registry as dr

        _LOGGER.info("Refreshing configuration for OEPL device %s", self._mac_address)

        try:
            # Get protocol handler
            protocol = get_protocol_by_name(self._protocol_type)
            fw_info = None

            # Connect and interrogate device
            async with BLEConnection(self.hass, self._mac_address, self._service_uuid, protocol) as conn:
                capabilities = await protocol.interrogate_device(conn)
                try:
                    fw_info = await protocol.read_firmware_version(conn)
                except Exception as fw_err:
                    _LOGGER.warning(
                        "Failed to read firmware version for %s: %s",
                        self._mac_address,
                        fw_err,
                    )

                if not capabilities:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="config_flow_invalid_config"
                    )

                # Get updated config from protocol
                config = protocol._last_config

                if not config:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="config_flow_missing_config"
                    )

                # Store complete OEPL config
                new_metadata = {
                    "oepl_config": config_to_dict(config),
                }
                if fw_info:
                    new_metadata["fw_version"] = fw_info.get("version")
                    new_metadata["fw_version_raw"] = fw_info.get("raw")
                    if fw_info.get("sha"):
                        new_metadata["fw_sha"] = fw_info["sha"]
                elif "fw_version" in self._device_metadata:
                    # Preserve the previously known firmware version if read fails
                    new_metadata["fw_version"] = self._device_metadata.get("fw_version")
                    if "fw_version_raw" in self._device_metadata:
                        new_metadata["fw_version_raw"] = self._device_metadata.get("fw_version_raw")
                    if "fw_sha" in self._device_metadata:
                        new_metadata["fw_sha"] = self._device_metadata.get("fw_sha")

                # Generate and store model name
                if config.displays:
                    model_name = generate_model_name(config.displays[0])
                    new_metadata["model_name"] = model_name
                else:
                    model_name = self._device_metadata.get('model_name', 'Unknown')
                    new_metadata["model_name"] = model_name

                # Log configuration changes
                old_config = self._device_metadata.get("oepl_config", {})
                new_config_data = new_metadata.get("oepl_config", {})

                if old_config != new_config_data:
                    changes = _compare_configs(old_config, new_config_data)

                    if changes:
                        # Build complete log message as multi-line string
                        log_lines = [f"Configuration changes for {self._mac_address}:"]

                        # Group changes by top-level section
                        sections = {}
                        for field_path, old_val, new_val in changes:
                            section = field_path.split('.')[0].split('[')[0]
                            if section not in sections:
                                sections[section] = []
                            sections[section].append((field_path, old_val, new_val))

                        # Build section change lines
                        for section in ["power", "displays", "leds", "sensors", "buses", "inputs", "system",
                                        "manufacturer"]:
                            if section in sections:
                                log_lines.append(f"  {section.title()}:")
                                for field_path, old_val, new_val in sections[section]:
                                    # Format values for readability
                                    old_str = _format_value(old_val)
                                    new_str = _format_value(new_val)
                                    log_lines.append(f"    {field_path}: {old_str} → {new_str}")

                        # Log complete message in a single statement
                        _LOGGER.info("\n".join(log_lines))
                else:
                    _LOGGER.info("No configuration changes for %s", self._mac_address)

                # Update config entry (persisted data)
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={**self._entry.data, "device_metadata": new_metadata}
                )

                # Update runtime_data so existing entities pick up new metadata
                self._entry.runtime_data.device_metadata = new_metadata
                self._device_metadata = new_metadata

                # Update device registry attributes
                device_registry = dr.async_get(self.hass)
                device = device_registry.async_get_device(
                    identifiers={(DOMAIN, f"ble_{self._mac_address}")}
                )

                if device:
                    sw_version = fw_info.get("version") if fw_info else device.sw_version
                    device_registry.async_update_device(
                        device.id,
                        hw_version=f"{capabilities.width}x{capabilities.height}",
                        model=model_name,
                        sw_version=str(sw_version) if sw_version else None,
                    )

                # Remove entities that will become invalid with the new config
                from . import async_remove_invalid_ble_entities
                removed = await async_remove_invalid_ble_entities(self.hass, self._entry, new_metadata)
                if removed:
                    _LOGGER.info("Removed invalid entities: %s", removed)

                # Reload integration to re-create entities based on the new config
                _LOGGER.info("Reloading integration to apply config changes for %s", self._mac_address)
                await self.hass.config_entries.async_reload(self._entry_id)

                _LOGGER.info("Successfully refreshed configuration for %s", self._mac_address)

        except Exception as e:
            _LOGGER.error("Failed to refresh configuration for %s: %s", self._mac_address, e)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_config_failed",
                translation_placeholders={"error": str(e)},
            ) from e
