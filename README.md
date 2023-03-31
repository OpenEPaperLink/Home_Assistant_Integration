# OpenEPaperLink integration for Home Assistant
<h1>This project is work in Progress</h1>
Home assistant Integration for the <a href="https://github.com/jjwbruijn/OpenEPaperLink">OpenEPaperLink</a> project

## Installation

### If you use [HACS](https://hacs.xyz/):

1. Click on HACS in the Home Assistant menu
2. Click on the 3 dots in the top right corner.
3. Select "Custom repositories"
4. Add the URL to the repository.
5. Select the Integration category.
6. Click the "ADD" button.

7. Click on HACS in the Home Assistant menu
8. Click on `Integrations`
9. Click the `EXPLORE & DOWNLOAD REPOSITORIES` button
10. Search for `OpenEPaperLink`
11. Click the `DOWNLOAD` button
12. Restart Home Assistant

### Manually:

1. Copy `open_epaper_link` folder from [latest release](https://github.com/jonasniesner/open_epaper_link_homeassistant/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations). in your config folder.
2. Restart Home Assistant

## Configuration

Adding OpenEPaperLink to your Home Assistant instance can be done via the user interface, by using this My button:

[![image](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

### Manual configuration steps
If the above My button doesn’t work, you can also perform the following steps manually:

* Browse to your Home Assistant instance.
* In the sidebar click on  Settings.
* From the configuration menu select: Devices & Services.
* In the bottom right, click on the  Add Integration button.
* From the list, search and select “OpenEPaperLink”.
* Follow the instruction on screen to complete the set up.
