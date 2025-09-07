DOMAIN = "open_epaper_link"
SIGNAL_TAG_UPDATE = f"{DOMAIN}_tag_update"
SIGNAL_TAG_IMAGE_UPDATE = f"{DOMAIN}_tag_image_update"
SIGNAL_AP_UPDATE = f"{DOMAIN}_ap_update"

#--------------
# BLE Constants
#--------------

SERVICE_UUID = "00001337-0000-1000-8000-00805f9b34fb"  # OEPL BLE service UUID
MANUFACTURER_ID = 4919  # OEPL manufacturer ID for device discovery (0x1337)

CMD_INIT = bytes([0x01, 0x01])  # Required initialization?
CMD_GET_DISPLAY_INFO = bytes([0x00, 0x05])  # Get display information

# LED control commands
CMD_LED_ON = bytes.fromhex("000103")
CMD_LED_OFF = bytes.fromhex("000100")
CMD_LED_OFF_FINAL = bytes.fromhex("0000")

# Clock mode commands
CMD_SET_CLOCK_MODE = bytes.fromhex("000B")
CMD_DISABLE_CLOCK_MODE = bytes.fromhex("000C")
