"""Constants for the OpenEPaperLink integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "open_epaper_link"

# Config entry data / options keys
CONF_HOST: Final = "host"
CONF_AP_MAC: Final = "ap_mac"
CONF_DEVICE_TYPE: Final = "device_type"
DEVICE_TYPE_AP: Final = "ap"

# Tags reached over Bluetooth run ATC firmware. "BLE" names the radio; ATC
# names the device and its protocol, and matches py-atc-ble-oepl. It used to be
# one of two Bluetooth protocols, which is why the old entries carried both a
# device_type of "ble" and a separate protocol_type; the other protocol was
# removed in 3.0.0, so a single discriminator now suffices.
DEVICE_TYPE_ATC: Final = "atc"
LEGACY_DEVICE_TYPE_ATC: Final = "ble"

OPT_BLACKLISTED_TAGS: Final = "blacklisted_tags"
OPT_BUTTON_DEBOUNCE: Final = "button_debounce"
OPT_NFC_DEBOUNCE: Final = "nfc_debounce"
OPT_CUSTOM_FONT_DIRS: Final = "custom_font_dirs"

DEFAULT_BUTTON_DEBOUNCE: Final = 0.5
DEFAULT_NFC_DEBOUNCE: Final = 1.0

# Bus event fired for tag interactions; consumed by device_trigger.
EVENT_TAG_INTERACTION: Final = f"{DOMAIN}_event"

# Dispatcher signal fired when any config entry loads or unloads, so sibling
# entries can re-evaluate which of them owns each mesh tag.
SIGNAL_ENTRIES_CHANGED: Final = f"{DOMAIN}_entries_changed"

# Sensor keys removed in the rewrite. These were derived by the integration
# from what it happened to observe, so they undercounted after any restart or
# WebSocket drop. The AP's own updatecount/updatelast are authoritative and
# replace them. migration.py removes the orphaned entities.
REMOVED_SENSOR_KEYS: Final = frozenset(
    {"runtime", "boot_count", "checkin_count", "block_requests"}
)
