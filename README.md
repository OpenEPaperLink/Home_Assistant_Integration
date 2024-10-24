# OpenEPaperLink integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/issues)

[//]: # (Server Widget has to be enabled first)
[//]: # (![Discord]&#40;https://img.shields.io/discord/717057001594683422?style=flat-square&#41;)



Home Assistant Integration for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) project, enabling control and monitoring of electronic shelf labels (ESLs) through Home Assistant.

## Features

### 🔌 Entities and Devices
- Each tag and AP is exposed as a device in Home Assistant
- Sensor data for each tag:
    - Temperature
    - Battery voltage and percentage
    - Signal strength (RSSI)
    - Link Quality Index (LQI)
    - Last seen timestamp
    - Next update/checkin time
    - Wakeup reason
    - Device capabilities
- Sensor data for each AP:
    - DBSize
    - Free heap
    - Free space
    - IP address
    - Recordcount
    - Run state
    - AP state
    - Systime
    - Temperature
    - Wi-Fi RSSI
    - Wi-Fi SSID
    - Wi-Fi state

### ⚙️ AP Configuration Options
- Alias
- Bluetooth
- IEEE 802.15.4 channel selection
- Language selection
- Lock tag inventory setting
- Maximum sleep duration settings
- No-updates time window configuration
- AP Image preview setting
- RGB LED brightness control
- TFT brightness control
- Time zone configuration
- Wi-Fi power settings

### 🎨 Display Controls
Several services for controlling the display content:

#### drawcustom (Recommended)
The most flexible and powerful service for creating custom displays. Supports:
- Text with multiple fonts and styles
- Shapes (rectangles, circles, lines)
- Icons from Material Design Icons
- QR codes
- Images from URLs
- Plots of Home Assistant sensor data
- Progress bars

[View full drawcustom documentation →](docs/drawcustom/supported_types.md)

#### Legacy Services (Deprecated)
- **dlimg**: Download and display images from URLs
- **lines5**: Display 5 lines of text (1.54" displays only)
- **lines4**: Display 4 lines of text (2.9" displays only)

### 🚦 Device Management
Services for managing ESL devices:
- `clear_pending`: Clear pending updates
- `force_refresh`: Force display refresh
- `reboot_tag`: Reboot tag
- `scan_channels`: Initiate channel scan
- `reboot_ap`: Reboot the access point

## Installation

### Option 1: HACS Installation (Recommended)
1. Click on HACS in the Home Assistant menu
2. Click `Integrations`
3. Click the `EXPLORE & DOWNLOAD REPOSITORIES` button
4. Search for `OpenEPaperLink`
5. Click the `DOWNLOAD` button
6. Restart Home Assistant

### Option 2: Manual Installation
1. Download the `open_epaper_link` folder from the [latest release](https://github.com/jonasniesner/open_epaper_link_homeassistant/releases/latest)
2. Copy it to your [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations)
3. Restart Home Assistant

## Configuration

### Automatic Configuration
Add OpenEPaperLink to your Home Assistant instance using this button:

[![Add Integration](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

### Manual Configuration
1. Browse to your Home Assistant instance
2. Go to Settings → Devices & Services
3. Click the `Add Integration` button in the bottom right
4. Search for and select "OpenEPaperLink"
5. Follow the on-screen instructions

## Usage Examples

### Basic Custom Display
```yaml
service: open_epaper_link.drawcustom
target:
  entity_id: open_epaper_link.0000021EC9EC743A
data:
  background: white
  rotate: 0
  payload:
    - type: text
      value: "Hello World!"
      font: "ppb.ttf"
      x: 10
      y: 10
      size: 40
      color: red
```

### Progress Bar with Icon
```yaml
service: open_epaper_link.drawcustom
target:
  entity_id: open_epaper_link.0000021EC9EC743A
data:
  background: white
  payload:
    - type: progress_bar
      x_start: 10
      y_start: 10
      x_end: 180
      y_end: 30
      progress: 75
      fill: red
      show_percentage: true
    - type: icon
      value: mdi:battery-70
      x: 190
      y: 20
      size: 24
```

If a template with a numeric sensor value still does not work, try appending a non-numeric string (can't be a blank string or just a space) e.g.
```
" {{  (states('sensor.car_range') | float / 1.609344 ) | int }} mi "
```

## Contributing
- Feature requests and bug reports are welcome! Please open an issue on GitHub
- Pull requests are encouraged
- Join the [Discord server](https://discord.com/invite/eRUHt4u5CZ) to discuss ideas and get help