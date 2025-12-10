from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from io import BytesIO
from typing import Final

import async_timeout
import requests
from requests_toolbelt import MultipartEncoder

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .runtime_data import OpenEPaperLinkBLERuntimeData
from .const import DOMAIN, SIGNAL_TAG_IMAGE_UPDATE
from .ble import BLEConnection, BLEImageUploader, BLEDeviceMetadata, get_protocol_by_name

_LOGGER: Final = logging.getLogger(__name__)

DITHER_DISABLED = 0
DITHER_FLOYD_BURKES = 1
DITHER_ORDERED = 2
DITHER_DEFAULT = DITHER_ORDERED

MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds


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


async def upload_to_hub(hub, entity_id: str, img: bytes, dither: int, ttl: int,
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
                response = await hub.hass.async_add_executor_job(
                    lambda: requests.post(
                        url,
                        headers={'Content-Type': mp_encoder.content_type},
                        data=mp_encoder
                    )
                )

            if response.status_code != 200:
                raise ServiceValidationError(
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
            raise ServiceValidationError(f"Image upload timed out for {entity_id}")
        except Exception as err:
            raise ServiceValidationError(f"Failed to upload image for {entity_id}: {str(err)}")


async def upload_to_ble_block(hass: HomeAssistant, entity_id: str, img: bytes, dither: int = 2) -> None:
    """Upload image to BLE tag using block-based protocol.

    Sends an image to a BLE tag using direct Bluetooth communication.
    This bypasses the AP and provides faster upload times.

    Uses protocol-specific service UUID based on device firmware type.
    This method is used for ATC devices and as fallback for OEPL devices.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID of the target tag
        img: JPEG image data as bytes
        dither: Dithering mode (0=none, 1=Burkes, 2=ordered)

    Raises:
        HomeAssistantError: If BLE upload fails
    """

    mac = entity_id.split(".")[1].upper()
    _LOGGER.debug("Preparing BLE block-based upload for %s (MAC: %s)", entity_id, mac)

    try:
        # Get device metadata from Home Assistant data
        device_metadata = None
        protocol_type = "atc"  # Default to ATC for backward compatibility

        # Find the config entry for this BLE device
        for entry in hass.config_entries.async_entries(DOMAIN):
            runtime_data = getattr(entry, 'runtime_data', None)
            if runtime_data is not None and isinstance(runtime_data, OpenEPaperLinkBLERuntimeData):
                if runtime_data.mac_address.upper() == mac:
                    device_metadata = runtime_data.device_metadata
                    protocol_type = runtime_data.protocol_type
                    break


        if not device_metadata:
            raise ServiceValidationError(f"No metadata found for BLE device {entity_id}")

        # Get protocol handler for service UUID
        protocol = get_protocol_by_name(protocol_type)
        _LOGGER.debug("Using protocol %s for device %s", protocol_type, entity_id)

        # Wrap metadata and create DeviceMetadata object
        metadata = BLEDeviceMetadata(device_metadata)

        # Upload via BLE using protocol-specific service UUID
        async with BLEConnection(hass, mac, protocol.service_uuid, protocol) as conn:
            uploader = BLEImageUploader(conn, mac)
            success, processed_image = await uploader.upload_image_block_based(img, metadata, protocol_type, dither)

            if not success:
                raise ServiceValidationError(f"BLE image upload failed for {entity_id}")

            if processed_image is not None:
                buffer = BytesIO()
                processed_image.save(buffer, format="JPEG", quality=95)
                jpeg_bytes = buffer.getvalue()
                async_dispatcher_send(
                    hass,
                    f"{SIGNAL_TAG_IMAGE_UPDATE}_{mac}",
                    jpeg_bytes
                )

    except Exception as err:
        _LOGGER.error("BLE upload error for %s: %s", entity_id, err)
        raise ServiceValidationError(f"Failed to upload image via BLE to {entity_id}: {str(err)}") from err


async def upload_to_ble_direct(
        hass: HomeAssistant, entity_id: str, img: bytes, compressed: bool = False, dither: int = 2
) -> None:
    """Upload image to BLE tag using direct write protocol (OEPL only).

    Sends an image to an OEPL BLE tag using direct write mode.
    This is faster than block-based upload and supports all color schemes.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID of the target tag
        img: JPEG image data as bytes
        compressed: Whether to compress the image data
        dither: Dithering mode (0=none, 1=Burkes, 2=ordered)

    Raises:
        HomeAssistantError: If BLE direct write upload fails
    """
    mac = entity_id.split(".")[1].upper()
    _LOGGER.debug(
        "Preparing BLE direct write upload for %s (MAC: %s, compressed=%s)",
        entity_id,
        mac,
        compressed
    )

    try:
        # Get device metadata from Home Assistant data
        device_metadata = None
        protocol_type = "oepl"  # Direct write is OEPL only

        # Find the config entry for this BLE device
        for entry in hass.config_entries.async_entries(DOMAIN):
            runtime_data = getattr(entry, 'runtime_data', None)
            if runtime_data is not None and isinstance(runtime_data, OpenEPaperLinkBLERuntimeData):
                if runtime_data.mac_address.upper() == mac:
                    device_metadata = runtime_data.device_metadata
                    protocol_type = runtime_data.protocol_type
                    break

        if not device_metadata:
            raise ServiceValidationError(f"No metadata found for BLE device {entity_id}")

        # Verify this is an OEPL device
        metadata = BLEDeviceMetadata(device_metadata)
        if not metadata.is_oepl:
            raise ServiceValidationError(
                f"Direct write is only supported for OEPL devices, "
                f"but {entity_id} appears to be an ATC device"
            )

        # Get protocol handler for service UUID
        protocol = get_protocol_by_name(protocol_type)
        _LOGGER.debug("Using protocol %s for direct write on device %s", protocol_type, entity_id)

        # Upload via BLE using direct write protocol
        async with BLEConnection(hass, mac, protocol.service_uuid, protocol) as conn:
            uploader = BLEImageUploader(conn, mac)
            success, processed_image = await uploader.upload_direct_write(img, metadata, compressed, dither)

            if not success:
                raise ServiceValidationError(f"BLE direct write upload failed for {entity_id}")

            if processed_image is not None:
                buffer = BytesIO()
                processed_image.save(buffer, format="JPEG", quality=95)
                jpeg_bytes = buffer.getvalue()
                async_dispatcher_send(
                    hass,
                    f"{SIGNAL_TAG_IMAGE_UPDATE}_{mac}",
                    jpeg_bytes
                )

    except Exception as err:
        _LOGGER.error("BLE direct write error for %s: %s", entity_id, err)
        raise ServiceValidationError(
            f"Failed to upload image via BLE direct write to {entity_id}: {str(err)}"
        ) from err


def create_upload_queues() -> tuple[UploadQueueHandler, UploadQueueHandler]:
    """Create BLE and Hub upload queues with appropriate settings."""
    ble_queue = UploadQueueHandler(max_concurrent=1, cooldown=0.1)
    hub_queue = UploadQueueHandler(max_concurrent=1, cooldown=1.0)
    return ble_queue, hub_queue