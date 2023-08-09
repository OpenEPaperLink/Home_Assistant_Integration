With drawcustom you can create a image in HomeAssistant and send the rendered image to a OpenEpaperLinkAP.
The basic service call, looks like this:
```
service: open_epaper_link.drawcustom
data:
  mac: 0000028DF056743A
  width: 640
  height: 384
  background: white
  rotate: 90
  payload:
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
### text
#### Parameters:
- value (required) The to show text
- x (required) position on x axis
- size (optional) size of text, default: 20
- font (optional) name of ttf file from custom_component folder. Default: ppb.ttf
- color (optional) frontcolor of text. default: black
- y (optional) position on y axis
- y_padding (optional) offset to last text or multiline y position. works only if y is not provided. default: 10
- anchor (optional) Position from the text, which shall be used as anchor. defualt: lf = left_top (mm = middle_middle) see https://pillow.readthedocs.io/en/stable/handbook/text-anchors.html

### multiline
this payload takes a string and a delimiter, and will break the string on every delimiter and move the cursor the amount if offset_y down the canvas.
#### Parameters:
- value (required) The to show text
- delimiter (required) The delimiting character, to split value. e.g.: #
- x (required) position on x axis
- size (required) size of text. e.g. 20
- font (required) name of ttf file from custom_component folder. e.g.: ppb.ttf
- color (required) frontcolor of text. e.g.: black
- start_y (optional) position on y axis
- y_padding (optional) offset to last text or multiline y position. works only if start_y is not provided. e.g.: 10

### line
Due to a bug in upstream, this isnt working. Use rectangle instead!
#### Parameters:
- x_start (required)
- y_start (required)
- x_end (required)
- y_end (required)
- color (optional) default: black

### rectangle
#### Parameters:
- x_start (required)
- y_start (required)
- x_end (required)
- y_end (required)
- fill (required) e.g. black
- outline (required) e.b. red
- width (required) width of outline e.g. 2

### icon
#### Parameters:
- value (required) name of icon. from: https://pictogrammers.com/library/mdi/
- size (required) e.g. 20
- color (required)  e.g. black, white, red
