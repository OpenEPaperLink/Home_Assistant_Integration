"""TLV configuration parser for OEPL BLE firmware.

Parses the complete device configuration from 0x0040 (Read Config) response.
Based on structs.h from OEPL_BLE firmware.
"""
import struct
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from .exceptions import ConfigValidationError
from .protocol_base import DeviceCapabilities
from .color_scheme import ColorScheme
from ..const import DOMAIN

# TLV packet type constants
PACKET_TYPE_SYSTEM_CONFIG = 0x01
PACKET_TYPE_MANUFACTURER_DATA = 0x02
PACKET_TYPE_POWER_OPTION = 0x04
PACKET_TYPE_DISPLAY_CONFIG = 0x20
PACKET_TYPE_LED_CONFIG = 0x21
PACKET_TYPE_SENSOR_DATA = 0x23
PACKET_TYPE_DATA_BUS = 0x24
PACKET_TYPE_BINARY_INPUTS = 0x25


@dataclass
class SystemConfig:
    """Packet type 0x01 - System configuration (22 bytes)."""

    SIZE: ClassVar[int] = 22

    ic_type: int  # IC type: 0=nRF52840, 1=ESP32-S3
    communication_modes: int  # Supported communication modes (bitfield)
    device_flags: int  # Misc device flags (bitfield)
    pwr_pin: int  # Power pin number (0xFF = not present)
    reserved: bytes  # 17 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "SystemConfig":
        """Parse SystemConfig from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "SystemConfig", "expected": cls.SIZE, "actual": len(data)}
            )
        ic_type, comm_modes, dev_flags, pwr_pin = struct.unpack_from("<HBBB", data, 0)
        reserved = data[5:22]
        return cls(ic_type, comm_modes, dev_flags, pwr_pin, reserved)


@dataclass
class ManufacturerData:
    """Packet type 0x02 - Manufacturer information (22 bytes)."""

    SIZE: ClassVar[int] = 22

    manufacturer_id: int  # Manufacturer ID (should be 0x2446)
    board_type: int  # Board identifier
    board_revision: int  # Board revision number
    reserved: bytes  # 18 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "ManufacturerData":
        """Parse ManufacturerData from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "ManufacturerData", "expected": cls.SIZE, "actual": len(data)}
            )
        mfg_id, board_type, board_rev = struct.unpack_from("<HBB", data, 0)
        reserved = data[4:22]
        return cls(mfg_id, board_type, board_rev, reserved)


@dataclass
class PowerOption:
    """Packet type 0x04 - Power configuration (30 bytes)."""

    SIZE: ClassVar[int] = 30

    power_mode: int  # Power source type enum: 1= battery, 2=USB, 3=solar
    battery_capacity_mah: int  # Battery capacity in mAh (3 bytes)
    sleep_timeout_ms: int  # Sleep timeout in milliseconds
    tx_power: int  # Transmit power setting (signed)
    sleep_flags: int  # Sleep-related flags (bitfield)
    battery_sense_pin: int  # Battery voltage sense pin (0xFF = none)
    battery_sense_enable_pin: int  # Battery sense enable pin (0xFF = none)
    battery_sense_flags: int  # Battery sense flags (bitfield)
    capacity_estimator: int  # Battery chemistry estimator enum
    voltage_scaling_factor: int  # Voltage scaling/divider factor
    deep_sleep_current_ua: int  # Deep sleep current in microamperes
    reserved: bytes  # 12 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "PowerOption":
        """Parse PowerOption from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "PowerOption", "expected": cls.SIZE, "actual": len(data)}
            )

        # Battery capacity is 3 bytes (little-endian)
        battery_capacity = int.from_bytes(data[1:4], byteorder="little")

        (
            power_mode,
            sleep_timeout,
            tx_power,
            sleep_flags,
            bat_sense_pin,
            bat_sense_en_pin,
            bat_sense_flags,
            capacity_est,
            voltage_scale,
            deep_sleep_ua,
        ) = struct.unpack_from("<BxxxHbBBBBBHI", data, 0)

        # Calculate actual struct size: 1+3+2+1+1+1+1+1+1+2+4 = 18 bytes data + 12 reserved
        reserved = data[18:30]

        return cls(
            power_mode,
            battery_capacity,
            sleep_timeout,
            tx_power,
            sleep_flags,
            bat_sense_pin,
            bat_sense_en_pin,
            bat_sense_flags,
            capacity_est,
            voltage_scale,
            deep_sleep_ua,
            reserved,
        )


@dataclass
class DisplayConfig:
    """Packet type 0x20 - Display configuration (46 bytes, repeatable)."""

    SIZE: ClassVar[int] = 46

    instance_number: int  # Instance index (0-based)
    display_technology: int  # Display technology enum
    panel_ic_type: int  # Display controller/panel type
    pixel_width: int  # Pixel width of panel
    pixel_height: int  # Pixel height of panel
    active_width_mm: int  # Active width in millimeters
    active_height_mm: int  # Active height in millimeters
    oepl_tagtype: int  # Legacy OEPL tag type
    rotation: int  # Physical rotation in degrees
    reset_pin: int  # Panel reset pin (0xFF = none)
    busy_pin: int  # Panel busy status pin (0xFF = none)
    dc_pin: int  # Data/Command select pin (0xFF = none)
    cs_pin: int  # SPI chip select pin (0xFF = none)
    data_pin: int  # Data out pin (MOSI)
    partial_update_support: int  # Partial update capability
    color_scheme: int  # Color scheme: 0=b/w, 1=bwr, 2=bwy, 3=bwry, 4=bwgbry, 5=bw4 (black, gray, gray, white)
    transmission_modes: int  # Supported transmission modes (bitfield)
    clk_pin: int  # Clock pin
    reserved_pins: bytes  # 7 reserved pin bytes
    reserved: bytes  # 15 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "DisplayConfig":
        """Parse DisplayConfig from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "DisplayConfig", "expected": cls.SIZE, "actual": len(data)}
            )

        (
            instance_num,
            display_tech,
            panel_ic,
            pixel_w,
            pixel_h,
            active_w_mm,
            active_h_mm,
            tagtype,
            rotation,
            reset_pin,
            busy_pin,
            dc_pin,
            cs_pin,
            data_pin,
            partial_update,
            color_scheme,
            trans_modes,
            clk_pin,
        ) = struct.unpack_from("<BBHHHHHHBBBBBBBBBB", data, 0)

        reserved_pins = data[24:31]
        reserved = data[31:46]

        return cls(
            instance_num,
            display_tech,
            panel_ic,
            pixel_w,
            pixel_h,
            active_w_mm,
            active_h_mm,
            tagtype,
            rotation,
            reset_pin,
            busy_pin,
            dc_pin,
            cs_pin,
            data_pin,
            partial_update,
            color_scheme,
            trans_modes,
            clk_pin,
            reserved_pins,
            reserved,
        )


@dataclass
class LedConfig:
    """Packet type 0x21 - LED configuration (22 bytes, repeatable)."""

    SIZE: ClassVar[int] = 22

    instance_number: int  # Instance index (0-based)
    led_type: int  # LED type enum
    led_1_r: int  # Channel 1 (red) pin
    led_2_g: int  # Channel 2 (green) pin
    led_3_b: int  # Channel 3 (blue) pin
    led_4: int  # Channel 4 pin
    led_flags: int  # LED flags (bitfield)
    reserved: bytes  # 15 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "LedConfig":
        """Parse LedConfig from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "LedConfig", "expected": cls.SIZE, "actual": len(data)}
            )

        instance_num, led_type, led_1, led_2, led_3, led_4, led_flags = struct.unpack_from(
            "<BBBBBBB", data, 0
        )
        reserved = data[7:22]

        return cls(instance_num, led_type, led_1, led_2, led_3, led_4, led_flags, reserved)


@dataclass
class SensorData:
    """Packet type 0x23 - Sensor configuration (30 bytes, repeatable)."""

    SIZE: ClassVar[int] = 30

    instance_number: int  # Instance index (0-based)
    sensor_type: int  # Sensor type enum
    bus_id: int  # Instance ID of the bus to use
    reserved: bytes  # 26 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "SensorData":
        """Parse SensorData from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "SensorData", "expected": cls.SIZE, "actual": len(data)}
            )

        instance_num, sensor_type, bus_id = struct.unpack_from("<BHB", data, 0)
        reserved = data[4:30]

        return cls(instance_num, sensor_type, bus_id, reserved)


@dataclass
class DataBus:
    """Packet type 0x24 - I2C/SPI bus configuration (30 bytes, repeatable)."""

    SIZE: ClassVar[int] = 30

    instance_number: int  # Instance index (0-based)
    bus_type: int  # Bus type enum (0=I2C, 1=SPI)
    pin_1: int  # Pin 1 (SCL for I2C)
    pin_2: int  # Pin 2 (SDA for I2C)
    pin_3: int  # Pin 3 (aux)
    pin_4: int  # Pin 4 (aux)
    pin_5: int  # Pin 5 (aux)
    pin_6: int  # Pin 6 (aux)
    pin_7: int  # Pin 7 (aux)
    bus_speed_hz: int  # Bus speed in Hz
    bus_flags: int  # Bus flags (bitfield)
    pullups: int  # Internal pullup resistors (bit per pin)
    pulldowns: int  # Internal pulldown resistors (bit per pin)
    reserved: bytes  # 14 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "DataBus":
        """Parse DataBus from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "DataBus", "expected": cls.SIZE, "actual": len(data)}
            )

        (
            instance_num,
            bus_type,
            pin_1,
            pin_2,
            pin_3,
            pin_4,
            pin_5,
            pin_6,
            pin_7,
            bus_speed,
            bus_flags,
            pullups,
            pulldowns,
        ) = struct.unpack_from("<BBBBBBBBBIBBB", data, 0)

        reserved = data[16:30]

        return cls(
            instance_num,
            bus_type,
            pin_1,
            pin_2,
            pin_3,
            pin_4,
            pin_5,
            pin_6,
            pin_7,
            bus_speed,
            bus_flags,
            pullups,
            pulldowns,
            reserved,
        )


@dataclass
class BinaryInputs:
    """Packet type 0x25 - Digital input configuration (30 bytes, repeatable)."""

    SIZE: ClassVar[int] = 30

    instance_number: int  # Instance index (0-based)
    input_type: int  # Input type enum
    display_as: int  # How input should be represented
    reserved_pins: bytes  # 8 reserved pin bytes
    input_flags: int  # Input flags (bitfield)
    invert: int  # Invert flags per pin (bitfield)
    pullups: int  # Pullup resistors per pin (bitfield)
    pulldowns: int  # Pulldown resistors per pin (bitfield)
    reserved: bytes  # 15 reserved bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryInputs":
        """Parse BinaryInputs from bytes."""
        if len(data) < cls.SIZE:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_section_too_short",
                translation_placeholders={"section": "BinaryInputs", "expected": cls.SIZE, "actual": len(data)}
            )

        instance_num, input_type, display_as = struct.unpack_from("<BBB", data, 0)
        reserved_pins = data[3:11]
        input_flags, invert, pullups, pulldowns = struct.unpack_from("<BBBB", data, 11)
        reserved = data[15:30]

        return cls(
            instance_num,
            input_type,
            display_as,
            reserved_pins,
            input_flags,
            invert,
            pullups,
            pulldowns,
            reserved,
        )


@dataclass
class GlobalConfig:
    """Complete device configuration from TLV parsing."""

    magic: int
    version: int
    crc32: int
    data_length: int

    # Single-instance configs
    system: SystemConfig | None = None
    manufacturer: ManufacturerData | None = None
    power: PowerOption | None = None

    # Multi-instance configs (up to 4 each)
    displays: list[DisplayConfig] = field(default_factory=list)
    leds: list[LedConfig] = field(default_factory=list)
    sensors: list[SensorData] = field(default_factory=list)
    buses: list[DataBus] = field(default_factory=list)
    inputs: list[BinaryInputs] = field(default_factory=list)


def parse_tlv_config(data: bytes) -> GlobalConfig:
    """Parse complete TLV config from 0x0040 response.

    Auto-detects format:
    - File format: [magic:4][version:4][crc32:4][data_len:4][TLV packets...]
    - BLE format: [TLV packets...] (raw TLV data only)

    Each TLV packet:
    [type:1][length:1][data:N]

    Args:
        data: Raw config data from device

    Returns:
        GlobalConfig: Parsed configuration structure

    Raises:
        ConfigValidationError: If data is invalid or CRC check fails
    """
    if len(data) < 2:
        raise ConfigValidationError(
            translation_domain=DOMAIN,
            translation_key="tlv_data_too_short",
            translation_placeholders={ "length": str(len(data))}
        )

    # Auto-detect format by checking for magic number
    has_header = False
    if len(data) >= 16:
        potential_magic = struct.unpack_from("<I", data, 0)[0]
        if potential_magic == 0xDEADBEEF:
            has_header = True

    if has_header:
        # File format with header - parse and validate
        magic, version, crc32_expected, data_length = struct.unpack_from("<IIII", data, 0)

        # Validate CRC32 of data portion
        data_portion = data[16 : 16 + data_length]
        crc32_actual = zlib.crc32(data_portion) & 0xFFFFFFFF

        if crc32_actual != crc32_expected:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_crc_mismatch",
                translation_placeholders={
                    "expected_crc32":  f"{crc32_expected:#010x}",
                    "actual_crc32": f"{crc32_actual:#010x}"
                }
            )

        # Create config object
        config = GlobalConfig(
            magic=magic,
            version=version,
            crc32=crc32_expected,
            data_length=data_length,
        )

        # Parse TLV packets starting after header
        tlv_start = 16
        tlv_end = 16 + data_length
    else:
        # Raw TLV format (BLE protocol) - no header, no CRC validation
        config = GlobalConfig(
            magic=0,
            version=0,
            crc32=0,
            data_length=len(data),
        )

        # Parse TLV packets from start of data
        tlv_start = 0
        tlv_end = len(data)

    # Parse packets (OEPL format: [packet_number:1][packet_id:1][fixed_data])
    offset = tlv_start
    while offset < tlv_end - 2:  # -2 for potential CRC at end (if has_header is False, ignore this)
        if offset + 2 > len(data):
            break  # Not enough data for packet header

        _packet_number = data[offset]  # Packet instance number (not used in parsing)
        packet_id = data[offset + 1]
        offset += 2

        # Determine packet size based on packet ID (fixed sizes from structs.h)
        packet_size = 0
        if packet_id == PACKET_TYPE_SYSTEM_CONFIG:
            packet_size = SystemConfig.SIZE
        elif packet_id == PACKET_TYPE_MANUFACTURER_DATA:
            packet_size = ManufacturerData.SIZE
        elif packet_id == PACKET_TYPE_POWER_OPTION:
            packet_size = PowerOption.SIZE
        elif packet_id == PACKET_TYPE_DISPLAY_CONFIG:
            packet_size = DisplayConfig.SIZE
        elif packet_id == PACKET_TYPE_LED_CONFIG:
            packet_size = LedConfig.SIZE
        elif packet_id == PACKET_TYPE_SENSOR_DATA:
            packet_size = SensorData.SIZE
        elif packet_id == PACKET_TYPE_DATA_BUS:
            packet_size = DataBus.SIZE
        elif packet_id == PACKET_TYPE_BINARY_INPUTS:
            packet_size = BinaryInputs.SIZE
        else:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_unknown_packet",
                translation_placeholders={
                    "packet_id": f"{packet_id:#04x}",
                    "offset": offset - 2
                }
            )

        if offset + packet_size > len(data):
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_packet_too_short",
                translation_placeholders={
                    "packet_id": f"{packet_id:#04x}",
                    "packet_size": packet_size,
                    "remaining_bytes": len(data) - offset,
                    "offset": offset
                }
            )

        packet_data = data[offset : offset + packet_size]
        offset += packet_size

        # Parse based on packet ID
        try:
            if packet_id == PACKET_TYPE_SYSTEM_CONFIG:
                config.system = SystemConfig.from_bytes(packet_data)

            elif packet_id == PACKET_TYPE_MANUFACTURER_DATA:
                config.manufacturer = ManufacturerData.from_bytes(packet_data)

            elif packet_id == PACKET_TYPE_POWER_OPTION:
                config.power = PowerOption.from_bytes(packet_data)

            elif packet_id == PACKET_TYPE_DISPLAY_CONFIG:
                config.displays.append(DisplayConfig.from_bytes(packet_data))

            elif packet_id == PACKET_TYPE_LED_CONFIG:
                config.leds.append(LedConfig.from_bytes(packet_data))

            elif packet_id == PACKET_TYPE_SENSOR_DATA:
                config.sensors.append(SensorData.from_bytes(packet_data))

            elif packet_id == PACKET_TYPE_DATA_BUS:
                config.buses.append(DataBus.from_bytes(packet_data))

            elif packet_id == PACKET_TYPE_BINARY_INPUTS:
                config.inputs.append(BinaryInputs.from_bytes(packet_data))

            # Silently ignore unknown packet types for forward compatibility

        except Exception as e:
            raise ConfigValidationError(
                translation_domain=DOMAIN,
                translation_key="tlv_packet_parse_failed",
                translation_placeholders={
                    "packet_id": f"{packet_id:#04x}",
                    "offset": offset - 2,
                    "error": str(e)
                }
            ) from e

    return config


def _color_scheme_from_value(value: int) -> ColorScheme | None:
    """Return ColorScheme enum for value or None if unknown."""
    for scheme in ColorScheme:
        if scheme.value == value:
            return scheme
    return None


def describe_color_scheme(value: int) -> str:
    """Convert color scheme int to human-readable description."""
    scheme = _color_scheme_from_value(value)
    if scheme is None:
        return f"Unknown ({value})"

    descriptions = {
        ColorScheme.MONO: "Monochrome",
        ColorScheme.BWR: "BWR (black/white/red)",
        ColorScheme.BWY: "BWY (black/white/yellow)",
        ColorScheme.BWRY: "BWRY (black/white/red/yellow)",
        ColorScheme.BWGBRY: "BWGBRY (6-color)",
        ColorScheme.GRAYSCALE_4: "Grayscale (4-level)",
    }
    return descriptions.get(scheme, scheme.name)


def extract_display_capabilities(config: GlobalConfig) -> DeviceCapabilities:
    """Extract minimal display info from full config for interrogation.

    Used by OEPLProtocol.interrogate_device() to return only what HA needs.

    Args:
        config: Complete parsed configuration

    Returns:
        DeviceCapabilities: Minimal device information for HA setup

    Raises:
        ConfigValidationError: If no display configuration found
    """
    if not config.displays:
        raise ConfigValidationError(
            translation_domain=DOMAIN,
            translation_key="tlv_no_display_config"
        )

    # Use first display
    display = config.displays[0]

    # Swap dimensions when rotation is 90/270 (consistent with ATC wh_inverted behavior)
    if display.rotation in (90, 270):
        return DeviceCapabilities(
            width=display.pixel_height,   # Swapped for portrait rotation
            height=display.pixel_width,   # Swapped for portrait rotation
            color_scheme=display.color_scheme,
            rotatebuffer=1,
        )
    else:
        return DeviceCapabilities(
            width=display.pixel_width,
            height=display.pixel_height,
            color_scheme=display.color_scheme,
            rotatebuffer=0,
        )


def generate_model_name(display: DisplayConfig) -> str:
    """Generate human-readable model name from display configuration.

    Creates concise names based on physical dimensions and color capabilities.
    Uses diagonal size in inches calculated from millimeter dimensions.

    Examples:
        - "2.9\""  (monochrome 2.9" display)
        - "7.5\" BWR"  (7.5" color display)
        - "800x480 BWR"  (fallback when physical dimensions unavailable)

    Args:
        display: DisplayConfig with physical and pixel dimensions

    Returns:
        str: Human-readable model name

    Raises:
        ConfigValidationError: If display dimensions are invalid
    """
    import math

    # Validate pixel dimensions
    if display.pixel_width <= 0 or display.pixel_height <= 0:
        raise ConfigValidationError(
            translation_domain=DOMAIN,
            translation_key="tlv_invalid_dimensions",
            translation_placeholders={
                "width": str(display.pixel_width),
                "height": str(display.pixel_height)
            }
        )

    # Calculate diagonal size from physical dimensions (mm)
    if display.active_width_mm > 0 and display.active_height_mm > 0:
        diagonal_mm = math.sqrt(
            display.active_width_mm ** 2 + display.active_height_mm ** 2
        )
        diagonal_inches = diagonal_mm / 25.4
        size_str = f"{diagonal_inches:.1f}\""
    else:
        # Fallback if physical dimensions not available
        # Use pixel dimensions as identifier
        size_str = f"{display.pixel_width}x{display.pixel_height}"

    # Add color capability suffix
    scheme = _color_scheme_from_value(display.color_scheme)
    if scheme is None:
        color_suffix = f" color={display.color_scheme}"
    elif scheme is ColorScheme.MONO:
        color_suffix = " BW"
    else:
        color_suffix = f" {scheme.name}"

    # Build model name: "7.5\" BWR" or "800x480 BWR"
    model_name = f"{size_str}{color_suffix}"

    return model_name


def encode_tlv_config(config: GlobalConfig) -> bytes:
    """Encode GlobalConfig to TLV binary format (for future write support).

    NOT IMPLEMENTED YET - reserved for future config management features.

    Args:
        config: Configuration to encode

    Returns:
        bytes: Complete TLV config binary data

    Raises:
        NotImplementedError: This function is not yet implemented
    """
    raise NotImplementedError("Config encoding not yet implemented")


def config_to_dict(config: GlobalConfig) -> dict[str, Any]:
    """Convert GlobalConfig to JSON-serializable dictionary.

    Converts the complete OEPL configuration structure to a nested dictionary
    that can be stored in Home Assistant config entries. Bytes fields are
    converted to hex strings for serialization.

    Args:
        config: GlobalConfig instance to convert

    Returns:
        dict: JSON-serializable nested dictionary representation
    """
    def _convert_bytes(obj: Any) -> Any:
        """Recursively convert bytes objects to hex strings."""
        if isinstance(obj, bytes):
            return obj.hex()
        elif isinstance(obj, dict):
            return {k: _convert_bytes(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_convert_bytes(item) for item in obj]
        else:
            return obj

    # Convert dataclass to dict, then convert all bytes fields
    config_dict = asdict(config)
    return _convert_bytes(config_dict)
