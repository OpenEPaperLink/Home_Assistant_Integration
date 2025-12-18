from __future__ import annotations

import logging
from functools import wraps
from typing import Final, Any, Callable

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .coordinator import Hub
from .ble import BLEConnectionError, BLETimeoutError, BLEProtocolError, BLEDeviceMetadata
from .const import DOMAIN, SIGNAL_TAG_IMAGE_UPDATE
from .imagegen import ImageGen
from .tag_types import get_tag_types_manager
from .upload import create_upload_queues, DITHER_DEFAULT, upload_to_ble_direct, upload_to_ble_block, upload_to_hub
from .util import is_ble_entry, get_hub_from_hass, rgb_to_rgb332, int_to_hex_string, \
    is_ble_device, get_mac_from_entity_id

_LOGGER: Final = logging.getLogger(__name__)



async def async_setup_services(hass: HomeAssistant) -> None:
    """
    Set up the OpenEPaperLink services.
    Args:
        hass: Home Assistant instance
    """

    # Create upload queues
    ble_upload_queue, hub_upload_queue = create_upload_queues()

    async def get_device_ids_from_label_id(label_id: str) -> list[str]:
        """Get device_ids for OpenEPaperLink devices with a specific label."""
        device_registry = dr.async_get(hass)
        devices = dr.async_entries_for_label(device_registry, label_id)

        oepl_device_ids = []
        for device in devices:
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN:
                    oepl_device_ids.append(device.id)
                    break

        return oepl_device_ids

    async def get_device_ids_from_area_id(area_id: str) -> list[str]:
        """Get device_ids for all OpenEPaperLink devices in an area."""
        device_registry = dr.async_get(hass)
        devices = dr.async_entries_for_area(device_registry, area_id)
        oepl_device_ids = []
        for device in devices:
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN:
                    oepl_device_ids.append(device.id)
                    break
        return oepl_device_ids

    async def get_entity_id_from_device_id(device_id: str) -> str:
        """Get the primary entity ID for an OpenEPaperLink device."""
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)
        if not device:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device_id": device_id},
            )
        if not device.identifiers:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_no_identifiers",
                translation_placeholders={"device_id": device_id},
            )

        domain_mac = next(iter(device.identifiers))
        if domain_mac[0] != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_oepl",
                translation_placeholders={"device_id": device_id},
            )

        identifier = domain_mac[1]
        if identifier.startswith("ble_"):
            mac_address = identifier[4:]
        else:
            mac_address = identifier

        return f"{DOMAIN}.{mac_address.lower()}"


    def _build_led_pattern(service_data: dict[str, Any]) -> str:
        """Build LED pattern hex string from service data."""
        mode = service_data.get("mode", "")
        modebyte = "1" if mode == "flash" else "0"
        brightness = service_data.get("brightness", 2)
        modebyte = hex(((brightness - 1) << 4) + int(modebyte))[2:]

        def _color_segment(color_num: int) -> str:
            default_delay = 0.0 if color_num == 3 else 0.1
            color = service_data.get(f"color{color_num}")
            flash_speed = service_data.get(f"flashSpeed{color_num}", 0.2)
            flash_count = service_data.get(f"flashCount{color_num}", 2)
            delay = service_data.get(f"delay{color_num}", default_delay)

            if not isinstance(color, (list, tuple)) or len(color) != 3:
                color = (0, 0, 0)
                flash_speed = 0
                flash_count = 0

            return (
                    rgb_to_rgb332(color)
                    + hex(int(flash_speed * 10))[2:]
                    + hex(flash_count)[2:]
                    + int_to_hex_string(int(delay * 10))
            )

        return (
                modebyte +
                _color_segment(1) +
                _color_segment(2) +
                _color_segment(3) +
                int_to_hex_string(service_data.get("repeats", 2) - 1) +
                "00"
        )


    def require_hub_online(func: Callable) -> Callable:
        """Decorator to require the AP to be online before executing a service."""
        @wraps(func)
        async def wrapper(service: ServiceCall, *args, **kwargs) -> None:
            hub = get_hub_from_hass(hass)
            if not hub.online:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ap_offline",
                )
            return await func(service, *args, hub=hub, **kwargs)
        return wrapper

    def handle_targets(func: Callable) -> Callable:
        """Decorator to handle device_id, label_id, and area_id targeting."""
        @wraps(func)
        async def wrapper(service: ServiceCall, *args, **kwargs):
            device_ids = service.data.get("device_id", [])
            label_ids = service.data.get("label_id", [])
            area_ids = service.data.get("area_id", [])

            # Normalize to lists
            if isinstance(device_ids, str):
                device_ids = [device_ids]
            if isinstance(label_ids, str):
                label_ids = [label_ids]
            if isinstance(area_ids, str):
                area_ids = [area_ids]

            # Expand labels
            for label_id in label_ids:
                expanded = await get_device_ids_from_label_id(label_id)
                device_ids.extend(expanded)

            # Expand areas
            for area_id in area_ids:
                expanded = await get_device_ids_from_area_id(area_id)
                device_ids.extend(expanded)

            # Remove duplicates while preserving order
            seen = set()
            unique_device_ids = []
            for device_id in device_ids:
                if device_id not in seen:
                    seen.add(device_id)
                    unique_device_ids.append(device_id)

            if not unique_device_ids:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_targets_specified",
                )

            # Process each device
            errors: list[tuple[str, str]] = []
            for device_id in unique_device_ids:
                try:
                    entity_id = await get_entity_id_from_device_id(device_id)
                    await func(service, entity_id, *args, **kwargs)
                except ServiceValidationError as err:
                    errors.append((device_id, str(err)))

                # Wait for all queued uploads to complete
                # This is async/await so it doesn't block the HA event loop
                try:
                    ble_errors = await ble_upload_queue.wait_for_current_batch()
                    hub_errors = await hub_upload_queue.wait_for_current_batch()
                    for ble_error in ble_errors:
                        errors.append((device_id, str(ble_error)))
                    for hub_error in hub_errors:
                        errors.append((device_id, str(hub_error)))
                except (ServiceValidationError, HomeAssistantError) as err:
                    errors.append((device_id, str(err)))

            # If ANY errors occurred across all targets, raise them
            if errors:
                errors_str = "\n".join(f"{entity}: {message}" for entity, message in errors)
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="multiple_errors",
                    translation_placeholders={"errors": errors_str},
                )
        return wrapper

    @handle_targets
    async def drawcustom_service(service: ServiceCall, entity_id: str) -> None:
        """Handle drawcustom service calls.

        Processes requests to generate and upload custom images to tags.
        The service supports:

        - Multiple target devices
        - Custom content with text, shapes, and images
        - Background color and rotation
        - Dithering options
        - "Dry run" mode for testing

        Args:
            service: Service call object with parameters and target devices

        Raises:
            HomeAssistantError: If AP is offline or image generation fails
        """
        device_errors = []

        try:
            is_ble = is_ble_device(hass, entity_id)

            # For hub devices, ensure hub is online
            hub = None
            if not is_ble:
                hub = get_hub_from_hass(hass)
                if not hub.online:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="ap_offline",
                    )

            # Generate image
            generator = ImageGen(hass)
            width, height, accent_color = await generator.get_tag_dimensions(
                entity_id, is_ble=is_ble
            )
            image_data = await generator.generate_custom_image(
                entity_id=entity_id,
                service_data=service.data,
                error_collector=device_errors,
                width=width,
                height=height,
                accent_color=accent_color,
            )

            if device_errors:
                errors_str = "\n".join(device_errors)
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_payload",
                    translation_placeholders={"errors": errors_str},
                )

            if device_errors:
                _LOGGER.warning(
                    "Completed with warnings for device %s:\n%s",
                    entity_id,
                    "\n".join(device_errors)
                )

            # Handle dry-run mode
            if service.data.get("dry-run", False):
                _LOGGER.info("Dry run completed for %s", entity_id)
                tag_mac = get_mac_from_entity_id(entity_id)
                async_dispatcher_send(
                    hass,
                    f"{SIGNAL_TAG_IMAGE_UPDATE}_{tag_mac}",
                    image_data
                )
                return

            # Upload image
            dither = int(service.data.get("dither", DITHER_DEFAULT))

            refresh_type = int(service.data.get("refresh_type", 0))

            if is_ble:
                from .util import is_bluetooth_available
                if not is_bluetooth_available(hass):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="ble_upload_bt_disabled",
                        translation_placeholders={"entity_id": entity_id},
                    )

                # Determine upload method
                mac = get_mac_from_entity_id(entity_id)

                # Find device metadata
                device_metadata = {}
                for entry in hass.config_entries.async_entries(DOMAIN):
                    runtime_data = getattr(entry, 'runtime_data', None)
                    if runtime_data is not None and is_ble_entry(runtime_data):
                        if runtime_data.mac_address.upper() == mac:
                            device_metadata = runtime_data.device_metadata
                            break

                metadata = BLEDeviceMetadata(device_metadata)
                upload_method = metadata.get_best_upload_method(len(image_data))

                if upload_method == "block":
                    await ble_upload_queue.add_to_queue(upload_to_ble_block, hass, entity_id, image_data, dither)
                else:
                    await ble_upload_queue.add_to_queue(
                        upload_to_ble_direct,
                        hass,
                        entity_id,
                        image_data,
                        upload_method == "direct_write_compressed",
                        dither,
                        refresh_type
                    )
            else:
                # Map refresh_type to AP's lut parameter
                # 0→1 (full), 1→3 (fast), 2→2 (fast no-reds), 3→0 (no-repeats)
                ap_lut_mapping = {0: 1, 1: 3, 2: 2, 3: 0}
                ap_lut = ap_lut_mapping.get(refresh_type, 1)  # Default to 1 (full) if invalid
                await hub_upload_queue.add_to_queue(
                    upload_to_hub, hub, entity_id, image_data, dither,
                    service.data.get("ttl", 60),
                    service.data.get("preload_type", 0),
                    service.data.get("preload_lut", 0),
                    ap_lut
                )

        except ServiceValidationError:
            raise  # User input errors - propagate unchanged
        except (HomeAssistantError, BLEConnectionError, BLETimeoutError, BLEProtocolError):
            raise  # Operational errors - propagate unchanged
        except Exception as err:
            # Unexpected errors - wrap as operational error
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="error_processing_device",
                translation_placeholders={"entity_id": entity_id, "error": str(err)}
            ) from err



    @require_hub_online
    @handle_targets
    async def setled_service(service: ServiceCall, entity_id: str, hub: Hub) -> None:
        pattern = _build_led_pattern(service.data)

        await hub.set_led_pattern(entity_id, pattern)

    @require_hub_online
    @handle_targets
    async def clear_pending_service(service: ServiceCall, entity_id: str, hub: Hub) -> None:
        """Clear pending updates for target devices."""
        await hub.send_tag_cmd(entity_id, "clear")

    @require_hub_online
    @handle_targets
    async def force_refresh_service(service: ServiceCall, entity_id: str, hub: Hub) -> None:
        """Force refresh target devices."""
        await hub.send_tag_cmd(entity_id, "refresh")

    @require_hub_online
    @handle_targets
    async def reboot_tag_service(service: ServiceCall,entity_id: str, hub: Hub) -> None:
        """Reboot target devices."""
        await hub.send_tag_cmd(entity_id, "reboot")

    @require_hub_online
    @handle_targets
    async def scan_channels_service(service: ServiceCall, entity_id: str, hub: Hub) -> None:
        """Trigger channel scan on target devices."""
        await hub.send_tag_cmd(entity_id, "scan")

    @require_hub_online
    async def reboot_ap_service(service: ServiceCall, hub: Hub) -> None:
        """Reboot the Access Point."""
        await hub.reboot_ap()

    async def refresh_tag_types_service(service: ServiceCall) -> None:
        """Force refresh tag types from GitHub."""
        manager = await get_tag_types_manager(hass)
        manager._last_update = None  # Force refresh by invalidating cache

        # Let exceptions propagate - ensure_types_loaded will raise HomeAssistantError if it fails
        await manager.ensure_types_loaded()

        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag type definitions from GitHub"

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refresh",
                "message": message,
                "notification_id": "oepl_tag_types_refresh",
            },
        )

    # Register all services
    hass.services.async_register(DOMAIN, "drawcustom", drawcustom_service)
    hass.services.async_register(DOMAIN, "setled", setled_service)
    hass.services.async_register(DOMAIN, "clear_pending", clear_pending_service)
    hass.services.async_register(DOMAIN, "force_refresh", force_refresh_service)
    hass.services.async_register(DOMAIN, "reboot_tag", reboot_tag_service)
    hass.services.async_register(DOMAIN, "scan_channels", scan_channels_service)
    hass.services.async_register(DOMAIN, "reboot_ap", reboot_ap_service)
    hass.services.async_register(DOMAIN, "refresh_tag_types", refresh_tag_types_service)
