# drawcustom

With `drawcustom`, you can create an image in Home Assistant and send the rendered image to an OpenEpaperLink AP.

## List of draw types
- [Debug Grid](#debug_grid)
- [Text](#text)
- [Multiline Text](#multiline-text)
- [Line](#line)
- [Rectangle](#rectangle)
- [Rectangle Pattern](#rectangle-pattern)
- [Polygon](#polygon)
- [Circle](#circle)
- [Ellipse](#ellipse)
- [Arc/ Pie Slice](#arc-pie-slice)
- [Icon](#icon)
- [Icon Sequence](#icon-sequence)
- [Download Image](#download-image)
- [QR Code](#qr-code)
- [Plot](#plot)
- [Progress Bar](#progress-bar)
- [Template Examples](#template-examples)

## Basic Usage

ESLs come in multiple variants - red and yellow are the most common accent colors. The following options are available:

The payload is a list of drawing elements that define what to display. Each element must specify its type and required properties. The elements are drawn in order from first to last.

Example payload:
```yaml
- type: text
  value: Hello World!
  font: ppb.ttf
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

### Service Options

| Option       | Description                     | Default |
|--------------|---------------------------------|---------|
| `payload`    | List of drawing elements (YAML) | -       |
| `background` | Background color                | white   |
| `rotate`     | Rotation of image               | 0       |
| `dither`     | Dithering (see table below)     | 2       |
| `ttl`        | Cache time in seconds           | 60      |
| `dry-run`    | Generate without sending        | false   |

| Dither | Description                                           |
|--------|-------------------------------------------------------|
| `0`    | No dithering                                          |
| `1`    | Floyd-Steinberg dithering (best for photos)           |
| `2`    | Ordered dithering (default, best for halftone colors) |


# Color Support

ESLs predominantly come in two variants: red and yellow accent colors (tags with more also exist). You can specify colors in several ways:

- Using explicit colors: `"black"`, `"white"`, `"red"`, `"yellow"`
- Using halftone colors (set `dither=2`): `"half_black"` (or `"gray"`, `"grey"`, `"half_white"`), `"half_red"`, `"half_yellow"`
- Using single letter shortcuts: `"b"` (black), `"w"` (white), `"r"` (red), `"y"` (yellow)
- Using halftone shortcuts: `"hb"`, `"hw"` (50% black/gray), `"hr"` (50% red), `"hy"` (50% yellow)
- Using `"accent"`, `"a"`, `"half_accent"`, or `"ha"` to automatically use the tag's accent color (red or yellow depending on the hardware)
- Using hex colors: `"#RGB"` or `"#RRGGBB"` (e.g., `"#F00"` or `"#FF0000"` for red)

Example payload adapting to tag color:
```yaml
- type: text
  value: Hello World!
  font: ppb.ttf
  x: 0
  y: 0
  size: 40
  color: accent  # Will be red or yellow depending on the tag
```

## Color Support by Element Type

All elements that support colors (text, shapes, icons, etc.) accept the following color properties:

| Property     | Description                        | Values                                                      |
|--------------|------------------------------------|-------------------------------------------------------------|
| `color`      | Primary color                      | `white`, `black`, `accent`, `red`, `yellow`, `#RRGGBB`      |
| `fill`       | Fill color                         | `white`, `black`, `accent`, `red`, `yellow`, `#RRGGBB`      |
| `outline`    | Outline/border color               | `white`, `black`, `accent`, `red`, `yellow`, `#RRGGBB`      |
| `background` | Background color (when applicable) | `white`, `black`, `accent`, `red`, `yellow`, `#RRGGBB`      |

Using `"accent"` is recommended for portable scripts that should work with both red and yellow tags.

# Font support

Custom fonts are supported for text elements. The integration provides several ways to specify fonts:

### Specifying fonts

```yaml
# Using the default font (ppb.ttf)
- type: text
  value: Default font
  font: ppb.ttf # Optional, you can also omit this line
  x: 10
  y: 10
  
# Using just the filename (searched in all font directories)
- type: text
  value: "Custom Font"
  font: "CustomFont.ttf"
  x: 10
  y: 50

# Using the absolute path (direct access)
- type: text
  value: "Custom Font with Path"
  font: "/media/GothamBold-Rnd.ttf"
  x: 10
  y: 90
```

### Font locations

The integration searches for fonts in these locations in order:

1. **Custom font directories** (configured in the integration options)
2. **Integration assets directory** (`custom_components/open_epaper_link/imagegen/assets`) - contains default fonts (`ppb.ttf`, `rbm.ttf`)
3. **Web directory** - (`/config/www/fonts/`)
4. **Media directory** - (`/media/fonts/`)

> **Note:** The `/config/www/fonts/` and `/media/fonts/` directories do not exist by default. You'll need to create them if you want to use them.

#### Setting Up Font Directories

To create the standard font directories:

```bash
# Create the www/fonts directory
mkdir -p /config/www/fonts

# Create the media/fonts directory
mkdir -p /media/fonts
```

You can access these directories:
- Through the Home Assistant File Editor or the VSCode Addon by navigating to `/config/www/fonts/`
- Via SFTP/SSH if you have direct access to your Home Assistant server
- Through Samba shares if configured

### Default fonts

The integration provides two default fonts:
- `ppb.ttf`
- `rbm.ttf`

These are always available and will be used as fallbacks if specified fonts cannot be found.

### Configuring custom font directories

You can add custom font directories in the integrations configuration:

1. Go to **Settings** → **Devices & Services**
2. Find the OpenEPaperLink integration and click **Configure**
3. Enter custom font directories, separated by semicolons (must be absolute paths)
   ```
   /config/custom/fonts;/usr/share/fonts;/home/homeassistant/fonts
   ```
4. Click **Submit**

### Font not found

If a font can't be found, the integration:
1. Logs a warning message
2. Falls back to the default `ppb.ttf` font

Check the Home Assistant logs for messages like:
```
Font 'myfont.ttf' not found in any of the standard locations.
Place fonts in /config/www/fonts/ or /media/fonts/ or provide absolute path.
Falling back to default font.
```

## Types

### debug_grid
The `debug_grid` draw type overlays a grid on the image canvas to help with layout debugging.

```yaml
- type: debug_grid
```
| Parameter         | Description                                | Required | Default            | Notes               |
|-------------------|--------------------------------------------|----------|--------------------|---------------------|
| `spacing`         | Distance between grid lines                | No       | `20`               | Pixels              |
| `line_color`      | Color of the grid lines                    | No       | `black`            | Any supported color |
| `dashed`          | Whether to use dashed lines for the grid   | No       | `True`             | `True`, `False`     |
| `dash_length`     | Length of dash segments (if dashed)        | No       | `2`                | Pixels              |
| `space_length`    | Space between the dashes (if dashed)       | No       | `4`                | Pixels              |
| `show_labels`     | Whether to label coordinates at grid lines | No       | `True`             | `True`, `False`     |
| `label_step`      | Frequency of labels (every Nth) grid line  | No       | `40` (2*`spacing`) | Pixels              |
| `label_color`     | Color of the coordinate labels             | No       | `black`            | Any supported color |
| `label_font_size` | Font size for coordinate labels            | No       | `12`               | Pixels              |
| `font`            | Font for labels                            | No       | `ppb.ttf`          | -                   |

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

| Parameter      | Description                          | Required | Default                        | Notes                                                                                     |
|----------------|--------------------------------------|----------|--------------------------------|-------------------------------------------------------------------------------------------|
| `value`        | Text to display                      | Yes      | -                              | String                                                                                    |
| `x`            | X position                           | Yes      | -                              | Pixels or percentage                                                                      |
| `y`            | Y position                           | No       | Last text position + y_padding | Pixels or percentage                                                                      |
| `size`         | Font size                            | No       | `20`                           | Pixels                                                                                    |
| `font`         | Font file name                       | No       | `ppb.ttf`                      | Available fonts: `ppb.ttf`, `rbm.ttf`, or custom                                          |
| `color`        | Text color                           | No       | `black`                        | `black`, `white`, `red`,`yellow`                                                          |
| `anchor`       | Text anchor point                    | No       | `lt` (left-top)                | [Pillow text anchors](https://pillow.readthedocs.io/en/stable/handbook/text-anchors.html) |
| `max_width`    | Maximum text width before wrapping   | No       | -                              | Pixels or percentage                                                                      |
| `spacing`      | Line spacing for wrapped text        | No       | `5`                            | Pixels                                                                                    |
| `stroke_width` | Outline width                        | No       | `0`                            | Pixels                                                                                    |
| `stroke_fill`  | Outline color                        | No       | `white`                        | `white`, `black`, `accent`, `red`, `yellow`                                               |
| `y_padding`    | Vertical offset when y not specified | No       | `10`                           | Pixels                                                                                    |
| `visible`      | Show/hide element                    | No       | `true`                         | `true`, `false`                                                                           |
| `parse_colors` | Enable color markup in text          | No       | false                          | Enables `[color]text[/color]` syntax                                                      |
| `truncate`     | Truncate text if exceeds max_width   | No       | false                          | Adds ellipsis (...) when truncating                                                       |
### Inline Color Markup

Text elements support inline color markup when `parse_colors` is enabled. This allows different parts of the text to be rendered in different colors without needing to create multiple text elements.

| Parameter      | Description                 | Required | Default | Notes                                           |
|----------------|-----------------------------|----------|---------|-------------------------------------------------|
| `parse_colors` | Enable color markup parsing | No       | `false` | Set to `true` to enable color markup processing |

Color markup syntax:
```
[color]text[/color]
```

Available colors:
- `black` - Black text
- `white` - White text
- `red` - Red text (for red displays)
- `yellow` - Yellow text (for yellow displays)
- `accent` - Uses the display's accent color (red or yellow depending on hardware)

Examples:
```yaml
# Simple colored text
- type: text
  value: "Temperature: [red]25°C[/red]"
  x: 10
  y: 10
  parse_colors: true

# Multiple colors
- type: text
  value: "[black]Current[/black] temp: [accent]25°C[/accent]"
  x: 10
  y: 40
  parse_colors: true

# With Home Assistant templates
- type: text
  value: "Status: [{{ 'accent' if is_state('binary_sensor.door', 'on') else 'black' }}]{{ states('binary_sensor.door') }}[/{{ 'accent' if is_state('binary_sensor.door', 'on') else 'black' }}]"
  x: 10
  y: 70
  parse_colors: true
```

Notes:
- Color markup only works when `parse_colors: true` is set
- Without `parse_colors: true`, markup characters are treated as literal text
- Works with Home Assistant templates
- The `accent` color automatically adapts to the display type (red or yellow)

#### Multiline Text with parse_colors

When `parse_colors` is enabled, text elements support newline characters (`\n`) for creating multi-line colored text:

```yaml
- type: text
  value: "Line 1\n[red]Red Line 2[/red]\n[yellow]Yellow Line 3[/yellow]"
  x: "50%"
  y: "50%"
  font: "ppb.ttf"
  size: 24
  parse_colors: true
  anchor: "mm"
```
Anchor Behavior with Multiline Colored Text:
  - Anchors apply to the entire text block (all lines together)
  - For example, anchor: "mm" centers the entire block at the specified coordinates
  - Line spacing is controlled by the spacing parameter
  - Each line respects the align parameter (left, center, right)

### Multiline Text
Splits text into multiple lines based on a delimiter.

```yaml
- type: multiline
  value: "Line 1|Line 2|Line 3"
  delimiter: "|"
  font: "ppb.ttf"
  x: 0
  offset_y: 50
  size: 40
  color: black
```

| Parameter   | Description                    | Required | Default                   | Notes                                       |
|-------------|--------------------------------|----------|---------------------------|---------------------------------------------|
| `value`     | Text with delimiters           | Yes      | -                         | String                                      |
| `delimiter` | Character to split text        | Yes      | -                         | Single character                            |
| `x`         | X position                     | Yes      | -                         | Pixels or percentage                        |
| `offset_y`  | Vertical spacing between lines | Yes      | -                         | Pixels                                      |
| `y`         | Starting Y position            | No       | Last position + y_padding | Pixels or percentage                        |
| `size`      | Font size                      | No       | `20`                      | Pixels                                      |
| `font`      | Font file name                 | No       | `ppb.ttf`                 | Available fonts: `ppb.ttf`, `rbm.ttf`       |
| `color`     | Text color                     | No       | `black`                   | `white`, `black`, `accent`, `red`, `yellow` |
| `spacing`   | Additional line spacing        | No       | `0`                       | Pixels                                      |
| `visible`   | Show/hide element              | No       | `true`                    | `true`, `false`                             |
### Inline Color Markup

Multiline elements support inline color markup when `parse_colors` is enabled. This allows different parts of the text to be rendered in different colors without needing to create multiple text elements.

Please take a look at Text element documentation above.

### Line
Draws a straight line.

```yaml
- type: line
  x_start: 20
  x_end: 380
  y_start: 15
  y_end: 15
  width: 1
  fill: red
```

| Parameter      | Description                          | Required | Default         | Notes                                       |
|----------------|--------------------------------------|----------|-----------------|---------------------------------------------|
| `x_start`      | Starting X position                  | Yes      | -               | Pixels or percentage                        |
| `x_end`        | Ending X position                    | Yes      | -               | Pixels or percentage                        |
| `y_start`      | Starting Y position                  | No       | Auto-positioned | Pixels or percentage                        |
| `y_end`        | Ending Y position                    | No       | `y_start`       | Pixels or percentage                        |
| `fill`         | Line color                           | No       | `black`         | `white`, `black`, `accent`, `red`, `yellow` |
| `width`        | Line thickness                       | No       | `1`             | Pixels                                      |
| `y_padding`    | Vertical offset when auto-positioned | No       | `0`             | Pixels                                      |
| `dashed`       | Enable dashed line behaviour         | No       | `False`         | `False`, `True`                             |
| `dash_length`  | Length of dashes                     | No       | 5               | Pixels                                      |
| `space_length` | Length of spaces between dashes      | No       | 3               | Pixels                                      |
| `visible`      | Show/hide element                    | No       | `True`          | `True`, `False`                             |

### Rectangle
Draws a rectangle with optional rounded corners.

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

| Parameter | Description            | Required | Default | Notes                                                                                    |
|-----------|------------------------|----------|---------|------------------------------------------------------------------------------------------|
| `x_start` | Left position          | Yes      | -       | Pixels or percentage                                                                     |
| `x_end`   | Right position         | Yes      | -       | Pixels or percentage                                                                     |
| `y_start` | Top position           | Yes      | -       | Pixels or percentage                                                                     |
| `y_end`   | Bottom position        | Yes      | -       | Pixels or percentage                                                                     |
| `fill`    | Fill color             | No       | `null`  | `white`, `black`, `accent`, `red`, `yellow`  `null`                                      |
| `outline` | Border color           | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`                                              |
| `width`   | Border thickness       | No       | `1`     | Pixels                                                                                   |
| `radius`  | Corner radius          | No       | `0`     | Pixels                                                                                   |
| `corners` | Which corners to round | No       | `all`   | `all` or comma-separated list of: `top_left`, `top_right`, `bottom_left`, `bottom_right` |
| `visible` | Show/hide element      | No       | `true`  | `true`, `false`                                                                          |

### Rectangle Pattern
Draws repeated rectangles in a grid pattern.

```yaml
  - type: rectangle_pattern
    x_start: 5
    x_size: 35
    x_offset: 10
    y_start: 28
    y_size: 18
    y_offset: 2
    fill: white
    outline: red
    width: 1
    x_repeat: 1
    y_repeat: 4
```

| Parameter  | Description                  | Required | Default | Notes                                                |
|------------|------------------------------|----------|---------|------------------------------------------------------|
| `x_start`  | Starting X position          | Yes      | -       | Pixels or percentage                                 |
| `x_size`   | Width of each rectangle      | Yes      | -       | Pixels                                               |
| `x_offset` | Horizontal spacing           | Yes      | -       | Pixels                                               |
| `y_start`  | Starting Y position          | Yes      | -       | Pixels or percentage                                 |
| `y_size`   | Height of each rectangle     | Yes      | -       | Pixels                                               |
| `y_offset` | Vertical spacing             | Yes      | -       | Pixels                                               |
| `x_repeat` | Number of horizontal repeats | Yes      | -       | Integer                                              |
| `y_repeat` | Number of vertical repeats   | Yes      | -       | Integer                                              |
| `fill`     | Fill color                   | No       | `null`  | `white`, `black`, `accent`, `red`, `yellow`,  `null` |
| `outline`  | Border color                 | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`          |
| `width`    | Border thickness             | No       | `1`     | Pixels                                               |
| `visible`  | Show/hide element            | No       | `true`  | `true`, `false`                                      |

### Polygon

Draws a filled or outlined polygon based on the provided points.

```yaml
- type: polygon
  points: [[10, 10], [50, 10], [50, 50], [10, 50]]
  fill: "red"
  outline: "black"
```

| Parameter | Description                              | Required | Default | Notes                    |
|-----------|------------------------------------------|----------|---------|--------------------------|
| `points`  | List of coordinate pairs for the polygon | Yes      | -       | Example: [[x1, y1], ...] |
| `fill`    | Fill color for the polygon               | No       | `none`  | Any supported color      |
| `outline` | Outline color for the polygon            | No       | `black` | Any supported color      |
| `width`   | Width of the outline                     | No       | `1`     | Pixels                   |


### Circle
Draws a circle around a center point.

```yaml
- type: circle
  x: 50
  y: 50
  radius: 20
```

| Parameter | Description       | Required | Default | Notes                                                |
|-----------|-------------------|----------|---------|------------------------------------------------------|
| `x`       | Center X position | Yes      | -       | Pixels or percentage                                 |
| `y`       | Center Y position | Yes      | -       | Pixels or percentage                                 |
| `radius`  | Circle radius     | Yes      | -       | Pixels                                               |
| `fill`    | Fill color        | No       | `null`  | `white`, `black`, `accent`, `red`, `yellow` , `null` |
| `outline` | Border color      | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`          |
| `width`   | Border thickness  | No       | `1`     | Pixels                                               |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                                      |

### Ellipse
Draws an ellipse inside the bounding box.

```yaml
- type: ellipse
  x_start: 50
  x_end: 100
  y_start: 50
  y_end: 100
```

| Parameter | Description       | Required | Default | Notes                                               |
|-----------|-------------------|----------|---------|-----------------------------------------------------|
| `x_start` | Left position     | Yes      | -       | Pixels or percentage                                |
| `x_end`   | Right position    | Yes      | -       | Pixels or percentage                                |
| `y_start` | Top position      | Yes      | -       | Pixels or percentage                                |
| `y_end`   | Bottom position   | Yes      | -       | Pixels or percentage                                |
| `fill`    | Fill color        | No       | `null`  | `white`, `black`, `accent`, `red`, `yellow`  `null` |
| `outline` | Border color      | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`         |
| `width`   | Border thickness  | No       | `1`     | Pixels                                              |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                                     |

### Arc/ Pie Slice
Draws an arc (outline-only) or a pie slice (filled) based on the specified center, radius, and angles.
```yaml
- type: arc
  x: 100
  y: 75
  radius: 50
  start_angle: 0
  end_angle: 90
  fill: red
- type: arc
  x: 100
  y: 75
  radius: 50
  start_angle: 90
  end_angle: 0
```
| Parameter     | Description                          | Required | Default | Notes                       |
|---------------|--------------------------------------|----------|---------|-----------------------------|
| `x`           | X coordinate of the center           | Yes      | -       | Pixels or percentage        |
| `y`           | Y coordinate of the center           | Yes      | -       | Pixels or percentage        |
| `radius`      | Radius of the arc or pie slice       | Yes      | -       | Pixels                      |
| `start_angle` | Starting angle of the arc            | Yes      | -       | 0 degrees = right           |
| `end_angle`   | Ending angle af the arc              | Yes      | -       | Clockwise direction         |
| `fill`        | Foll color for the pie slices        | No       | `none`  | Use to make a pie slice     |
| `outline`     | Outline color for arcs or pie slices | No       | `black` |                             |
| `width`       | Width of the outline                 | No       | `1`     | Ignored if fill is provided |


### Icon
Draws Material Design Icons.

```yaml
- type: icon
  value: "account-cowboy-hat"
  x: 60
  y: 120
  size: 120
  color: red
```

| Parameter | Description       | Required | Default | Notes                                                                |
|-----------|-------------------|----------|---------|----------------------------------------------------------------------|
| `value`   | Icon name         | Yes      | -       | From [Material Design Icons](https://pictogrammers.com/library/mdi/) |
| `x`       | X position        | Yes      | -       | Pixels or percentage                                                 |
| `y`       | Y position        | Yes      | -       | Pixels or percentage                                                 |
| `size`    | Icon size         | Yes      | -       | Pixels                                                               |
| `fill`    | Icon color        | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`                          |
| `anchor`  | Icon anchor point | No       | `la`    | See text anchors                                                     |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                                                      |

Note: Icon name can be prefixed with `mdi:` (e.g., `mdi:account-cowboy-hat`)

### Icon Sequence
Draws multiple Material Design Icons in a sequence with specified direction and spacing.

```yaml
- type: icon_sequence
  x: 10
  y: 10
  icons:
    - mdi:home
    - mdi:arrow-right
    - mdi:office-building
  size: 24
  direction: right
```

| Parameter      | Description           | Required | Default | Notes                                                                |
|----------------|-----------------------|----------|---------|----------------------------------------------------------------------|
| `x`            | X position            | Yes      | -       | Pixels or percentage                                                 |
| `y`            | Y position            | Yes      | -       | Pixels or percentage                                                 |
| `icons`        | List of icon names    | Yes      | -       | From [Material Design Icons](https://pictogrammers.com/library/mdi/) |
| `size`         | Size of each icon     | Yes      | -       | Pixels                                                               |
| `direction`    | Direction of sequence | No       | `right` | `right`, `left`, `up`, `down`                                        |
| `spacing`      | Space between icons   | No       | size/4  | Pixels                                                               |
| `fill`         | Icon color            | No       | `black` | `white`, `black`, `accent`, `red`, `yellow`                          |
| `anchor`       | Icon anchor point     | No       | `la`    | See text anchors                                                     |
| `visible`      | Show/hide element     | No       | `true`  | `true`, `false`                                                      |


### Download Image
Downloads and displays an image from a URL.

```yaml
- type: dlimg
  url: "https://upload.wikimedia.org/wikipedia/en/9/9a/Trollface_non-free.png"
  x: 10
  y: 10
  xsize: 120
  ysize: 120
  rotate: 0
```

| Parameter       | Description       | Required | Default   | Notes                                                       |
|-----------------|-------------------|----------|-----------|-------------------------------------------------------------|
| `url`           | Image URL or path | Yes      | -         | HTTP/HTTPS URL, Data URI, local path or camera/image entity |
| `x`             | X position        | Yes      | -         | Pixels                                                      |
| `y`             | Y position        | Yes      | -         | Pixels                                                      |
| `xsize`         | Target width      | Yes      | -         | Pixels                                                      |
| `ysize`         | Target height     | Yes      | -         | Pixels                                                      |
| `resize_method` | Resizing method   | No       | `stretch` | `stretch`, `crop`, `cover`, `contain`                       |
| `rotate`        | Rotation angle    | No       | `0`       | Degrees                                                     |
| `visible`       | Show/hide element | No       | `true`    | `true`, `false`                                             |

Notes:
- Local images must be in `/config/media/`
- Data URIs supported (e.g., `data:image/gif;base64,...`)
- External images must be publicly accessible
- Camera entities (e.g. `camera.p1s_camera`) must have a `entity_picture` attribute

### QR Code
Generates and displays a QR code.

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

| Parameter | Description          | Required | Default | Notes                                       |
|-----------|----------------------|----------|---------|---------------------------------------------|
| `data`    | Content to encode    | Yes      | -       | String                                      |
| `x`       | X position           | Yes      | -       | Pixels or percentage                        |
| `y`       | Y position           | Yes      | -       | Pixels or percentage                        |
| `boxsize` | Size of each QR box  | No       | `2`     | Pixels                                      |
| `border`  | QR code border width | No       | `1`     | Units                                       |
| `color`   | QR code color        | No       | `black` | `white`, `black`, `accent`, `red`, `yellow` |
| `bgcolor` | Background color     | No       | `white` | `white`, `black`, `accent`, `red`, `yellow` |
| `visible` | Show/hide element    | No       | `true`  | `true`, `false`                             |

### Plot
Renders historical data from Home Assistant entities as a line plot.

```yaml
- type: plot
  x_start: 10
  y_start: 20
  x_end: 199
  y_end: 119
  duration: 36000 # 10 hours in seconds
  low: 10
  high: 20
  font: "ppb.ttf"
  data:
    - entity: sensor.temperature
      width: 3
    - entity: sensor.humidity
      color: red
  ```

| Parameter      | Description               | Required | Default       | Notes                                     |
|----------------|---------------------------|----------|---------------|-------------------------------------------|
| `data`         | List of entities to plot  | Yes      | -             | Array                                     |
| `ylegend`      | Y-axis legend options     | No       | -             | See [Y-Legend Options](#Y-Legend-Options) |
| `yaxis`        | Y-axis options            | No       | -             | See [Y-Axis Options](#Y-Axis-Options)     |
| `xlegend`      | X-axis legend options     | No       | -             | See [X-Legend Options](#X-Legend-Options) |
| `xaxis`        | X-axis options            | No       | -             | See [X-Axis Options](#X-Axis-Options)     |
| `x_start`      | Left position             | No       | `0`           | Pixels                                    |
| `y_start`      | Top position              | No       | `0`           | Pixels                                    |
| `x_end`        | Right position            | No       | Canvas width  | Pixels                                    |
| `y_end`        | Bottom position           | No       | Canvas height | Pixels                                    |
| `duration`     | Time range                | No       | `86400`       | Seconds                                   |
| `low`          | Minimum Y value           | No       | Auto          | Number                                    |
| `high`         | Maximum Y value           | No       | Auto          | Number                                    |
| `font`         | Font for Legend Text      | No       | `ppb.ttf`     | Font name                                 |
| `round_values` | Round min/max to integers | No       | `false`       | `true`, `false`                           |
| `size`         | Font size                 | No       | `10`          | Pixels                                    |
| `debug`        | Show debug borders        | No       | `false`       | `true`, `false`                           |
| `visible`      | Show/hide element         | No       | `true`        | `true`, `false`                           |

#### Line Options (per entity)
Each entry in the `data` array can have these options:
```yaml
- entity: sensor.temperature  
  color: red
  width: 2
  smooth: true
  show_points: true
  point_size: 3
  point_color: black
  value_scale: 1.0
```
| Parameter     | Description                                                        | Required | Default | Notes                       |
|---------------|--------------------------------------------------------------------|----------|---------|-----------------------------|
| `entity`      | Entity ID to plot                                                  | Yes      | -       | String                      |
| `color`       | Line color                                                         | No       | `black` | Any supported color         |
| `width`       | Line width                                                         | No       | `1`     | Pixels                      |
| `span_gaps`   | Connect lines across gaps                                          | No       | `false` | `true`, `false`, or seconds |
| `smooth`      | Curve smoothing                                                    | No       | `false` | `true`, `false`             |
| `line_style`  | `linear`: direct connections between points, `step`: stair pattern | No       | linear  | `linear` or `step`          |
| `show_points` | Show data points                                                   | No       | `false` | `true`, `false`             |
| `point_size`  | Data point size                                                    | No       | `3`     | Pixels                      |
| `point_color` | Data point color                                                   | No       | `black` | Any supported color         |
| `value_scale` | Scale data points by a factor                                      | No       | `1.0`   | Float                       |

#### Gap Handling

By default, the plot creates visual gaps when sensor data is unavailable or null. This matches Home Assistant's history graph behavior and prevents misleading visual connections across missing data periods.

**`span_gaps` Parameter Options:**

- `false` (default): Break lines at null/unavailable values - creates visual gaps
- `true`: Connect lines across all gaps
- `<number>`: Only span time gaps smaller than N seconds

**Examples:**

```yaml
# Default behavior - break at null values (recommended)
- type: plot
  data:
    - entity: sensor.temperature
      color: red
       # span_gaps: false (implicit default)

# Connect across all gaps
- type: plot
  data:
    - entity: sensor.temperature
      span_gaps: true

# Only break at gaps longer than 1 hour
- type: plot
  data:
    - entity: sensor.temperature
      span_gaps: 3600  # seconds
```

#### Y-Legend Options
```yaml
ylegend:
  width: -1
  color: black
  position: left
  size: 10
```
| Parameter  | Description     | Required | Default | Notes                         |
|------------|-----------------|----------|---------|-------------------------------|
| `width`    | Legend width    | No       | -1      | Pixels or `-1` for auto width |
| `color`    | Legend color    | No       | `black` | Any supported color           |
| `position` | Legend position | No       | `left`  | `left`, `right`               |
| `size`     | Font size       | No       | `10`    | Pixels                        |


#### Y-Axis Options
```yaml
yaxis:
  width: 1
  color: black
  tick_width: 2
  tick_every: 1.0
  grid: 5
  grid_color: black
  grid_style: dotted
```
| Parameter    | Description     | Required | Default   | Notes                                  |
|--------------|-----------------|----------|-----------|----------------------------------------|
| `width`      | Axis line width | No       | `1`       | Pixels                                 |
| `color`      | Axis color      | No       | `black`   | Any supported color                    |
| `tick_width` | Tick mark width | No       | `2`       | Pixels                                 |
| `tick_every` | Tick interval   | No       | `1.0`     | Float                                  |
| `grid`       | Enable Grid     | No       | `true`    | Boolean                                |
| `grid_color` | Grid color      | No       | `black`   | Any supported color                    |
| `grid_style` | Grid line style | No       | `dotted`  | `dotted`, `dashed`, or `lines` (solid) |

#### X-Legend Options
```yaml
xlegend:
  width: -1
  format: "%H:%M"
  interval: 3600
  snap_to_hours: true
  size: 10
  position: bottom
  color: black
```
| Parameter       | Description                | Required | Default  | Notes                                           |
|-----------------|----------------------------|----------|----------|-------------------------------------------------|
| `width`         | Legend width               | No       | -1       | Pixels or `-1` for auto width                   |
| `format`        | Time label format          | No       | `%H:%M`  | [Python strftime format](https://strftime.org/) |
| `interval`      | Time interval in seconds   | No       | `3600`   | Seconds                                         |
| `snap_to_hours` | Align time labels to hours | No       | `true`   | `true`, `false`                                 |
| `size`          | Font size for time labels  | No       | `10`     | Pixels                                          |
| `position`      | Position of time labels    | No       | `bottom` | `bottom` or `top`                               |
| `color`         | Color for time labels      | No       | `black`  | Any supported color                             |

#### X-Axis Options
```yaml
xaxis:
  width: 1
  color: black
  tick_width: 2
  tick_length: 4
  tick_every: 1.0
  grid: true
  grid_color: black
  grid_style: dotted
```
| Parameter     | Description      | Required | Default  | Notes                                  |
|---------------|------------------|----------|----------|----------------------------------------|
| `width`       | Axis line width  | No       | `1`      | Pixels                                 |
| `color`       | Axis color       | No       | `black`  | Any supported color                    |
| `tick_width`  | Tick mark width  | No       | `2`      | Pixels                                 |
| `tick_length` | Tick mark length | No       | `4`      | Pixels                                 |
| `tick_every`  | Tick interval    | No       | `1.0`    | Float                                  |
| `grid`        | Enable grid      | No       | `true`   | Boolean                                |
| `grid_color`  | Grid color       | No       | `black`  | Any supported color                    |
| `grid_style`  | Grid line style  | No       | `dotted` | `dotted`, `dashed`, or `lines` (solid) |

#### Example with Full Configuration
```yaml
- type: plot
  x_start: 10
  y_start: 20
  x_end: 290
  y_end: 120
  duration: 86400
  font: "ppb.ttf"
  round_values: true
  ylegend:
    color: black
    position: left
    size: 12
    width: -1
  yaxis:
    width: 1
    color: black
    grid: 5
    grid_color: gray
    grid_style: dotted
    tick_width: 2
    tick_every: 1.0
  xlegend:
    format: "%H:%M"
    interval: 3600
    snap_to_hours: true
    color: black
    position: bottom
    size: 12
    width: -1
  xaxis:
    width: 1
    color: black
    grid: 5
    grid_color: gray
    grid_style: dotted
    tick_width: 2
    tick_length: 4
    tick_every: 1.0
  data:
    - entity: sensor.temperature
      color: red
      width: 2
      smooth: true
      show_points: true
      point_size: 3
      point_color: black
      value_scale: 1.0
```

### Progress Bar
Displays a progress bar with optional percentage text.

```yaml
- type: progress_bar
  x_start: 10
  y_start: 10
  x_end: 280
  y_end: 30
  fill: red
  outline: black
  width: 1
  progress: 42
  direction: right
  show_percentage: true
  font: "ppb.ttf"
```

| Parameter         | Description               | Required | Default   | Notes                                       |
|-------------------|---------------------------|----------|-----------|---------------------------------------------|
| `x_start`         | Left position             | Yes      | -         | Pixels or percentage                        |
| `y_start`         | Top position              | Yes      | -         | Pixels or percentage                        |
| `x_end`           | Right position            | Yes      | -         | Pixels or percentage                        |
| `y_end`           | Bottom position           | Yes      | -         | Pixels or percentage                        |
| `progress`        | Progress value            | Yes      | -         | 0-100 (clamped)                             |
| `direction`       | Fill direction            | No       | `right`   | `right`, `left`, `up`, `down`               |
| `background`      | Background color          | No       | `white`   | `white`, `black`, `accent`, `red`, `yellow` |
| `fill`            | Progress bar color        | No       | `red`     | `white`, `black`, `accent`, `red`, `yellow` |
| `outline`         | Border color              | No       | `black`   | `white`, `black`, `accent`, `red`, `yellow` |
| `width`           | Border thickness          | No       | `1`       | Pixels                                      |
| `show_percentage` | Show percentage text      | No       | `false`   | `true`, `false`                             |
| `font`            | Percentage text font      | No       | `ppb.ttf` | Font name                                   |
| `visible`         | Show/hide element         | No       | `true`    | `true`, `false`                             |

## Template Examples

Basic state display:
```yaml
- type: "text"
  value: "Temperature: {{ states('sensor.temperature') }}°C"
  x: 10
  y: 10
```

Conditional formatting:
```yaml
- type: "text"
  value: >
    Status:
    [{{ 'red' if is_state('binary_sensor.door', 'on') else 'black' }}]
    {{ states('binary_sensor.door') }}
    [/{{ 'red' if is_state('binary_sensor.door', 'on') else 'black' }}]
  parse_colors: true
  x: 10
  y: 10
```

Dynamic positioning:
```yaml
- type: "text"
  value: "Centered"
  x: "50%"
  y: "50%"
  anchor: "mm"
```

### Common Use Cases

Battery status with icon:
```yaml
- type: "icon"
  value: "mdi:battery"
  x: 10
  y: 10
  size: 24
  color: "{{ 'red' if states('sensor.battery')|float < 20 else 'black' }}"
- type: "text"
  value: "{{ states('sensor.battery') }}%"
  x: 40
  y: 10
```

Header with divider:
```yaml
- type: "text"
  value: "Status Overview"
  x: 10
  y: 10
  size: 24
- type: "line"
  x_start: 10
  x_end: 286
  y_start: 40
  width: 2
```

Multi-sensor display:
```yaml
- type: "text"
  value: "Living Room"
  x: 10
  y: 10
  size: 24
- type: "icon"
  value: "mdi:thermometer"
  x: 10
  y: 40
  size: 20
- type: "text"
  value: "{{ states('sensor.living_room_temperature') }}°C"
  x: 35
  y: 40
- type: "icon"
  value: "mdi:water-percent"
  x: 10
  y: 70
  size: 20
- type: "text"
  value: "{{ states('sensor.living_room_humidity') }}%"
  x: 35
  y: 70
```
