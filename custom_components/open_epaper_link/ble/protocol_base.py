"""Base protocol abstraction for BLE firmware types."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import BLEConnection


@dataclass
class AdvertisingData:
    """Parsed BLE advertising data."""

    battery_mv: int
    battery_pct: int
    temperature: int | None
    hw_type: int
    fw_version: int
    version: int  # Config/protocol version


@dataclass
class DeviceCapabilities:
    """Minimal device information needed for Home Assistant setup."""

    width: int
    height: int
    color_scheme: int  # 0=MONO, 1=BWR, 2=BWY, 3=BWRY, 4=BWGBRY, 5=GRAYSCALE
    rotatebuffer: int


class BLEProtocol(ABC):
    """Abstract base class for BLE firmware protocols.

    Each firmware type (ATC, OEPL) implements this interface to provide
    protocol-specific behavior while sharing common infrastructure.
    """

    @staticmethod
    def _calculate_battery_percentage(voltage_mv: int) -> int:
        """Convert battery voltage (mV) to percentage estimate.

        Args:
            voltage_mv: Battery voltage in millivolts

        Returns:
            int: Battery percentage (0-100)
        """
        if voltage_mv == 0:
            return 0  # Unknown battery level

        voltage = voltage_mv / 1000.0
        min_voltage, max_voltage = 2.6, 3.2  # Battery voltage range
        percentage = min(
            100, max(0, int((voltage - min_voltage) * 100 / (max_voltage - min_voltage)))
        )
        return percentage

    @property
    @abstractmethod
    def manufacturer_id(self) -> int:
        """Bluetooth manufacturer ID for device discovery."""

    @property
    @abstractmethod
    def service_uuid(self) -> str:
        """BLE GATT service UUID for communication."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Protocol identifier: 'atc' or 'oepl'."""

    @abstractmethod
    def parse_advertising_data(self, data: bytes) -> AdvertisingData:
        """Parse manufacturer-specific advertising data.

        Args:
            data: Raw manufacturer-specific data from BLE advertisement

        Returns:
            AdvertisingData: Parsed advertising information

        Raises:
            ValueError: If data format is invalid
        """

    @abstractmethod
    async def interrogate_device(
        self, connection: "BLEConnection"
    ) -> DeviceCapabilities:
        """Query device capabilities during setup.

        Returns minimal information needed for Home Assistant entity creation.

        For OEPL: Reads full config via 0x0040, extracts display dimensions.
        For ATC: Uses legacy 0x0005 command.

        Args:
            connection: Active BLE connection to device

        Returns:
            DeviceCapabilities: Minimal device information

        Raises:
            BLEError: If interrogation fails
            ConfigValidationError: If device returns invalid data
        """

    async def initialize_connection(self, connection: "BLEConnection") -> None:
        """Perform protocol-specific connection initialization.

        Called after BLE connection is established and notifications are enabled.
        Protocols can override this to send initialization commands if needed.

        Args:
            connection: Active BLE connection

        Default implementation does nothing - protocols requiring initialization
        should override this method.
        """
        pass  # Default: no initialization needed
