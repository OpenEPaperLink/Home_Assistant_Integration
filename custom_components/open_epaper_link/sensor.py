from __future__ import annotations

import datetime
import logging
from typing import Final

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER: Final = logging.getLogger(__name__)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    new_devices = [IPSensor(hub),
                   SystimeSensor(hub),
                   HeapSensor(hub),
                   RecordCountSensor(hub),
                   DBsizeSensor(hub),
                   LittlefsFreeSensor(hub),
                   APWifiRssiSensor(hub),
                   APStateSensor(hub),
                   APRunStateSensor(hub),
                   APWifiStatusSensor(hub),
                   APWifiSsidSensor(hub)]
    for esls in hub.esls:
        new_devices.append(LastSeenSensor(esls, hub))
        new_devices.append(NextUpdateSensor(esls, hub))
        new_devices.append(NextCheckinSensor(esls, hub))
        new_devices.append(PendingSensor(esls, hub))
        new_devices.append(WakeupReasonSensor(esls, hub))
        new_devices.append(CapabilitiesSensor(esls, hub))
        if (hub.data[esls]["lqi"] != 100 or hub.data[esls]["rssi"] != 100) and hub.data[esls]["hwtype"] != 224 and \
                hub.data[esls]["hwtype"] != 240:
            new_devices.append(TempSensor(esls, hub))
            new_devices.append(RssiSensor(esls, hub))
            new_devices.append(BatteryVoltageSensor(esls, hub))
            new_devices.append(BatteryPercentageSensor(esls, hub))
            new_devices.append(LqiSensor(esls, hub))
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
            "model": "esp32",
            "manufacturer": "OpenEpaperLink",
        }

    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["ip"]


class APWifiRssiSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_wifirssi"
        self._attr_name = "AP Wifi RSSI"
        self._hub = hub
        self._attr_native_unit_of_measurement = "dB"
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["rssi"]


class APStateSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_state"
        self._attr_name = "AP State"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        lut = {0: "offline", 1: "online", 2: "flashing", 3: "wait for reset", 4: "requires power cycle", 5: "failed",
               6: "coming online", 7: "no radio"}
        self._attr_native_value = lut[self._hub.data["ap"]["apstate"]]


class APRunStateSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_runstate"
        self._attr_name = "AP Run State"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        lut = {0: "stopped", 1: "pause", 2: "running", 3: "init"}
        self._attr_native_value = lut[self._hub.data["ap"]["runstate"]]


class APTempSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_aptemp"
        self._attr_name = "AP Temp"
        self._hub = hub
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        temp = self._hub.data["ap"]["temp"]
        if temp:
            self._attr_native_value = round(temp, 1)


class APWifiStatusSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_wifistate"
        self._attr_name = "AP Wifi State"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        lut = {3: "connected"}
        self._attr_native_value = lut[self._hub.data["ap"]["wifistatus"]]


class APWifiSsidSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_wifissid"
        self._attr_name = "AP Wifi SSID"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = self._hub.data["ap"]["wifissid"]


class SystimeSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_systime"
        self._attr_name = "AP Systime"
        self._hub = hub
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = datetime.datetime.fromtimestamp(self._hub.data["ap"]["systime"],
                                                                  datetime.timezone.utc)


class HeapSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_heap"
        self._attr_name = "AP free Heap"
        self._hub = hub
        self._attr_native_unit_of_measurement = "kB"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = round(int(self._hub.data["ap"]["heap"]) / 1024, 1)


class RecordCountSensor(SensorEntity):
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
        self._attr_native_unit_of_measurement = "kB"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = round(int(self._hub.data["ap"]["dbsize"]) / 1024, 1)


class LittlefsFreeSensor(SensorEntity):
    def __init__(self, hub):
        self._attr_unique_id = "ap_littlefsfree"
        self._attr_name = "AP Free Space"
        self._hub = hub
        self._attr_native_unit_of_measurement = "kB"
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "ap")}
        }

    def update(self) -> None:
        self._attr_native_value = round(int(self._hub.data["ap"]["littlefsfree"]) / 1024, 1)


class TempSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_temp"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Temperature"
        self._hub = hub
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["temperature"]


class RssiSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_rssi"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Rssi"
        self._hub = hub
        self._attr_native_unit_of_measurement = "dB"
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["rssi"]


class BatteryVoltageSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_batteryvoltage"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Battery Voltage"
        self._hub = hub
        self._attr_native_unit_of_measurement = "V"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["battery"] / 1000


class LqiSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_lqi"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Link Quality Index"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["lqi"]


class ContentModeSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_contentmode"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Content Mode"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["contentmode"]


class LastSeenSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_lastseen"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Last Seen"
        self._hub = hub
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
            "name": self._hub.data[self._esl_id]["tagname"],
            "sw_version": hex(self._hub.data[self._esl_id]["ver"]),
            "serial_number": self._esl_id,
            "model": self._hub.data[self._esl_id]["hwstring"],
            "manufacturer": "OpenEpaperLink",
            "via_device": (DOMAIN, "ap")
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = datetime.datetime.fromtimestamp(self._hub.data[esl_id]["lastseen"],
                                                                  datetime.timezone.utc)


class NextUpdateSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_nextupdate"
        self._eslid = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Next Update"
        self._hub = hub
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._eslid)},
        }

    def update(self) -> None:
        esl_id = self._eslid
        self._attr_native_value = datetime.datetime.fromtimestamp(self._hub.data[esl_id]["nextupdate"],
                                                                  datetime.timezone.utc)


class NextCheckinSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_nextcheckin"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Next Checkin"
        self._hub = hub
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = datetime.datetime.fromtimestamp(self._hub.data[esl_id]["nextcheckin"],
                                                                  datetime.timezone.utc)


class PendingSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_pending"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Pending Transfer"
        self._hub = hub
        self._attr_native_unit_of_measurement = ""
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["pending"]


class WakeupReasonSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_wakeupReason"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Wakeup Reason"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        lut = {0: "TIMED", 1: "BOOT", 2: "GPIO", 3: "NFC", 4: "BUTTON1", 5: "BUTTON2", 252: "FIRSTBOOT",
               253: "NETWORK_SCAN", 254: "WDT_RESET"}
        wr = lut[self._hub.data[esl_id]["wakeupReason"]]
        self._attr_native_value = wr


class CapabilitiesSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_capabilities"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Capabilities"
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        self._attr_native_value = self._hub.data[esl_id]["capabilities"]


class BatteryPercentageSensor(SensorEntity):
    def __init__(self, esl_id, hub):
        self._attr_unique_id = f"{esl_id}_battery"
        self._esl_id = esl_id
        self._attr_name = hub.data[esl_id]["tagname"] + " Battery"
        self._hub = hub
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._esl_id)},
        }

    def update(self) -> None:
        esl_id = self._esl_id
        battery_percentage = ((self._hub.data[esl_id]["battery"] / 1000) - 2.20) * 250
        if battery_percentage > 100:
            battery_percentage = 100
        if battery_percentage < 0:
            battery_percentage = 0
        battery_percentage = int(battery_percentage)
        self._attr_native_value = battery_percentage
