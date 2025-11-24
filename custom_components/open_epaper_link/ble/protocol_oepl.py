"""OEPL firmware protocol implementation."""
import logging
from typing import TYPE_CHECKING

from .protocol_base import BLEProtocol, AdvertisingData, DeviceCapabilities
from .tlv_parser import parse_tlv_config, extract_display_capabilities, GlobalConfig
from .exceptions import ConfigValidationError

if TYPE_CHECKING:
    from .connection import BLEConnection

_LOGGER = logging.getLogger(__name__)

# OEPL protocol constants
CMD_READ_CONFIG = bytes([0x00, 0x40])


def _format_config_summary(config: GlobalConfig, mac_address: str) -> str:
    """Format OEPL configuration as human-readable debug output.

    Args:
        config: Parsed OEPL device configuration
        mac_address: Device MAC address for reference

    Returns:
        Multi-line formatted configuration summary
    """
    lines = [f"\nOEPL Configuration for {mac_address}:"]

    # Device Identity
    lines.append("  Device:")
    if config.system:
        ic_names = {1: "nRF52840", 2: "ESP32-S3", 3: "ESP32-C3", 4: "ESP32-C6"}
        ic_type = ic_names.get(config.system.ic_type, f"Unknown ({config.system.ic_type})")
        lines.append(f"    - IC Type: {ic_type}")
        lines.append(f"    - Communication Modes: 0x{config.system.communication_modes:02x}")
        lines.append(f"    - Device Flags: 0x{config.system.device_flags:02x}")

    if config.manufacturer:
        lines.append(f"    - Manufacturer ID: 0x{config.manufacturer.manufacturer_id:04x}")
        lines.append(f"    - Board Type: {config.manufacturer.board_type}")
        lines.append(f"    - Board Revision: {config.manufacturer.board_revision}")

    # Display Configuration (primary display)
    if config.displays:
        display = config.displays[0]  # Primary display
        lines.append("  Display (primary):")

        # Calculate diagonal size if physical dimensions available
        size_info = f"{display.pixel_width}x{display.pixel_height} pixels"
        if display.active_width_mm > 0 and display.active_height_mm > 0:
            import math
            diagonal_mm = math.sqrt(display.active_width_mm ** 2 + display.active_height_mm ** 2)
            diagonal_inches = diagonal_mm / 25.4
            size_info += f" ({display.active_width_mm}x{display.active_height_mm}mm, {diagonal_inches:.1f}\")"
        lines.append(f"    - Dimensions: {size_info}")

        color_scheme = "BWR" if display.color_scheme == 1 else "Monochrome"
        lines.append(f"    - Color Scheme: {color_scheme}")
        lines.append(f"    - Rotation: {display.rotation}°")
        lines.append(f"    - Panel IC: {display.panel_ic_type}")

        if len(config.displays) > 1:
            lines.append(f"    - Additional Displays: {len(config.displays) - 1}")

    # Power Configuration
    if config.power:
        lines.append("  Power:")
        lines.append(f"    - Battery Capacity: {config.power.battery_capacity_mah} mAh")
        lines.append(f"    - Power Mode: {config.power.power_mode}")

        # Convert sleep timeout to human-readable format
        sleep_sec = config.power.sleep_timeout_ms / 1000
        if sleep_sec >= 60:
            lines.append(f"    - Sleep Timeout: {sleep_sec / 60:.1f} minutes")
        else:
            lines.append(f"    - Sleep Timeout: {sleep_sec:.1f} seconds")

        lines.append(f"    - TX Power: {config.power.tx_power:+d} dBm")
        lines.append(f"    - Deep Sleep Current: {config.power.deep_sleep_current_ua} µA")

    # Optional Hardware Summary
    hardware_summary = []
    if config.leds:
        led_types = ", ".join([f"#{led.instance_number} type {led.led_type}" for led in config.leds])
        hardware_summary.append(f"LEDs: {len(config.leds)} ({led_types})")

    if config.sensors:
        sensor_types = ", ".join([f"#{sensor.instance_number} type {sensor.sensor_type}" for sensor in config.sensors])
        hardware_summary.append(f"Sensors: {len(config.sensors)} ({sensor_types})")

    if config.buses:
        bus_types = {0: "I2C", 1: "SPI"}
        bus_list = ", ".join([f"#{bus.instance_number} {bus_types.get(bus.bus_type, 'Unknown')}" for bus in config.buses])
        hardware_summary.append(f"Buses: {len(config.buses)} ({bus_list})")

    if config.inputs:
        hardware_summary.append(f"Digital Inputs: {len(config.inputs)}")

    if hardware_summary:
        lines.append("  Optional Hardware:")
        for hw in hardware_summary:
            lines.append(f"    - {hw}")

    return "\n".join(lines)


class OEPLProtocol(BLEProtocol):
    """OEPL firmware protocol implementation.

    Supports the new OEPL BLE firmware protocol with:
    - Manufacturer ID: 0x2446 (9286)
    - Service UUID: 00002446-0000-1000-8000-00805f9b34fb
    - Interrogation: CMD_READ_CONFIG (0x0040) with TLV parsing
    - Advertising: 13-byte format (sensor data currently placeholder)
    - Complete TLV configuration system
    """

    def __init__(self):
        """Initialize OEPL protocol."""
        self._last_config: GlobalConfig | None = None

    @property
    def manufacturer_id(self) -> int:
        """Bluetooth manufacturer ID for OEPL firmware."""
        return 0x2446  # 9286 decimal

    @property
    def service_uuid(self) -> str:
        """BLE GATT service UUID for OEPL firmware."""
        return "00002446-0000-1000-8000-00805f9b34fb"

    @property
    def protocol_name(self) -> str:
        """Protocol identifier."""
        return "oepl"

    def parse_advertising_data(self, data: bytes) -> AdvertisingData:
        """Parse OEPL manufacturer data for device state updates.

        OEPL firmware uses the same advertising format as ATC firmware:
        [version, hw_type_low, hw_type_high, fw_low, fw_high, reserved_low, reserved_high,
         battery_low, battery_high, temperature, counter]

        Args:
            data: Manufacturer-specific advertising data

        Returns:
            AdvertisingData: Parsed advertising information

        Raises:
            ValueError: If data format is invalid
        """
        if not data:
            raise ValueError("Empty advertising data")

        # Minimum required: version(1) + hw_type(2) + fw_version(2) = 5 bytes
        if len(data) < 5:
            raise ValueError(f"OEPL advertising requires at least 5 bytes, got {len(data)}")

        # Parse core fields (same layout as ATC)
        version = data[0]
        hw_type = int.from_bytes(data[1:3], "little")
        fw_version = int.from_bytes(data[3:5], "little")

        # Parse optional sensor data if present
        battery_mv = 0
        battery_pct = 0
        temperature = None

        # Battery voltage at bytes 7-8 (same as ATC)
        if len(data) >= 9:
            battery_mv = int.from_bytes(data[7:9], "little")
            battery_pct = self._calculate_battery_percentage(battery_mv) if battery_mv > 0 else 0

        # Temperature at byte 9 (signed int8, same as ATC)
        if len(data) >= 10:
            import struct
            temperature = struct.unpack("<b", data[9:10])[0]

        return AdvertisingData(
            battery_mv=battery_mv,
            battery_pct=battery_pct,
            temperature=temperature,
            hw_type=hw_type,
            fw_version=fw_version,
            version=version,
        )

    async def interrogate_device(self, connection: "BLEConnection") -> DeviceCapabilities:
        """Query device during setup using CMD_READ_CONFIG (0x0040).

        Reads the complete device TLV configuration but returns only the
        minimal display information needed for Home Assistant entity setup.

        This replaces the legacy 0x0005 command used by ATC firmware.

        The OEPL firmware sends config data in chunks:
        - Chunk 0: [cmd_echo:2][chunk_num:2][total_len:2][tlv_data:~94]
        - Chunk N: [cmd_echo:2][chunk_num:2][tlv_data:~96]

        Args:
            connection: Active BLE connection to device

        Returns:
            DeviceCapabilities: Minimal device information for HA setup

        Raises:
            ConfigValidationError: If config is invalid or missing display data
        """
        import asyncio

        _LOGGER.debug("OEPL device interrogation for %s", connection.mac_address)

        # Read first chunk
        response = await connection.write_command_with_response(CMD_READ_CONFIG)

        _LOGGER.debug(
            "OEPL config response for %s: received %d bytes",
            connection.mac_address,
            len(response),
        )

        # Debug: log first 20 bytes to understand response format
        _LOGGER.debug(
            "OEPL config first 20 bytes: %s",
            response[:20].hex() if len(response) >= 20 else response.hex()
        )

        # Strip command echo (first 2 bytes are the command 0x0040 echoed back)
        if len(response) >= 2 and response[0:2] == CMD_READ_CONFIG:
            chunk_data = response[2:]
            _LOGGER.debug("Stripped command echo, chunk data is %d bytes", len(chunk_data))
        else:
            chunk_data = response
            _LOGGER.warning("Expected command echo not found, using full response")

        # Parse chunk header
        if len(chunk_data) < 4:
            raise ConfigValidationError(f"Chunk data too short: {len(chunk_data)} bytes")

        chunk_num = int.from_bytes(chunk_data[0:2], "little")
        _LOGGER.debug("Received chunk number: %d", chunk_num)

        if chunk_num != 0:
            raise ConfigValidationError(f"Expected chunk 0, got chunk {chunk_num}")

        # Parse total length from chunk 0
        total_length = int.from_bytes(chunk_data[2:4], "little")
        _LOGGER.debug("Total config length: %d bytes", total_length)

        # Extract TLV data from chunk 0 (skip 4-byte chunk header)
        tlv_data = bytearray(chunk_data[4:])
        _LOGGER.debug("Chunk 0 TLV data: %d bytes", len(tlv_data))

        # Collect remaining chunks if needed
        # Firmware sends all chunks automatically with 50ms delay between them
        max_chunks = 10  # Safety limit to prevent infinite loops
        current_chunk = 1

        while len(tlv_data) < total_length and current_chunk < max_chunks:
            _LOGGER.debug(
                "Waiting for chunk %d (have %d of %d bytes)",
                current_chunk,
                len(tlv_data),
                total_length,
            )

            try:
                # Read next chunk from queue (firmware sends them automatically)
                next_response = await asyncio.wait_for(
                    connection._response_queue.get(), timeout=2.0
                )
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout waiting for chunk %d (have %d of %d bytes)",
                    current_chunk,
                    len(tlv_data),
                    total_length,
                )
                break

            _LOGGER.debug("Received chunk response: %d bytes", len(next_response))

            # Strip command echo from next chunk
            if len(next_response) >= 2 and next_response[0:2] == CMD_READ_CONFIG:
                next_chunk_data = next_response[2:]
            else:
                next_chunk_data = next_response

            # Parse chunk header
            if len(next_chunk_data) >= 2:
                next_chunk_num = int.from_bytes(next_chunk_data[0:2], "little")
                _LOGGER.debug("Received chunk %d", next_chunk_num)

                if next_chunk_num != current_chunk:
                    _LOGGER.warning(
                        "Expected chunk %d, got chunk %d",
                        current_chunk,
                        next_chunk_num,
                    )

                # Subsequent chunks don't have total_length, just chunk_num
                tlv_data.extend(next_chunk_data[2:])
                _LOGGER.debug(
                    "Chunk %d TLV data: %d bytes (total: %d/%d)",
                    next_chunk_num,
                    len(next_chunk_data[2:]),
                    len(tlv_data),
                    total_length,
                )

            current_chunk += 1

        _LOGGER.debug("Collected %d bytes of TLV data in %d chunks", len(tlv_data), current_chunk)
        _LOGGER.debug("Complete TLV data (hex): %s", tlv_data.hex())

        # Strip OEPL config header: [length:2][version:1]
        # The firmware sends: [length:2][version:1][packets...][crc:2]
        if len(tlv_data) < 3:
            raise ConfigValidationError(f"Config data too short: {len(tlv_data)} bytes (need at least 3)")

        config_length = int.from_bytes(tlv_data[0:2], "little")
        config_version = tlv_data[2]

        _LOGGER.debug(
            "OEPL config header: length=%d bytes, version=%d",
            config_length,
            config_version,
        )

        # Extract packet data (skip 3-byte header)
        packet_data = tlv_data[3:]

        _LOGGER.debug("Packet data after stripping header: %d bytes", len(packet_data))

        # Parse complete TLV config (OEPL format: [packet_number:1][packet_id:1][fixed_data])
        try:
            full_config = parse_tlv_config(bytes(packet_data))
        except ConfigValidationError as e:
            _LOGGER.error("Failed to parse OEPL config for %s: %s", connection.mac_address, e)
            raise

        # Store for potential future use (optional - for config management features)
        self._last_config = full_config

        # Log complete configuration in human-readable format
        _LOGGER.debug(_format_config_summary(full_config, connection.mac_address))

        _LOGGER.debug(
            "OEPL device %s config: %d displays, %d LEDs, %d sensors",
            connection.mac_address,
            len(full_config.displays),
            len(full_config.leds),
            len(full_config.sensors),
        )

        # Extract and return only what Home Assistant needs right now
        return extract_display_capabilities(full_config)

    async def read_config(self, connection: "BLEConnection") -> GlobalConfig:
        """Read complete device configuration (FUTURE - for config management service).

        This is different from interrogate_device():
        - interrogate_device(): Automatic during setup, returns 4 fields
        - read_config(): Manual service call, returns everything

        Both send command 0x0040 but return different data structures.

        Args:
            connection: Active BLE connection to device

        Returns:
            GlobalConfig: Complete device configuration

        Raises:
            ConfigValidationError: If config parsing fails
        """
        response = await connection.write_command_with_response(CMD_READ_CONFIG)

        # Strip command echo (first 2 bytes are the command 0x0040 echoed back)
        if len(response) >= 2 and response[0:2] == CMD_READ_CONFIG:
            config_data = response[2:]
        else:
            config_data = response

        config = parse_tlv_config(config_data)
        self._last_config = config
        return config

    def get_last_config(self) -> GlobalConfig | None:
        """Return last read config (for potential future features).

        Returns:
            GlobalConfig: Last config read via interrogate_device() or read_config(),
                         or None if no config has been read yet
        """
        return self._last_config
