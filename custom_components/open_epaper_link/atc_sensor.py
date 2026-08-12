"""Sensor descriptions for tags running ATC firmware.

Kept apart from the Access Point sensors because the two read entirely
different sources: these come from Bluetooth advertisements, those from the
Access Point's websocket.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from py_atc_ble_oepl import AdvertisingData

from .atc_coordinator import ATCCoordinator
from .entity import ATCEntity


@dataclass(frozen=True, kw_only=True)
class ATCSensorDescription(SensorEntityDescription):
    """Describes a value carried in an ATC advertisement."""

    value_fn: Callable[[AdvertisingData], float | int | str | None]


ATC_SENSORS: tuple[ATCSensorDescription, ...] = (
    ATCSensorDescription(
        key="battery_percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda adv: adv.battery_pct,
    ),
    ATCSensorDescription(
        key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda adv: adv.battery_mv or None,
    ),
    ATCSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        # Only version 2 advertisements carry a temperature.
        value_fn=lambda adv: adv.temperature,
    ),
)


class ATCSensor(ATCEntity, SensorEntity):
    """A value read from an ATC advertisement."""

    entity_description: ATCSensorDescription

    def __init__(
        self,
        coordinator: ATCCoordinator,
        entry_id: str,
        description: ATCSensorDescription,
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, entry_id, description)
        self._attr_translation_key = description.key

    @property
    def native_value(self) -> float | int | str | None:
        """Return the value from the most recent advertisement."""
        advertisement = self.advertisement
        return (
            self.entity_description.value_fn(advertisement) if advertisement else None
        )
