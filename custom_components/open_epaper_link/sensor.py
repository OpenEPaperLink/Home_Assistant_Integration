"""Platform for sensor integration."""
from __future__ import annotations
from .const import DOMAIN
import logging
_LOGGER: Final = logging.getLogger(__name__)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import TEMP_CELSIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    new_devices = []
    new_devices.append(IPSensor(hub))
    new_devices.append(SystimeSensor(hub))
    new_devices.append(HeapSensor(hub))
    new_devices.append(RecordcountSensor(hub))
    new_devices.append(DBsizeSensor(hub))
    new_devices.append(LitefsfreeSensor(hub))
    for esls in hub.esls:
        new_devices.append(TempSensor(esls,hub))
        new_devices.append(RssiSensor(esls,hub))
        new_devices.append(BatteryVoltageSensor(esls,hub))
        new_devices.append(BatteryPercentageSensor(esls,hub))
        new_devices.append(LqiSensor(esls,hub))
        new_devices.append(ContentModeSensor(esls,hub))
        new_devices.append(LastSeenSensor(esls,hub))
        new_devices.append(NextUpdateSensor(esls,hub))
        new_devices.append(NextCheckinSensor(esls,hub))
        new_devices.append(PendingSensor(esls,hub))
        new_devices.append(HWTypeSensor(esls,hub))
        new_devices.append(AliasSensor(esls,hub))
        new_devices.append(WakeupReasonSensor(esls,hub))
        new_devices.append(CapabilitiesSensor(esls,hub))
        new_devices.append(HashSensor(esls,hub))
    async_add_entities(new_devices)

class IPSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_ip"
        self._attr_name = "AP IP"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")},
            "configuration_url": "http://" + self._hub.data["ap"]["ip"],
            "name": "OpenEpaperLink AP",
            "sw_version": "unknown",
            "model": "esp32",
            "manufacturer": "OpenEpaperLink",
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["ip"]
      
class SystimeSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_systime"
        self._attr_name = "AP Systime"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["systime"]
        
class HeapSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_heap"
        self._attr_name = "AP Heap"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["heap"]

class RecordcountSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_recordcount"
        self._attr_name = "AP Recordcount"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["recordcount"]
        
class DBsizeSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_dbsize"
        self._attr_name = "AP DBSize"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["dbsize"]
        
class LitefsfreeSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_littlefsfree"
        self._attr_name = "AP Free Space"
        self._hub = hub
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }
    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["littlefsfree"]

class TempSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_temp"
        self._eslid = esls
        self._attr_name = f"{esls} Temperature"
        self._hub = hub
        self._attr_native_unit_of_measurement = TEMP_CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
            "name": self._eslid,
            "sw_version": "unknown",
            "model": self._hub.data[self._eslid]["hwstring"],
            "manufacturer": "OpenEpaperLink",
            "via_device": (DOMAIN, "ap")
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["temperature"]

class RssiSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_rssi"
        self._eslid = esls
        self._attr_name = f"{esls} Rssi"
        self._hub = hub
        self._attr_native_unit_of_measurement = "dB"
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["rssi"]
        
class BatteryVoltageSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_batteryvoltage"
        self._eslid = esls
        self._attr_name = f"{esls} Battery Voltage"
        self._hub = hub
        self._attr_native_unit_of_measurement = "V"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["battery"] / 1000
        
class LqiSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_lqi"
        self._eslid = esls
        self._attr_name = f"{esls} Link Quality Index"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["lqi"]
        
class ContentModeSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_contentmode"
        self._eslid = esls
        self._attr_name = f"{esls} Content Mode"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["contentmode"]
        
class LastSeenSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_lastseen"
        self._eslid = esls
        self._attr_name = f"{esls} Last Seen"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["lastseen"]

class NextUpdateSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_nextupdate"
        self._eslid = esls
        self._attr_name = f"{esls} Next Update"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["nextupdate"]

class NextCheckinSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_nextcheckin"
        self._eslid = esls
        self._attr_name = f"{esls} Next Checkin"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["nextcheckin"]

class PendingSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_pending"
        self._eslid = esls
        self._attr_name = f"{esls} Pending Transfer"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["pending"]
        
class AliasSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_alias"
        self._eslid = esls
        self._attr_name = f"{esls} Alias"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["alias"]
        
class WakeupReasonSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_wakeupReason"
        self._eslid = esls
        self._attr_name = f"{esls} Wakeup Reason"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["wakeupReason"]
        
class CapabilitiesSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_capabilities"
        self._eslid = esls
        self._attr_name = f"{esls} Capabilities"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["capabilities"]
    
class HashSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_hashv"
        self._eslid = esls
        self._attr_name = f"{esls} Hash"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["hashv"]
        
class HWTypeSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_hwtype"
        self._eslid = esls
        self._attr_name = f"{esls} Hardware Type"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        self._attr_native_value = self._hub.data[eslid]["hwtype"]
        
class BatteryPercentageSensor(SensorEntity):
    def __init__(self, esls,hub):
        self._attr_unique_id = f"{esls}_battery"
        self._eslid = esls
        self._attr_name = f"{esls} Battery"
        self._hub = hub
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }
    def update(self) -> None:
        eslid = self._eslid
        bperc = ((self._hub.data[eslid]["battery"] / 1000) - 2.30) * 200
        if bperc > 100:
            bperc = 100
        if bperc < 0:
            bperc = 0
        bperc = int(bperc)
        self._attr_native_value = bperc
