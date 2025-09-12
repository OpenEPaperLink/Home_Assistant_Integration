from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Final

import async_timeout
import requests

from requests_toolbelt import MultipartEncoder

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, SIGNAL_TAG_IMAGE_UPDATE
from .imagegen import ImageGen
from .tag_types import get_tag_types_manager
from .util import send_tag_cmd, reboot_ap, is_ble_entry, get_hub_from_hass
from .ble_utils import upload_image as ble_upload_image, DeviceMetadata

_LOGGER: Final = logging.getLogger(__name__)

DITHER_DISABLED = 0
DITHER_FLOYD_STEINBERG = 1
DITHER_ORDERED = 2
DITHER_DEFAULT = DITHER_ORDERED

MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds


def rgb_to_rgb332(rgb):
    """Convert RGB values to RGB332 format.

    Converts a standard RGB color tuple (0-255 for each component)
    to the 8-bit RGB332 format used by OpenEPaperLink for LED patterns.

    The conversion uses:

    - 3 bits for red (0-7)
    - 3 bits for green (0-7)
    - 2 bits for blue (0-3)

    Args:
        rgb: Tuple of (r, g, b) values, each 0-255

    Returns:
        str: Hexadecimal string representation of the RGB332 value
    """
    r, g, b = [max(0, min(255, x)) for x in rgb]
    r = (r // 32) & 0b111
    g = (g // 32) & 0b111
    b = (b // 64) & 0b11
    rgb332 = (r << 5) | (g << 2) | b
    return str(hex(rgb332)[2:].zfill(2))


def int_to_hex_string(number: int) -> str:
    """Convert integer to two-digit hex string.

    Ensures the resulting hex string is always two digits,
    padding with a leading zero if needed.

    Args:
        number: Integer value to convert

    Returns:
        str: Two-digit hexadecimal string
    """
    hex_string = hex(number)[2:]
    return '0' + hex_string if len(hex_string) == 1 else hex_string


async def get_device_ids_from_label_id(hass: HomeAssistant, label_id: str) -> list[str]:
    """Get the device_id for a label_id.

    Resolve a Label_ID to one or more device_ids.

    Args:
        hass: Home Assistant instance
        label_id: Home Assistant label id

    Returns:
        list: Device IDs
    """
    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_label(device_registry, label_id)

    device_ids = []
    for device in devices:
        device_ids.append(device.id)

    return device_ids

async def get_entity_id_from_device_id(hass: HomeAssistant, device_id: str) -> str:
    """Get the primary entity ID for an OpenEPaperLink device.

    Resolves a Home Assistant device ID to the corresponding
    OpenEPaperLink entity ID by finding the device in the device
    registry and extracting the MAC address from its identifiers.

    Args:
        hass: Home Assistant instance
        device_id: Home Assistant device ID

    Returns:
        str: Entity ID in the format "open_epaper_link.mac_address"

    Raises:
        HomeAssistantError: If device not found or not an OpenEPaperLink device
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if not device:
        raise HomeAssistantError(f"Device {device_id} not found")

    # Get the first entity ID associated with this device
    if not device.identifiers:
        raise HomeAssistantError(f"No identifiers found for device {device_id}")

    # Get the MAC address from the device identifier
    domain_mac = next(iter(device.identifiers))
    if domain_mac[0] != DOMAIN:
        raise HomeAssistantError(f"Device {device_id} is not an OpenEPaperLink device")

    # Handle BLE device identifiers (format: "ble_MAC") vs Hub tags (format: "MAC")
    identifier = domain_mac[1]
    if identifier.startswith("ble_"):
        mac_address = identifier[4:]  # Remove "ble_" prefix
    else:
        mac_address = identifier
    
    return f"{DOMAIN}.{mac_address.lower()}"


class UploadQueueHandler:
    """Handle queued image uploads to the AP.

    Manages a queue of image upload tasks to prevent overwhelming the AP with concurrent requests.

    Features include:

    - Maximum concurrent upload limit
    - Cooldown period between uploads
    - Task tracking and status reporting

    This helps maintain AP stability while processing multiple image requests from different parts of Home Assistant.
    """

    def __init__(self, max_concurrent: int = 1, cooldown: float = 1.0):
        """Initialize the upload queue handler.

        Args:
            max_concurrent: Maximum number of concurrent uploads (default: 1)
            cooldown: Cooldown period in seconds between uploads (default: 1.0)
        """
        self._queue = asyncio.Queue()
        self._processing = False
        self._max_concurrent = max_concurrent
        self._cooldown = cooldown
        self._active_uploads = 0
        self._last_upload = None
        self._lock = asyncio.Lock()

    def __str__(self):
        """Return queue status string."""
        return f"Queue(active={self._active_uploads}, size={self._queue.qsize()})"

    async def add_to_queue(self, upload_func, *args, **kwargs):
        """Add an upload task to the queue.

        Queues an upload function with its arguments for later execution.
        Starts the queue processor if it's not already running.

        Args:
            upload_func: Async function that performs the actual upload
            *args: Positional arguments to pass to the upload function
            **kwargs: Keyword arguments to pass to the upload function
        """

        entity_id = next((arg for arg in args if isinstance(arg, str) and "." in arg), "unknown")

        _LOGGER.debug("Adding upload task to queue for %s. %s", entity_id, self)
        # Add task to queue
        await self._queue.put((upload_func, args, kwargs))

        # Start processing queue if not already running
        if not self._processing:
            _LOGGER.debug("Starting upload queue processor for %s", entity_id)
            asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        """Process queued upload tasks with true parallelism.

        Long-running task that processes the upload queue, respecting:

        - Maximum concurrent upload limit
        - Cooldown period between uploads

        Creates background tasks for parallel execution instead of blocking.
        Handles errors in individual uploads without stopping queue processing.
        This method runs until the queue is empty, then terminates.
        """
        self._processing = True
        _LOGGER.debug("Upload queue processor started. %s", self)
        
        running_tasks = set()

        try:
            while not self._queue.empty() or running_tasks:
                # Clean up completed tasks
                if running_tasks:
                    done_tasks = {task for task in running_tasks if task.done()}
                    for task in done_tasks:
                        running_tasks.remove(task)
                        # Get the result to handle any exceptions
                        try:
                            await task
                        except Exception as err:
                            _LOGGER.error("Background upload task failed: %s", str(err))

                # Check if new uploads can be started
                async with self._lock:
                    if (not self._queue.empty() and 
                        self._active_uploads < self._max_concurrent):
                        
                        # Check cooldown period
                        if self._last_upload:
                            elapsed = (datetime.now() - self._last_upload).total_seconds()
                            if elapsed < self._cooldown:
                                _LOGGER.debug("In cooldown period (%.1f seconds remaining)",
                                              self._cooldown - elapsed)
                                await asyncio.sleep(self._cooldown - elapsed)

                        # Get next task from queue
                        upload_func, args, kwargs = await self._queue.get()
                        entity_id = next((arg for arg in args if isinstance(arg, str) and "." in arg), "unknown")

                        # Create and start background task
                        task = asyncio.create_task(self._execute_upload(upload_func, args, kwargs, entity_id))
                        running_tasks.add(task)
                        
                        # Update last upload timestamp
                        self._last_upload = datetime.now()
                        
                    else:
                        # Wait a bit before checking again
                        await asyncio.sleep(0.1)

        finally:
            # Wait for all running tasks to complete
            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)
            self._processing = False

    async def _execute_upload(self, upload_func, args, kwargs, entity_id):
        """Execute a single upload task in the background."""
        try:
            # Increment active uploads counter
            async with self._lock:
                self._active_uploads += 1
            _LOGGER.debug("Starting upload for %s. %s", entity_id, self)

            # Perform upload
            _LOGGER.debug("Starting queued upload task")
            start_time = datetime.now()
            await upload_func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()

            _LOGGER.debug("Upload completed for %s in %.1f seconds", entity_id, duration)

        except Exception as err:
            _LOGGER.error("Error processing queued upload for %s: %s", entity_id, str(err))
        finally:
            # Decrement active upload counter
            async with self._lock:
                self._active_uploads -= 1
            # Mark task as done
            self._queue.task_done()
            _LOGGER.debug("Upload task for %s finished. %s", entity_id, self)


async def async_setup_services(hass: HomeAssistant, service_type: str = "all") -> None:
    """Set up the OpenEPaperLink services.

    Registers service handlers for the integration based on device type:

    - service_type="all": All services (AP and BLE compatible)
    - service_type="ble": Only BLE-compatible services (drawcustom)
    - service_type="ap": All services (backwards compatibility)

    Services by category:
    - BLE compatible: drawcustom
    - AP only: setled, clear_pending, force_refresh, reboot_tag, scan_channels, reboot_ap, refresh_tag_types

    Also registers handlers for deprecated services that show errors.

    Args:
        hass: Home Assistant instance
        service_type: Type of services to register ("all", "ble", "ap")
    """

    # Separate queues for different device types
    ble_upload_queue = UploadQueueHandler(max_concurrent=3, cooldown=0.1)
    hub_upload_queue = UploadQueueHandler(max_concurrent=1, cooldown=1.0)


    async def drawcustom_service(service: ServiceCall) -> None:
        """Handle drawcustom service calls.

        Processes requests to generate and upload custom images to tags.
        The service supports:

        - Multiple target devices
        - Custom content with text, shapes, and images
        - Background color and rotation
        - Dithering options
        - "Dry run" mode for testing

        For each target device, the service:

        1. Resolves device ID to entity ID
        2. Generates image with the ImageGen component
        3. Queues image upload to the AP
        4. Collects and reports any errors

        Args:
            service: Service call object with parameters and target devices

        Raises:
            HomeAssistantError: If AP is offline or image generation fails
        """
        # Check if any Hub (AP-based) devices require Hub connectivity
        # BLE devices don't need the Hub to be online
        hub = None

        label_ids = service.data.get("label_id", [])
        device_ids = service.data.get("device_id", [])

        if isinstance(device_ids, str):
            device_ids = [device_ids]

        if isinstance(label_ids, str):
            label_ids = [label_ids]

        for label_id in label_ids:
            device_ids.extend(await get_device_ids_from_label_id(hass, label_id))

        generator = ImageGen(hass)
        errors = []

        # Process each device
        for device_id in device_ids:
            device_errors = []
            try:
                # Get entity ID from device ID
                entity_id = await get_entity_id_from_device_id(hass, device_id)
                _LOGGER.debug("Processing device_id: %s (entity_id: %s)", device_id, entity_id)

                # Determine if this is a BLE device by checking device registry
                device_registry = dr.async_get(hass)
                device = device_registry.async_get(device_id)
                is_ble_device = False
                if device and device.identifiers:
                    domain_mac = next(iter(device.identifiers))
                    is_ble_device = domain_mac[1].startswith("ble_")

                # For Hub devices, ensure Hub is online
                if not is_ble_device:
                    if hub is None:
                        hub = get_hub_from_hass(hass)
                    if not hub.online:
                        raise HomeAssistantError(
                            "AP is offline. Please check your network connection and AP status."
                        )

                try:
                    # Generate image (BLE vs Hub path will be handled in ImageGen)
                    if is_ble_device:
                        # For BLE devices, tag info must be provided since they don't use Hub
                        tag_info = await generator.get_ble_tag_info(hass, entity_id)
                        image_data = await generator.generate_custom_image(
                            entity_id=entity_id,
                            service_data=service.data,
                            error_collector=device_errors,
                            tag_info=tag_info
                        )
                    else:
                        # Hub devices use existing path
                        image_data = await generator.generate_custom_image(
                            entity_id=entity_id,
                            service_data=service.data,
                            error_collector=device_errors
                        )

                    if device_errors:
                        errors.extend([f"Device {entity_id}: {err}" for err in device_errors])
                        _LOGGER.warning(
                            "Completed with warnings for device %s:\n%s",
                            device_id,
                            "\n".join(device_errors)
                        )

                    if service.data.get("dry-run", False):
                        _LOGGER.info("Dry run completed for %s", entity_id)
                        tag_mac = entity_id.split(".")[1].upper()
                        async_dispatcher_send(
                            hass,
                            f"{SIGNAL_TAG_IMAGE_UPDATE}_{tag_mac}",
                            image_data
                        )
                        continue

                    # Choose upload method based on device type
                    if is_ble_device:
                        # Check Bluetooth availability before queuing BLE upload
                        from .util import is_bluetooth_available
                        if not is_bluetooth_available(hass):
                            raise HomeAssistantError(
                                f"Cannot upload to BLE device {entity_id}: "
                                "Bluetooth integration is disabled or no scanners available. "
                                "Please enable Bluetooth integration in Home Assistant."
                            )
                            
                        # Queue BLE upload (only if Bluetooth is available)
                        await ble_upload_queue.add_to_queue(
                            upload_ble_image,
                            hass,
                            entity_id,
                            image_data
                        )
                    else:
                        # Queue Hub/AP upload
                        await hub_upload_queue.add_to_queue(
                            upload_image,
                            hub,
                            entity_id,
                            image_data,
                            service.data.get("dither", DITHER_DEFAULT),
                            service.data.get("ttl", 60),
                            service.data.get("preload_type", 0),
                            service.data.get("preload_lut", 0)
                        )

                except Exception as err:
                    error_msg = f"Error processing device {entity_id}: {str(err)}"
                    errors.append(error_msg)
                    _LOGGER.error(error_msg)
                    continue

            except Exception as err:
                error_msg = f"Failed to process device {device_id}: {str(err)}"
                errors.append(error_msg)
                _LOGGER.error(error_msg)
                continue

        if errors:
            raise HomeAssistantError("\n".join(errors))

    async def upload_image(hub, entity_id: str, img: bytes, dither: int, ttl: int,
                           preload_type: int = 0, preload_lut: int = 0) -> None:
        """Upload image to tag through AP.

        Sends an image to the AP for display on a specific tag using
        multipart/form-data POST request. Configures display parameters
        such as dithering, TTL, and optional preloading.

        Will retry upload on timeout, with increasing backoff times

        Args:
            hub: Hub instance with connection details
            entity_id: Entity ID of the target tag
            img: JPEG image data as bytes
            dither: Dithering mode (0=none, 1=Floyd-Steinberg, 2=ordered)
            ttl: Time-to-live in seconds
            preload_type: Type for image preloading (0=disabled)
            preload_lut: Look-up table for preloading

        Raises:
            HomeAssistantError: If upload fails or times out
        """
        url = f"http://{hub.host}/imgupload"
        mac = entity_id.split(".")[1].upper()

        _LOGGER.debug("Preparing upload for %s (MAC: %s)", entity_id, mac)
        _LOGGER.debug("Upload parameters: dither=%d, ttl=%d, preload_type=%d, preload_lut=%d",
                      dither, ttl, preload_type, preload_lut)

        # Convert TTL fom seconds to minutes for the AP
        ttl_minutes = max(1, ttl // 60)

        backoff_delay = INITIAL_BACKOFF # Try up to MAX_RETRIES times to upload the image, retrying on TimeoutError.

        for attempt in range(1, MAX_RETRIES + 1):
            try:

                # Create a new MultipartEncoder for each attempt
                fields = {
                    'mac': mac,
                    'contentmode': "25",
                    'dither': str(dither),
                    'ttl': str(ttl_minutes),
                    'image': ('image.jpg', img, 'image/jpeg'),
                }

                if preload_type > 0:
                    fields.update({
                        'preloadtype': str(preload_type),
                        'preloadlut': str(preload_lut),
                    })

                mp_encoder = MultipartEncoder(fields=fields)

                async with async_timeout.timeout(30):  # 30 second timeout for upload
                    response = await hass.async_add_executor_job(
                        lambda: requests.post(
                            url,
                            headers={'Content-Type': mp_encoder.content_type},
                            data=mp_encoder
                        )
                    )

                if response.status_code != 200:
                    raise HomeAssistantError(
                        f"Image upload failed for {entity_id} with status code: {response.status_code}"
                    )
                break

            except asyncio.TimeoutError:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Timeout uploading %s (attempt %d/%d), retrying in %ds…",
                        entity_id, attempt, MAX_RETRIES, backoff_delay
                    )
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2  # exponential back-off
                    continue
                raise HomeAssistantError(f"Image upload timed out for {entity_id}")
            except Exception as err:
                raise HomeAssistantError(f"Failed to upload image for {entity_id}: {str(err)}")

    async def upload_ble_image(hass: HomeAssistant, entity_id: str, img: bytes) -> None:
        """Upload image to BLE tag.

        Sends an image to a BLE tag using direct Bluetooth communication.
        This bypasses the AP and provides faster upload times.

        Args:
            hass: Home Assistant instance
            entity_id: Entity ID of the target tag
            img: JPEG image data as bytes

        Raises:
            HomeAssistantError: If BLE upload fails
        """

        mac = entity_id.split(".")[1].upper()
        _LOGGER.debug("Preparing BLE upload for %s (MAC: %s)", entity_id, mac)

        try:
            # Get device metadata from Home Assistant data
            domain_data = hass.data.get(DOMAIN, {})
            device_metadata = None
            
            # Find the config entry for this BLE device
            for entry_id, entry_data in domain_data.items():
                if (is_ble_entry(entry_data) and
                    entry_data.get("mac_address", "").upper() == mac):
                    device_metadata = entry_data.get("device_metadata", {})
                    break
            
            if not device_metadata:
                raise HomeAssistantError(f"No metadata found for BLE device {entity_id}")
            
            # Create DeviceMetadata object
            metadata = DeviceMetadata(
                hw_type=device_metadata.get("hw_type", 0),
                fw_version=device_metadata.get("fw_version", 0),
                width=device_metadata.get("width", 0),
                height=device_metadata.get("height", 0),
                color_support=device_metadata.get("color_support", "mono"),
                rotatebuffer=device_metadata.get("rotatebuffer", 0)
            )
            

            # Upload via BLE
            success = await ble_upload_image(hass, mac, img, metadata)
            if not success:
                raise HomeAssistantError(f"BLE image upload failed for {entity_id}")
                
        except Exception as err:
            _LOGGER.error("BLE upload error for %s: %s", entity_id, err)
            raise HomeAssistantError(f"Failed to upload image via BLE to {entity_id}: {str(err)}") from err

    async def setled_service(service: ServiceCall) -> None:
        """Handle LED pattern service calls.

        Configures LED flashing patterns for tags. Supports:

        - Off/flashing mode
        - Brightness settings
        - Multi-color patterns with timing
        - Repeat counts

        The LED pattern is encoded as a hex string according to the
        OpenEPaperLink protocol specification (https://github.com/OpenEPaperLink/OpenEPaperLink/wiki/Led-control).

        Args:
            service: Service call object with parameters and target devices

        Raises:
            HomeAssistantError: If AP is offline or request fails
        """
        hub = get_hub_from_hass(hass)
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        device_ids = service.data.get("device_id")
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            entity_id = await get_entity_id_from_device_id(hass, device_id)
            _LOGGER.info("Processing device_id: %s (entity_id: %s)", device_id, entity_id)
            mac = entity_id.split(".")[1].upper()

            mode = service.data.get("mode", "")
            modebyte = "1" if mode == "flash" else "0"
            brightness = service.data.get("brightness", 2)
            modebyte = hex(((brightness - 1) << 4) + int(modebyte))[2:]

            pattern = (
                    modebyte +
                    rgb_to_rgb332(service.data.get("color1", "")) +
                    hex(int(service.data.get("flashSpeed1", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount1", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay1", 0.1) * 10)) +
                    rgb_to_rgb332(service.data.get("color2", "")) +
                    hex(int(service.data.get("flashSpeed2", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount2", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay2", 0.1) * 10)) +
                    rgb_to_rgb332(service.data.get("color3", "")) +
                    hex(int(service.data.get("flashSpeed3", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount3", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay3", 0.0) * 10)) +
                    int_to_hex_string(service.data.get("repeats", 2) - 1) +
                    "00"
            )

            url = f"http://{hub.host}/led_flash?mac={mac}&pattern={pattern}"
            result = await hass.async_add_executor_job(requests.get, url)
            if result.status_code != 200:
                _LOGGER.warning("LED pattern update failed with status code: %s", result.status_code)

    async def clear_pending_service(service: ServiceCall) -> None:
        """Handle clear pending service calls.

        Sends command to clear any pending updates for the target tags,
        canceling queued content changes that haven't been applied yet.

        Args:
            service: Service call object with target devices
        """
        device_ids = service.data.get("device_id")
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            entity_id = await get_entity_id_from_device_id(hass, device_id)
            await send_tag_cmd(hass, entity_id, "clear")

    async def force_refresh_service(service: ServiceCall) -> None:
        """Handle force refresh service calls.

        Sends command to force the refresh of the tag display,
        to for example redraw content.

        Args:
            service: Service call object with target devices
        """
        device_ids = service.data.get("device_id")
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            entity_id = await get_entity_id_from_device_id(hass, device_id)
            await send_tag_cmd(hass, entity_id, "refresh")

    async def reboot_tag_service(service: ServiceCall) -> None:
        """Handle tag reboot service calls.

        Sends command to reboot the target tags, performing a full
        restart of the tags.

        Args:
            service: Service call object with target devices
        """
        device_ids = service.data.get("device_id")
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            entity_id = await get_entity_id_from_device_id(hass, device_id)
            await send_tag_cmd(hass, entity_id, "reboot")

    async def scan_channels_service(service: ServiceCall) -> None:
        """Handle channel scan service calls.

        Sends command to trigger an IEEE 802.15.4 channel scan on the
        target tags.

        Args:
            service: Service call object with target devices
        """
        device_ids = service.data.get("device_id")
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            entity_id = await get_entity_id_from_device_id(hass, device_id)
            await send_tag_cmd(hass, entity_id, "scan")

    async def reboot_ap_service(service: ServiceCall) -> None:
        """Handle AP reboot service calls.

        Sends command to reboot the Access Point, performing a full
        restart of the AP firmware. This temporarily disconnects all tags.

        Args:
            service: Service call object with target devices
        """
        await reboot_ap(hass)

    async def refresh_tag_types_service(service: ServiceCall) -> None:
        """Handle tag type refresh service calls.

        Forces a refresh of tag type definitions from the GitHub repository,
        updating the local cache with the latest hardware support information.

        Creates a persistent notification when complete to inform the user.

        Args:
            service: Service call object with target devices
        """
        manager = await get_tag_types_manager(hass)
        manager._last_update = None  # Force refresh
        await manager.ensure_types_loaded()

        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag types from GitHub"

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refreshed",
                "message": message,
                "notification_id": "tag_types_refresh_notification",
            },
        )
    # Register services available for all device types
    hass.services.async_register(DOMAIN, "drawcustom", drawcustom_service)

    # Register AP-only services based on service_type
    if service_type in ["all", "ap"]:
        hass.services.async_register(DOMAIN, "setled", setled_service)
        hass.services.async_register(DOMAIN, "clear_pending", clear_pending_service)
        hass.services.async_register(DOMAIN, "force_refresh", force_refresh_service)
        hass.services.async_register(DOMAIN, "reboot_tag", reboot_tag_service)
        hass.services.async_register(DOMAIN, "scan_channels", scan_channels_service)
        hass.services.async_register(DOMAIN, "reboot_ap", reboot_ap_service)
        hass.services.async_register(DOMAIN, "refresh_tag_types", refresh_tag_types_service)

    # Register handlers for deprecated services that just show error
    async def deprecated_service_handler(service: ServiceCall, old_service: str) -> None:
        """Handler for deprecated services that raises an error.

        Provides informative error messages when users try to use
        deprecated services (dlimg, lines4, lines5), guiding them
        to use the current drawcustom service instead.

        Args:
            service: Service call object
            old_service: Name of the deprecated service

        Raises:
            HomeAssistantError: Always raises this with migration information
        """
        raise HomeAssistantError(
            f"The service {DOMAIN}.{old_service} has been removed. "
            f"Please use {DOMAIN}.drawcustom instead. "
            "See the documentation for more details."
        )

    # Register deprecated services with error message (only if all services are being registered)
    if service_type in ["all", "ap"]:
        for old_service in ["dlimg", "lines5", "lines4"]:
            hass.services.async_register(
                DOMAIN,
                old_service,
                lambda call, name=old_service: deprecated_service_handler(call, name)
            )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload OpenEPaperLink services.

    Removes all registered service handlers when the integration
    is unloaded. This prevents service calls to a non-existent
    integration.

    Only removes services that were actually registered to prevent errors.

    Args:
        hass: Home Assistant instance
    """
    # Always try to remove drawcustom service (registered for all device types)
    if hass.services.has_service(DOMAIN, "drawcustom"):
        hass.services.async_remove(DOMAIN, "drawcustom")

    # Remove AP-only services if they exist
    ap_services = ["setled", "clear_pending", "force_refresh", "reboot_tag", "scan_channels", "reboot_ap", "refresh_tag_types"]
    for service in ap_services:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    # Remove deprecated services if they exist
    deprecated_services = ["dlimg", "lines5", "lines4"]
    for service in deprecated_services:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
