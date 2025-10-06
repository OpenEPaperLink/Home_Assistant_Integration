# OpenEPaperLink integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/issues)

[//]: # (Server Widget has to be enabled first)
[//]: # (![Discord]&#40;https://img.shields.io/discord/717057001594683422?style=flat-square&#41;)



Home Assistant Integration for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) project, enabling control and monitoring of electronic shelf labels (ESLs) through Home Assistant.

## Requirements

### Hardware

**AP-Based Setup:**
- OpenEPaperLink Access Point (ESP32-based)
- Compatible Electronic Shelf Labels connected to AP

**BLE-Based Setup:**
- BLE-compatible Electronic Shelf Labels with ATC BLE firmware
- Home Assistant with Bluetooth adapter or proxy (e.g., ESPHome)
- No separate AP required - direct device communication

**Mixed Setup:**
- Both AP and BLE devices can coexist in the same Home Assistant instance

## Features

### 🔌 Device Integration
- Each tag and AP appears as a device in Home Assistant
- Device triggers for buttons, NFC, and GPIO
- Automatic tag discovery and configuration

### ⚙️ Configuration Controls
- AP settings management (WiFi, Bluetooth, language, etc.)
- Tag inventory and blacklist management

### 🎨 Display Controls

#### drawcustom (Recommended)
The most flexible and powerful service for creating custom displays. Supports:
- Text with multiple fonts and styles
- Shapes (rectangles, circles, lines)
- Icons from Material Design Icons
- QR codes
- Images from URLs
- Plots of Home Assistant sensor data
- Progress bars

[View full drawcustom documentation](docs/drawcustom/supported_types.md)

#### Legacy Services (Deprecated)
The following services have been deprecated in favor of drawcustom:
- **dlimg**: Download and display images from URLs
- **lines5**: Display 5 lines of text (1.54" displays only)
- **lines4**: Display 4 lines of text (2.9" displays only)

These legacy services were removed in the 1.0 release. Please migrate to using drawcustom.

### 🚦 Device Management
- `clear_pending`: Clear pending updates
- `force_refresh`: Force display refresh
- `reboot_tag`: Reboot tag
- `scan_channels`: Initiate channel scan
- `reboot_ap`: Reboot the access point
- Automatic tag detection and configuration
- Support for tag blacklisting to ignore unwanted devices
- Hardware capability detection for buttons, NFC, and GPIO features

### 🔋 Battery Optimization

To maximize tag battery life when using this integration:

- **[Shorten latency during config](https://github.com/OpenEPaperLink/OpenEPaperLink/wiki/Tag-protocol-timing#shorten-latency-during-config) setting**: This setting can be set to `no` either directly on the AP's web interface or through the integration's AP device in Home Assistant.

  If set to `yes`, tags will only sleep for 40 seconds between check-ins instead of using the configured longer sleep periods, reducing battery life.

  This occurs because Home Assistant maintains a constant WebSocket connection to the AP, which the AP interprets as being in configuration mode.

## Installation

### ⚠️ Important: BLE Tag Firmware & Configuration
For the integration to discover and control BLE-based e-paper tags, they **MUST** be running the correct firmware and be properly configured. Tags with their original stock firmware will **not** be discovered by Home Assistant.

#### Step 1: Flash `ATC_BLE_OEPL` Firmware
The flashing method depends on the tag model:
- **For tags previously used with an OpenEPaperLink BLE AP:** The [web-based OTA flasher](https://atc1441.github.io/BLE_EPaper_OTA.html) can likely be used.
- **For other tags:** A manual flash is often required. This video provides a comprehensive guide: [Universal E-Paper Firmware Flashing](https://youtu.be/9oKWkHGI-Yk).

#### Step 2: Set the Device Type
After flashing, the correct device type for the tag model **must** be set.
1.  Connect to the tag using the [ATC_BLE_OEPL Image Upload tool](https://atc1441.github.io/ATC_BLE_OEPL_Image_Upload.html).
2.  Use the "Set Type" dropdown to select the specific tag model (e.g., "`12: 290 Gici BWR SSD`").
3.  Click the "Set Type" button.

#### Getting Help
For any issues, the `#atc_ble_oepl` and `#home_assistant` channel on the [OpenEPaperLink Discord](https://discord.com/invite/eRUHt4u5CZ) is a great resource for community support.

Once flashed and configured, tags are discovered by HA automatically.

### Option 1: HACS Installation (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OpenEpaperLink&repository=Home_Assistant_Integration)

### Option 2: Manual Installation
1. Download the `open_epaper_link` folder from the [latest release](https://github.com/jonasniesner/open_epaper_link_homeassistant/releases/latest)
2. Copy it to your [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations)
3. Restart Home Assistant

## Configuration

This step is only needed when using OpenEPaperLink in AP mode. When using a BLE-only setup, the tags will be detected automatically as soon as OpenEPaperLink has been installed.

### Automatic Configuration
Add OpenEPaperLink to your Home Assistant instance using this button:

[![Add Integration](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

### Manual Configuration
1. Browse to your Home Assistant instance
2. Go to Settings → Devices & Services
3. Click the `Add Integration` button in the bottom right
4. Search for and select "OpenEPaperLink"
5. Follow the on-screen instructions

### Integration Options
After setup, you can configure additional options through the integration's option flow:

#### Tag Management
- **Blacklisted Tags**: Select tags to hide and ignore.
- **Button Debounce Time**: Adjust sensitivity of button triggers (0.0-5.0 seconds)
- **NFC Debounce Time**: Adjust sensitivity of NFC triggers (0.0-5.0 seconds)

#### Device Discovery

**AP Device Configuration:**
- Manual setup required via Settings → Integrations → Add Integration
- Enter your AP's IP address when prompted
- ⚠️ **Single Hub Limitation**: Only one AP hub allowed per Home Assistant instance
- All tags connected to the AP are automatically discovered

**BLE Device Discovery:**
- Automatic discovery via Bluetooth scanning
- Devices appear when in range and advertising
- Each BLE device creates a separate integration entry
- No limit on number of BLE devices

## Usage Examples

### Basic Text Display
```yaml
- type: "text"
  value: "Hello World!"
  x: 10
  y: 10
  size: 40
  color: "red"
```

### Progress Bar with Icon
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

### Sensor Display
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
## Migrating to Version 1.0

### Breaking Changes

1. **Service Changes**
   - `dlimg`, `lines4`, and `lines5` services have been deprecated
   - All image/text display should now use `drawcustom` service
   - Service target now uses device ID instead of entity ID
2. **Entity Changes**
    - Entities for each device have also changed significantly

**To make sure no potential bugs carry over from the old version, please remove the old integration and re-add it. This will ensure that all entities are correctly setup.**



### Service Migration

#### Text Display
Old format (`lines5` service):
```yaml
line1: "Hello"
line2: "World"
```

New format (`drawcustom` payload):
```yaml
- type: "text"
  value: "Hello"
  x: 10
  y: 10
  size: 24
- type: "text"
  value: "World"
  x: 10
  y: 40
  size: 24
```

#### Image Display
Old format (`dlimg` service):
```yaml
url: "https://example.com/image.jpg"
x: 0
y: 0
xsize: 296
ysize: 128
```

New format (`drawcustom` payload):
```yaml
- type: "dlimg"
  url: "https://example.com/image.jpg"
  x: 0
  y: 0
  xsize: 296
  ysize: 128
```

The device selection, background color, rotation, and other options are now configured through dropdown menus in the service UI.

## Contributing
- Feature requests and bug reports are welcome! Please open an issue on GitHub
- Pull requests are encouraged
- Join the [Discord server](https://discord.com/invite/eRUHt4u5CZ) to discuss ideas and get help
