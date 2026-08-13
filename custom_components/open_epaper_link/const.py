"""Constants for the OpenEPaperLink integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "open_epaper_link"

# Config entry data / options keys
CONF_HOST: Final = "host"
CONF_AP_MAC: Final = "ap_mac"
CONF_MAC_ADDRESS: Final = "mac_address"
# Obsolete entry-data keys, stripped by migration. An AP entry has a host and
# an ATC entry does not, which already distinguishes them, and after setup the
# runtime data type does so with real type information.
CONF_DEVICE_TYPE: Final = "device_type"

OPT_BLACKLISTED_TAGS: Final = "blacklisted_tags"
OPT_BUTTON_DEBOUNCE: Final = "button_debounce"
OPT_NFC_DEBOUNCE: Final = "nfc_debounce"
# Semicolon-separated extra font directories for drawcustom.
OPT_CUSTOM_FONT_DIRS: Final = "custom_font_dirs"

DEFAULT_BUTTON_DEBOUNCE: Final = 0.5
DEFAULT_NFC_DEBOUNCE: Final = 1.0

# Dispatched when a tag reports a button, NFC or GPIO wake-up. Consumed by the
# event platform. The pre-4.0 integration fired a custom bus event for device
# triggers instead; event entities replace both.
SIGNAL_TAG_INTERACTION: Final = f"{DOMAIN}_tag_interaction"

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

# Battery percentage scale. Full is the point the M2 family stops measuring:
# it reports exactly 2600 mV when full or better, and the Access Point's own
# web interface renders that as "at least 2.6 V".
#
# This is knowingly approximate on other hardware, which reports true voltage
# past 3100 mV, so a nearly flat M3 reads higher than it should. Scaling per
# tag needs a measurement range that nothing publishes: the firmware only
# forwards batteryMv, the tag types do not describe it, and learning it from
# observation would make the reading depend on what this Home Assistant
# instance happened to see. Use battery_low, which comes from the firmware's
# own threshold, when the answer has to be right.
BATTERY_EMPTY_MV: Final = 2200
BATTERY_FULL_MV: Final = 2600
