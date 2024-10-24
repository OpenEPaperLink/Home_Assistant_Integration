# drawcustom

With `drawcustom`, you can create an image in Home Assistant and send the rendered image to an OpenEpaperLink AP.

## Basic Usage

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

## Global Parameters

| Parameter    | Description                          | Required | Default | Values                  |
|--------------|--------------------------------------|----------|---------|-------------------------|
| `payload`    | Payload to draw, see below           | Yes      | -       |                         |
| `background` | Background color of the entire image | Yes      | -       | `white`, `black`, `red` |
| `rotate`     | Rotation of the entire image         | No       | `0`     | `0`, `90`, `180`, `270` |
| `dry-run`    | Generate image without sending to AP | No       | `false` | `true`, `false`         |

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

| Parameter      | Description                          | Required | Default                        | Notes                                                                                     |
|----------------|--------------------------------------|----------|--------------------------------|-------------------------------------------------------------------------------------------|
| `value`        | Text to display                      | Yes      | -                              | String                                                                                    |
| `x`            | X position                           | Yes      | -                              | Pixels from left                                                                          |
| `y`            | Y position                           | No       | Last text position + y_padding | Pixels from top                                                                           |
| `size`         | Font size                            | No       | `20`                           | Pixels                                                                                    |
| `font`         | Font file name                       | No       | `ppb.ttf`                      | Available fonts: `ppb.ttf`, `rbm.ttf`, or custom                                          |
| `color`        | Text color                           | No       | `black`                        | `black`, `white`, `red`                                                                   |
| `anchor`       | Text anchor point                    | No       | `lt` (left-top)                | [Pillow text anchors](https://pillow.readthedocs.io/en/stable/handbook/text-anchors.html) |
| `max_width`    | Maximum text width before wrapping   | No       | -                              | Pixels                                                                                    |
| `spacing`      | Line spacing for wrapped text        | No       | `5`                            | Pixels                                                                                    |
| `stroke_width` | Outline width                        | No       | `0`                            | Pixels                                                                                    |
| `stroke_fill`  | Outline color                        | No       | `white`                        | `white`, `black`, `red`                                                                   |
| `align`        | Text alignment                       | No       | `left`                         | `left`, `center`, `right`                                                                 |
| `y_padding`    | Vertical offset when y not specified | No       | `10`                           | Pixels                                                                                    |
| `visible`      | Show/hide element                    | No       | `true`                         | `true`, `false`                                                                           |

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

| Parameter   | Description                    | Required | Default                   | Notes                                 |
|-------------|--------------------------------|----------|---------------------------|---------------------------------------|
| `value`     | Text with delimiters           | Yes      | -                         | String                                |
| `delimiter` | Character to split text        | Yes      | -                         | Single character                      |
| `x`         | X position                     | Yes      | -                         | Pixels from left                      |
| `offset_y`  | Vertical spacing between lines | Yes      | -                         | Pixels                                |
| `start_y`   | Starting Y position            | No       | Last position + y_padding | Pixels from top                       |
| `size`      | Font size                      | No       | `20`                      | Pixels                                |
| `font`      | Font file name                 | No       | `ppb.ttf`                 | Available fonts: `ppb.ttf`, `rbm.ttf` |
| `color`     | Text color                     | No       | `black`                   | `black`, `white`, `red`               |
| `spacing`   | Additional line spacing        | No       | `0`                       | Pixels                                |
| `align`     | Text alignment                 | No       | `left`                    | `left`, `center`, `right`             |
| `visible`   | Show/hide element              | No       | `true`                    | `true`, `false`                       |

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

| Parameter   | Description                          | Required | Default         | Notes                   |
|-------------|--------------------------------------|----------|-----------------|-------------------------|
| `x_start`   | Starting X position                  | Yes      | -               | Pixels                  |
| `x_end`     | Ending X position                    | Yes      | -               | Pixels                  |
| `y_start`   | Starting Y position                  | No       | Auto-positioned | Pixels                  |
| `y_end`     | Ending Y position                    | No       | `y_start`       | Pixels                  |
| `fill`      | Line color                           | No       | `black`         | `black`, `white`, `red` |
| `width`     | Line thickness                       | No       | `1`             | Pixels                  |
| `y_padding` | Vertical offset when auto-positioned | No       | `0`             | Pixels                  |
| `visible`   | Show/hide element                    | No       | `true`          | `true`, `false`         |

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
| `x_start` | Left position          | Yes      | -       | Pixels                                                                                   |
| `x_end`   | Right position         | Yes      | -       | Pixels                                                                                   |
| `y_start` | Top position           | Yes      | -       | Pixels                                                                                   |
| `y_end`   | Bottom position        | Yes      | -       | Pixels                                                                                   |
| `fill`    | Fill color             | No       | `null`  | `black`, `white`, `red`, `null`                                                          |
| `outline` | Border color           | No       | `black` | `black`, `white`, `red`                                                                  |
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

| Parameter  | Description                  | Required | Default | Notes                           |
|------------|------------------------------|----------|---------|---------------------------------|
| `x_start`  | Starting X position          | Yes      | -       | Pixels                          |
| `x_size`   | Width of each rectangle      | Yes      | -       | Pixels                          |
| `x_offset` | Horizontal spacing           | Yes      | -       | Pixels                          |
| `y_start`  | Starting Y position          | Yes      | -       | Pixels                          |
| `y_size`   | Height of each rectangle     | Yes      | -       | Pixels                          |
| `y_offset` | Vertical spacing             | Yes      | -       | Pixels                          |
| `x_repeat` | Number of horizontal repeats | Yes      | -       | Integer                         |
| `y_repeat` | Number of vertical repeats   | Yes      | -       | Integer                         |
| `fill`     | Fill color                   | No       | `null`  | `black`, `white`, `red`, `null` |
| `outline`  | Border color                 | No       | `black` | `black`, `white`, `red`         |
| `width`    | Border thickness             | No       | `1`     | Pixels                          |
| `visible`  | Show/hide element            | No       | `true`  | `true`, `false`                 |

### Circle
Draws a circle around a center point.

```yaml
- type: circle
  x: 50
  y: 50
  radius: 20
```

| Parameter | Description       | Required | Default | Notes                           |
|-----------|-------------------|----------|---------|---------------------------------|
| `x`       | Center X position | Yes      | -       | Pixels                          |
| `y`       | Center Y position | Yes      | -       | Pixels                          |
| `radius`  | Circle radius     | Yes      | -       | Pixels                          |
| `fill`    | Fill color        | No       | `null`  | `black`, `white`, `red`, `null` |
| `outline` | Border color      | No       | `black` | `black`, `white`, `red`         |
| `width`   | Border thickness  | No       | `1`     | Pixels                          |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                 |

### Ellipse
Draws an ellipse inside the bounding box.

```yaml
- type: ellipse
  x_start: 50
  x_end: 100
  y_start: 50
  y_end: 100
```

| Parameter | Description       | Required | Default | Notes                           |
|-----------|-------------------|----------|---------|---------------------------------|
| `x_start` | Left position     | Yes      | -       | Pixels                          |
| `x_end`   | Right position    | Yes      | -       | Pixels                          |
| `y_start` | Top position      | Yes      | -       | Pixels                          |
| `y_end`   | Bottom position   | Yes      | -       | Pixels                          |
| `fill`    | Fill color        | No       | `null`  | `black`, `white`, `red`, `null` |
| `outline` | Border color      | No       | `black` | `black`, `white`, `red`         |
| `width`   | Border thickness  | No       | `1`     | Pixels                          |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                 |

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
| `x`       | X position        | Yes      | -       | Pixels                                                               |
| `y`       | Y position        | Yes      | -       | Pixels                                                               |
| `size`    | Icon size         | Yes      | -       | Pixels                                                               |
| `fill`    | Icon color        | No       | `black` | `black`, `white`, `red`                                              |
| `anchor`  | Icon anchor point | No       | `la`    | See text anchors                                                     |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                                                      |

Note: Icon name can be prefixed with `mdi:` (e.g., `mdi:account-cowboy-hat`)

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

| Parameter | Description       | Required | Default | Notes                                   |
|-----------|-------------------|----------|---------|-----------------------------------------|
| `url`     | Image URL or path | Yes      | -       | HTTP/HTTPS URL, Data URI, or local path |
| `x`       | X position        | Yes      | -       | Pixels                                  |
| `y`       | Y position        | Yes      | -       | Pixels                                  |
| `xsize`   | Target width      | Yes      | -       | Pixels                                  |
| `ysize`   | Target height     | Yes      | -       | Pixels                                  |
| `rotate`  | Rotation angle    | No       | `0`     | Degrees                                 |
| `visible` | Show/hide element | No       | `true`  | `true`, `false`                         |

Notes:
- Local images must be in `/config/media/`
- Data URIs supported (e.g., `data:image/gif;base64,...`)
- External images must be publicly accessible

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

| Parameter | Description          | Required | Default | Notes                   |
|-----------|----------------------|----------|---------|-------------------------|
| `data`    | Content to encode    | Yes      | -       | String                  |
| `x`       | X position           | Yes      | -       | Pixels                  |
| `y`       | Y position           | Yes      | -       | Pixels                  |
| `boxsize` | Size of each QR box  | No       | `2`     | Pixels                  |
| `border`  | QR code border width | No       | `1`     | Units                   |
| `color`   | QR code color        | No       | `black` | `black`, `white`, `red` |
| `bgcolor` | Background color     | No       | `white` | `black`, `white`, `red` |
| `visible` | Show/hide element    | No       | `true`  | `true`, `false`         |

### Plot
Renders historical data from Home Assistant entities as a line plot.

```yaml
- type: plot
  x_start: 10
  y_start: 20
  x_end: 199
  y_end: 119
  duration: 36000
  low: 10
  high: 20
  data:
    - entity: sensor.temperature
      width: 3
    - entity: sensor.humidity
      color: red
  ```

| Parameter  | Description              | Required | Default       | Notes           |
|------------|--------------------------|----------|---------------|-----------------|
| `x_start`  | Left position            | No       | `0`           | Pixels          |
| `y_start`  | Top position             | No       | `0`           | Pixels          |
| `x_end`    | Right position           | No       | Canvas width  | Pixels          |
| `y_end`    | Bottom position          | No       | Canvas height | Pixels          |
| `duration` | Time range               | No       | `86400`       | Seconds         |
| `low`      | Minimum Y value          | No       | Auto          | Number          |
| `high`     | Maximum Y value          | No       | Auto          | Number          |
| `font`     | Font file                | No       | `ppb.ttf`     | Font name       |
| `size`     | Font size                | No       | `10`          | Pixels          |
| `debug`    | Show debug borders       | No       | `false`       | `true`, `false` |
| `data`     | List of entities to plot | Yes      | -             | Array           |
| `visible`  | Show/hide element        | No       | `true`        | `true`, `false` |

#### Plot Legend Options
```yaml
ylegend:
  width: -1        # Auto width if -1
  color: black     # Legend color
  position: left   # left or right
  font: ppb.ttf   # Legend font
  size: 10        # Legend font size
```

#### Plot Axis Options
```yaml
yaxis:
  width: 1         # Axis line width
  color: black     # Axis color
  tick_width: 2    # Width of tick marks
  tick_every: 1.0  # Tick interval
  grid: 5         # Grid point spacing
  grid_color: black # Grid color
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
```

| Parameter         | Description          | Required | Default | Notes                         |
|-------------------|----------------------|----------|---------|-------------------------------|
| `x_start`         | Left position        | Yes      | -       | Pixels                        |
| `y_start`         | Top position         | Yes      | -       | Pixels                        |
| `x_end`           | Right position       | Yes      | -       | Pixels                        |
| `y_end`           | Bottom position      | Yes      | -       | Pixels                        |
| `progress`        | Progress value       | Yes      | -       | 0-100                         |
| `direction`       | Fill direction       | No       | `right` | `right`, `left`, `up`, `down` |
| `background`      | Background color     | No       | `white` | `white`, `black`, `red`       |
| `fill`            | Progress bar color   | No       | `red`   | `white`, `black`, `red`       |
| `outline`         | Border color         | No       | `black` | `white`, `black`, `red`       |
| `width`           | Border thickness     | No       | `1`     | Pixels                        |
| `show_percentage` | Show percentage text | No       | `false` | `true`, `false`               |
| `visible`         | Show/hide element    | No       | `true`  | `true`, `false`               |