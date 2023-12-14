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
- **fill** (required) e.g. black
- **outline** (required) e.g. red
- **width** (required) width of outline, e.g. 2

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
- value (required) name of icon from https://pictogrammers.com/library/mdi/
- size (required) e.g. 20
- color (required) e.g. black, white, red
- anchor (optional) position from the text, (see [text](#text) above for details)

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
