# OpenEPaperLink integration for Home Assistant

Home Assistant Integration for the <a href="https://github.com/jjwbruijn/OpenEPaperLink">OpenEPaperLink</a> project

Feature Request and code contributions are welcome!

## Functionality

### Sensors

Every sensor of the tags is exposed in Home Assistant.
Every tag and the AP is exposed as a device.

### Services

#### drawcustom
This Service call draws a image local in home assistant, and will send it to the EPaper AP afterwards. Note that the rectangle is not transparent, so if it is drawn after other objects, it may overwrite them.

Example Call:
```
service: open_epaper_link.drawcustom
target:
  entity_id:
    - open_epaper_link.0000021EC9EC743A
data:
  background: white
  rotate: 270
  ttl: 300
  payload:
    - type: rectangle
      outline: red
      fill: white
      width: 5
      x_start: 10
      y_start: 10
      x_end: 185
      y_end: 240   
    - type: line
      fill: red
      width: 3
      x_start: 0
      y_start: 237
      x_end: 196
      y_end: 240  
    - type: text
      value: "Hello World!"
      font: "ppb.ttf"
      x: 0
      "y": 0
      size: 40
      color: red
    - type: icon
      value: account-cowboy-hat
      x: 60
      y: 120
      size: 120
      color: red
```

Supported payload types, see [drawcustom payload types](docs/drawcustom/supported_types.md)

#### Download Image (deprecated, use drawcustom for more options)

Download an image from the provided url and if required, resized it for the esl it should be displayed on.

This requires that the esl has checked in once before fo Home Assistant knows the hardware type of it so if this service fail, wait 10 to 20 minutes.

#### 5 Line Display (deprecated, use drawcustom for more options)

Displays 5 (or up to 10) lines of text on a small 1.54" esl. If a text line contains a newline (\n), it will be split in 2 lines.
Only works on 1.54" M2 displays.

#### 4 Line Display (deprecated, use drawcustom for more options)

Displays 4 (or up to 8) lines of text on a 2.9" esl. If a text line contains a newline, it will be split in 2 lines.
Only works on 2.9" M2 displays.

#### Example Service Call
Go to Developer Tools, Services, select the OpenEPaperLink: 4 Line Display service and paste the below in to the YAML editor. Replace the sensor names in curly brackets with values from your own system. Note that floats work better when rounded and that all numbers work better when converted to strings.

```
service: open_epaper_link.lines4
target:
  entity_id:
    - open_epaper_link.0000021EDE313B15
data:
  line1: " Time: {{ states('sensor.time') | string }} " 
  line2: " LR Temp: {{ state_attr('climate.living_room_2','current_temperature') | string }} C " 
  line3: " Yest. Elec {{ state_attr('sensor.electricity_yesterday_previous_accumulative_consumption','total') | round(2) | string }} kWh " 
  line4: "Car: {{ states('sensor.car_state_of_charge') | int | string }} % / {{ ((states('sensor.id_3_pro_performance_range')) | float / 1.609344) | int | string }} miles  {{ states('sensor.bins') }}  " 
  border: r 
  format1: mbbw 
  format2: mrbw 
  format3: lbrw 
  format4: mwrb
```

If a template with a numeric sensor value still does not work, try appending a non-numeric string (can't be a blank string or just a space) e.g.
```
" {{  (states('sensor.car_range') | float / 1.609344 ) | int }} mi "
```

## Installation

### If you use [HACS](https://hacs.xyz/):

1. Click on HACS in the Home Assistant menu
2. Click on the 3 dots in the top right corner
3. Select "Custom repositories"
4. Add the URL to the repository
5. Select the Integration category
6. Click the "ADD" button

7. Click on HACS in the Home Assistant menu
8. Click on `Integrations`
9. Click the `EXPLORE & DOWNLOAD REPOSITORIES` button
10. Search for `OpenEPaperLink`
11. Click the `DOWNLOAD` button
12. Restart Home Assistant

### Manually:

1. Copy `open_epaper_link` folder from [latest release](https://github.com/jonasniesner/open_epaper_link_homeassistant/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config folder
2. Restart Home Assistant

## Configuration

Adding OpenEPaperLink to your Home Assistant instance can be done via the user interface, by using this My button:

[![image](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

### Manual configuration steps
If the above My button doesn’t work, you can also perform the following steps manually:

1. Browse to your Home Assistant instance
2. In the sidebar click on  Settings
3. From the configuration menu select: Devices & Services
4. In the bottom right, click on the `Add Integration` button
5. From the list, search and select “OpenEPaperLink”
6. Follow the instructions on screen to complete the setup


