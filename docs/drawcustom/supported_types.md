# drawcustom

With `drawcustom`, you can create an image in Home Assistant and send the rendered image to an OpenEpaperLink AP.

The basic service call, looks like this:

```yaml
service: open_epaper_link.drawcustom
target:
  entity_id:
    - open_epaper_link.0000028DF056743B
data:
  background: white
  rotate: 90
  payload:
    - type: text
      value: "Hello World!"
      font: "ppb.ttf"
      x: 0
      y: 0
      size: 40
      color: red
    - type: icon
      value: account-cowboy-hat
      x: 60
      y: 120
      size: 120
      color: red
```

## Data
### payload
Payload to draw, see below Types.

Required: true


### backgroundcolor
Background color: black, white, red

Required: true


### rotate
Rotate the whole image by 0, 90, 180, 270.

Required: false (default: 0)


### dry-run
Generate image, but don't send it to the AP.

Required: false (default: false)
```yaml
dry-run: true
```


## Types

### text

Draws text.

```yaml
- type: text
  value: "Hello World!"
  font: "/media/custom.ttf"
  x: 0
  y: 0
  size: 40
  color: red
```

#### Parameters

- **value** (required) the text to display
- **x** (required) position on x axis
- **size** (optional) size of text, default: 20
- **font** (optional) name of ttf file from `custom_components` folder. default: `ppb.ttf`. An additional font is available called `rbm.ttf`. If you want custom fonts, don't place them in the `custom_components` folder. Place them in, for example, `/media`, to not have them deleted by the next update.
- **color** (optional) font color of text. default: black
- **y** (optional) position on y axis
- **y_padding** (optional) offset to last text or multiline y position. works only if y is not provided. default: 10
- **anchor** (optional) Position from the text, which shall be used as anchor. default: `lt` (left_top). Other options include `mm` (middle_middle). See https://pillow.readthedocs.io/en/stable/handbook/text-anchors.html
- **max_width** (optional) creates line breaks in the provided text, if text is longer than `max_width` defines
- **spacing** (optional) if line breaks created in the provided text using `max_width`, set spacing between single lines. Default: 5
- **align** (optional) left, center, right default: left (this sets the alignment of any **new lines**)
- **visible** (optional) show element, default: True

### multiline

This payload takes a string and a delimiter, and will break the string on every delimiter and move the cursor the amount `offset_y` down the canvas.

```yaml
- type: multiline
  value: "adb|asd"
  delimiter: "|"
  font: "ppb.ttf"
  offset_y: 50
  x: 0
  size: 40
  color: black
  y_padding: 10
```

#### Parameters:

- **value** (required) the text to display
- **delimiter** (required) the delimiting character, to split value, e.g. `#`
- **x** (required) position on x axis
- **size** (required) size of text, e.g. 20
- **font** (required) name of ttf font file (see [text](#text) above for details)
- **color** (optional) font color of text. default: black
- **y_padding** (required) offset to last text or multiline y position. works only if `start_y` is not provided. e.g.: `10`
- **offset_y** (required) This is the line height: how much space to start the next line down the y axis.
- **start_y** (optional) position on y axis
- **align** (optional) left, center, right default: left (if text contains `\n` this sets the alignment of the lines)
- **spacing** (optional) if multiline text, spacing between single lines
- **visible** (optional) show element, default: True

### line

Draws a line.

```yaml
- type: line
  x_start: 20 
  x_end: 380
  y_start: 15
  y_end: 15
  width: 1
  fill: red
```

#### Parameters:

- **x_start** (required)
- **y_start** (optional) if `y_start` is not provided, it will automatically try to add the line at the bottom of the last text block
- **y_padding** (optional) if no `y_start` is provided, this will offset the start of the line to the last text block
- **x_end** (required)
- **y_end** (optional)
- **fill** (required)
- **width** (required)
- **visible** (optional) show element, default: True

### rectangle

Draws a rectangle.

```yaml
- type: rectangle
  x_start: 20 
  x_end: 80
  y_start: 15
  y_end: 30
  width: 2
  fill: red
  outline: black
```

#### Parameters:

- **x_start** (required)
- **y_start** (required)
- **x_end** (required)
- **y_end** (required)
- **fill** (required) e.g. black, use `null` to not draw the inside
- **outline** (required) e.g. red
- **width** (required) width of outline, e.g. 2
- **visible** (optional) show element, default: True

### icon

Draws an icon.

```yaml
- type: icon
  value: account-cowboy-hat
  x: 60
  y: 120
  size: 120
  color: red
```

#### Parameters:

- value (required) name of icon from <https://pictogrammers.com/library/mdi/>, may be optionally prefixed with "mdi:"
- size (required) e.g. 20
- color (required) e.g. black, white, red
- anchor (optional) position from the text, (see [text](#text) above for details)
- **visible** (optional) show element, default: True

### dlimg

Downloads an image from a URL and renders it.

```yaml
- type: dlimg
  url: "https://upload.wikimedia.org/wikipedia/en/9/9a/Trollface_non-free.png"
  x: 10
  y: 10
  xsize: 120
  ysize: 120
  rotate: 0
```

#### Parameters:

- **url** (required) url of the image to download
- **x** (required) e.g. 20
- **y** (required)  e.g. 10
- **xsize** (required)  e.g. x size the image is resized
- **ysize** (required)  e.g. y size the image is resized
- **rotate** (required)  e.g. 0
- **visible** (optional) show element, default: True

### qrcode

```yaml
- type: qrcode
  data: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  x: 140
  y: 50
  boxsize: 2
  border: 2
  color: "black"
  bgcolor: "white"
```

#### Parameters:

- **data** (required) content of the qr code
- **x** (required) e.g. 20
- **y** (required)  e.g. 10
- **boxsize** (required) e.g. 2
- **border** (required) e.g. 2
- **color** (required) e.g. black
- **bgcolor** (required) e.g. white
- **visible** (optional) show element, default: True

### plot

Renders the history of given home assistant entities as a line plot.
The plot will scale according to the data, so you should only use multiple entities within the same data range.

```yaml
- type: plot
  x_start: 10
  y_start: 20
  x_end: 199 # inclusive
  y_end: 119 # inclusive
  duration: 3600 # 1h in seconds
  low: 10 # if all values are larger than 10, we include 10 anyway
  high: 20 # if all values are smaller than 20, we include 20 anyway
  ylegend:
    position: right # show legend on the right
    color: red
  yaxis:
    tick_width: 4 # show very wide ticks
    grid: 3 # place a grid point every 3rd pixel
  data:
    - entity: sensor.my_room_temperature
      width: 3 # show very thick line
    - entity: sensor.my_outside_temperature
      color: red
```

#### Parameters:
- **x_start** (optional, default `0`) the left start of the whole plot (inlusive)
- **y_start** (optional, default `0`) the top start of the whole plot (inlusive)
- **x_end** (optional, default `0`) the right end of the whole plot (inlusive)
- **y_end** (optional, default `0`) the bottom end of the whole plot (inlusive)
- **duration** (optional, default `86400`) the number of seconds to look back, defaults to one day
- **font** (optional, default `ppb.ttf`) the font used for text output (may be overwritten by more specific font statements)
- **size** (optional, default `10`) the respective font size
- **low** (optional) if provided, it is ensured that the given value is included on the lower end of the plot (e.g., if values are in the range 12 to 17, providing 10 will make 10 the lower end, providing 14 changes nothing)
- **high** (optional) if provided, it is ensured that the given value is included on the upper end of the plot
- **debug** (optional, default `false`) if `true`, draw a black rectangle around the whole plot region and a red rectangle around the region with the data
- **ylegend** (optional) displays the highest and lowest value as a legend on the side, set to `null` to disable
  - **width** (optional, default `-1`) the number of pixels reserved for the legend, if `-1` it is automatically computed
  - **color** (optional, default `black`) the color for the legend
  - **position** (optional, default `left`) either `left` or `right`, the position of the legend
  - **font** / **size** (optional) the font file and size, defaults to the font selected at main level
- **yaxis** (optional) displays a vertical axis with ticks and a grid, set to `null` to disable
  - **width** (optional, default `1`) the width of the vertical axis
  - **color** (optional, default `black`) the color of the vertical axis
  - **tick_width** (optional, default `2`) the width for each axis tick, set to `0` to disable
  - **tick_every** (optional, default `1.0`) place a tick at every
  - **grid** (optional, default `5`) place a point horizontally every `grid`th pixel at the coordinates of the ticks, set to `null` to disable
  - **grid_color** (optional, default `black`) color for the grid points
- **data** (required) a list of objects for which the history should be rendered, each object has the following properties:
  - **entity** (required) the home assistant entity with has numeric data
  - **color** (optional, default `black`) the color of the plot
  - **width** (optional, default `1`) the width of the plot line
  - **joint** (optional, default `null`) sets the `joint` option for the [line draw funtion](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html#PIL.ImageDraw.ImageDraw.line), can be `curve` or `null`
- **visible** (optional) show element, default: True