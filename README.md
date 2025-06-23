# OpenEPaperLink integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/OpenEpaperLink/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenEpaperLink/Home_Assistant_Integration/issues)

[//]: # (Server Widget has to be enabled first)
[//]: # (![Discord]&#40;https://img.shields.io/discord/717057001594683422?style=flat-square&#41;)



Home Assistant Integration for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) project, enabling control and monitoring of electronic shelf labels (ESLs) through Home Assistant.

## Requirements

### Hardware
- OpenEPaperLink Access Point (ESP32-based)
- Compatible Electronic Shelf Labels

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

### Integration Options
After setup, you can configure additional options through the integration's option flow:

#### Tag Management
- **Blacklisted Tags**: Select tags to hide and ignore.
- **Button Debounce Time**: Adjust sensitivity of button triggers (0.0-5.0 seconds)
- **NFC Debounce Time**: Adjust sensitivity of NFC triggers (0.0-5.0 seconds)

#### Tag Discovery
Tags are automatically discovered when they check in with your AP. New tags will appear as devices with their MAC address as the identifier or alias if available. You can rename these in the device settings.

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

## Drawcustom Web Editor

A simple web-based editor is included for building `drawcustom` payloads visually.

### Running the Editor

1. Open `tools/editor/index.html` directly in a browser, or run `python app.py` and visit `http://localhost:5001/`.
2. Select a screen size preset (296x128, 154x154 or 384x168) or choose **Custom** and enter the desired width and height.
3. Click the element buttons to add drawing items. Configure colors, fonts, anchor points and other options. Service options such as background color, rotation, dithering, TTL and dry-run stay visible above the element list so they remain accessible while scrolling.
4. Use the **Zoom** selector to preview the canvas at 1x to 4x size. Scaling is
   pixel-perfect so each canvas pixel becomes a block of 2×2, 3×3 or 4×4
   pixels when zoomed.
5. Click an element in the list to select it, then drag it on the canvas to
   reposition it. Dragging accounts for the current zoom level so movement feels
   natural at any scale.
6. Choose **JavaScript** or **Python (Pyodide)** rendering using the
   **Renderer** toggle. The Python renderer uses the same drawing
   routines as the integration and automatically loads the bundled
   fonts (`ppb.ttf`, `rbm.ttf`, and Material Design Icons) when
   initialized. Debug messages are available in the optional output
   panel below the YAML field.
7. Use the buttons below the canvas to import or export YAML, or
   clear all elements. YAML changes are applied a short time after you
   stop typing to avoid errors while editing.

Rotation values of 90 or 270 degrees swap the preview width and height so the
displayed canvas matches the rotated orientation.

No build step is required; all dependencies are bundled with the repository.
The Python renderer downloads Pyodide and Pillow when first selected, so an
internet connection is required, but the renderer code itself is embedded in the
editor. The default JavaScript renderer provides a quick preview,
while the Python backend mirrors the integration's rendering logic. For an exact
result you can send the YAML to the `drawcustom` service with `dry-run: true`.

### Hosting on GitHub Pages

If the repository is stored on GitHub, you can enable GitHub Pages and view the editor online:

1. In the repository settings, enable **GitHub Pages** with the source set to the main branch.
2. Visit `https://<your-user>.github.io/<repo-name>/tools/editor/` to open the editor.

The editor is completely static so no additional build steps are required.

## Contributing
- Feature requests and bug reports are welcome! Please open an issue on GitHub
- Pull requests are encouraged
- Join the [Discord server](https://discord.com/invite/eRUHt4u5CZ) to discuss ideas and get help