# OpenEPaperLink integration for Home Assistant

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/OpenEPaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEPaperLink/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/OpenEPaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues)

Control and monitor electronic shelf labels (ESLs) running [OpenEPaperLink](https://github.com/OpenEPaperLink/OpenEPaperLink) firmware from Home Assistant: draw images on them, react to their buttons and NFC, and keep their firmware up to date.

## Requirements

- Home Assistant 2026.11 or newer.
- At least one of:
  - **An OpenEPaperLink Access Point** (ESP32-based) with tags connected to it.
  - **Bluetooth tags running the [ATC_BLE_OEPL](https://github.com/atc1441/ATC_BLE_OEPL) firmware**, reachable from a Bluetooth adapter or proxy (for example ESPHome). No Access Point is needed.

Both can be used side by side.

> **OpenDisplay users:** OpenDisplay (OEPL BLE) devices are not supported by this integration. They have their own:
> - [**Core integration**](https://www.home-assistant.io/integrations/opendisplay): send images with the `upload_image` action
> - [**Custom integration**](https://github.com/OpenDisplay/Home_Assistant_Integration): full support, including the `drawcustom` action

## Installation

### Marketplace (recommended)

OpenEPaperLink is in the Home Assistant Marketplace. Open it under **Settings → Marketplace**, search for OpenEPaperLink and select **Install**, or use this button:

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OpenEPaperLink&repository=Home_Assistant_Integration)

If you installed it through HACS before, Home Assistant moves it to the Marketplace automatically when you update to 2026.11.

### Manual

1. Download the source code of the [latest release](https://github.com/OpenEPaperLink/Home_Assistant_Integration/releases/latest).
2. Copy its `custom_components/open_epaper_link` folder into your [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations).
3. Restart Home Assistant.

## Setup

### Access Points

Access Points are discovered automatically on your network and show up under **Settings → Devices & services**. If yours is not found, for example because it is on another VLAN, add it by its address:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

Each Access Point is its own entry, so you can add as many as you have. In a mesh, each tag belongs to the Access Point it is connected to, and the other Access Points of the mesh are offered for setup once one of them is added.

If an Access Point changes its address, use **Reconfigure** on its entry.

### Bluetooth tags

Bluetooth tags are discovered automatically once they run the right firmware and have their type set:

1. **Flash the `ATC_BLE_OEPL` firmware.**
   - Tags that were used with an OpenEPaperLink BLE Access Point can usually be flashed with the [web-based OTA flasher](https://atc1441.github.io/BLE_EPaper_OTA.html).
   - Other tags usually need a wired flash. This video walks through it: [Universal E-Paper Firmware Flashing](https://youtu.be/9oKWkHGI-Yk).
2. **Set the device type.** Connect to the tag with the [ATC_BLE_OEPL Image Upload tool](https://atc1441.github.io/ATC_BLE_OEPL_Image_Upload.html), choose the tag's model under **Set Type** (for example `12: 290 Gici BWR SSD`) and select **Set Type**.

Each Bluetooth tag gets its own entry. Tags with their stock firmware are not discovered.

### Options

An Access Point's options have:

- **Hidden tags**: tags to ignore. No entities are created for them.
- **Button debounce**: ignore repeated button events within this many seconds. The Access Point repeats a wake-up reason on every check-in.
- **NFC debounce**: the same for NFC scans.

## Devices and entities

- **Access Point**: its status (state, Wi-Fi, memory, tag counts), its settings (channel, brightness, quiet hours, language and more) and a reboot button.
- **Display**: Access Points with a built-in screen have it as a part of the Access Point device, with the image it shows.
- **Tags**: each tag is a device connected through its Access Point, with its image, battery, signal, temperature, check-in times and buttons to refresh, reboot or scan for channels. The manufacturer, hardware type and firmware version are on the device page.
- **Bluetooth tags**: each is a device with its image, battery and temperature. A Bluetooth tag that is also connected to an Access Point appears in both places, and Home Assistant links the two devices.

### Events

Tags with buttons, NFC or GPIO get event entities (**Button**, **NFC**, **GPIO**) that fire when the tag wakes up for that reason. Use them as triggers in automations.

### Firmware updates

Firmware updates show up under **Settings → Updates**, like any other device's. Home Assistant checks for new releases once a day.

- **Access Point firmware**, from the repository set in the Access Point's **Update repository**.
- **Radio firmware**, for Access Points with a separate radio chip.
- **Tag firmware**, for tags with a published firmware image. Only one tag is updated at a time.
- **Bluetooth tag firmware**, sent over Bluetooth to tags set up as Bluetooth tags. Bluetooth tags that are only connected through an Access Point are not updated.

## Actions

| Action | What it does |
| --- | --- |
| `open_epaper_link.drawcustom` | Draw an image from a list of elements on one or more tags. |
| `open_epaper_link.setled` | Flash the LED on tags that have one, in up to three colour groups. |
| `open_epaper_link.force_refresh` | Make the tag redraw its current image. |
| `open_epaper_link.clear_pending` | Discard an update the tag has not collected yet. |
| `open_epaper_link.reboot_tag` | Restart the tag. |
| `open_epaper_link.scan_channels` | Make the tag search the radio channels for an Access Point again. |
| `open_epaper_link.reboot_ap` | Restart the Access Point. |
| `open_epaper_link.refresh_tag_types` | Reload the tag hardware definitions from the Access Point. |

### drawcustom

`drawcustom` builds the image from elements:

- Text with multiple fonts and styles
- Shapes (rectangles, circles, lines)
- Icons from Material Design Icons
- QR codes
- Images from URLs
- Plots of Home Assistant sensor data
- Progress bars

[Full drawcustom documentation](docs/drawcustom/supported_types.md)

#### Text

```yaml
- type: "text"
  value: "Hello World!"
  x: 10
  y: 10
  size: 40
  color: "red"
```

#### Progress bar with an icon

```yaml
- type: "progress_bar"
  x_start: 10
  y_start: 10
  x_end: 180
  y_end: 30
  progress: 75
  fill: "red"
  show_percentage: true
- type: "icon"
  value: "mdi:battery-70"
  x: 190
  y: 20
  size: 24
```

#### Sensor values

```yaml
- type: "text"
  value: "Temperature: {{ states('sensor.temperature') }}°C"
  x: 10
  y: 10
  size: 24
  color: "black"
- type: "text"
  value: "Humidity: {{ states('sensor.humidity') }}%"
  x: 10
  y: 40
  size: 24
  color: "black"
```

## Battery life

Set the Access Point's [**Shorten latency during config**](https://github.com/OpenEPaperLink/OpenEPaperLink/wiki/Tag-protocol-timing#shorten-latency-during-config) setting to `no` in its web interface. Home Assistant keeps a connection to the Access Point open, which the Access Point treats as being configured. With the setting on `yes`, tags then check in every 40 seconds instead of sleeping for their configured time, and drain their batteries.

## Contributing

- Feature requests and bug reports are welcome. Please [open an issue](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues).
- Pull requests are encouraged.
- Join the [OpenEPaperLink Discord](https://discord.com/invite/eRUHt4u5CZ) (`#home_assistant` and `#atc_ble_oepl`) to discuss ideas and get help.
