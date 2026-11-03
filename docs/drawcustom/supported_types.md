# drawcustom

`open_epaper_link.drawcustom` draws an image from a list of elements and sends it to one or more tags, either through their Access Point or directly to ATC tags over Bluetooth.

> **The element reference lives in [odl-renderer](https://github.com/OpenDisplay/odl-renderer/blob/odl-renderer-v0.5.15/README.md).**
> drawcustom renders the payload with the odl-renderer library, which defines every element type and the fields they share (`visible`, `rotation`, `mirror`, `pivot`, anchors, colours, coordinates). This page covers only what the integration adds: the action and its options, fonts, local files, templates and plots of Home Assistant history.

<!-- Keep the odl-renderer links on this page in sync with the odl-renderer pin in manifest.json. -->

## Contents

- [Calling the action](#calling-the-action)
- [Options](#options)
- [Colours](#colours)
- [Element types](#element-types)
- [Fonts](#fonts)
- [Local files](#local-files)
- [Plots](#plots)
- [Templates](#templates)

## Calling the action

Target the tags by device, area or label. The payload is a list of elements, drawn in order from first to last:

```yaml
action: open_epaper_link.drawcustom
target:
  device_id: <your tag>
data:
  background: white
  payload:
    - type: text
      value: Hello World!
      x: 0
      y: 0
      size: 40
      color: red
    - type: icon
      value: mdi:account-cowboy-hat
      x: 60
      y: 120
      size: 120
      color: red
```

What was drawn appears on the tag's **Content** image entity.

## Options

| Option         | Description                                                    | Default    | Values                                                                                                                         |
|----------------|----------------------------------------------------------------|------------|--------------------------------------------------------------------------------------------------------------------------------|
| `payload`      | The elements to draw (required)                                | —          | See [Element types](#element-types)                                                                                            |
| `background`   | Colour to fill the display with before drawing                 | `white`    | `white`, `black`, `accent`, `red`, `yellow`                                                                                    |
| `rotate`       | Degrees to rotate the finished image                           | `0`        | `0`, `90`, `180`, `270`                                                                                                        |
| `dither`       | How the image is reduced to the colours the tag can show       | `ordered`  | `none`, `burkes`, `ordered`, `floyd_steinberg`, `atkinson`, `stucki`, `sierra`, `sierra_lite`, `jarvis_judice_ninke`, `dizzy` |
| `refresh_type` | How the tag redraws                                            | `adaptive` | `adaptive`, `full`, `fast`, `fast_no_red`                                                                                      |
| `ttl`          | Seconds the tag sleeps before checking in again, after this update | `60`   | `0`–`86400`                                                                                                                    |
| `dry-run`      | Render and show the image in Home Assistant without sending it | `false`    | `true`, `false`                                                                                                                |

- **`rotate`** is applied before sending, so a payload can be laid out sideways for a tag mounted that way. The rotation configured on the tag still applies on top of it.
- **`dither`**: `ordered` suits flat graphics, the error-diffusion algorithms (`floyd_steinberg`, `atkinson` and the others) suit photos.
- **`refresh_type`**: `adaptive` uses quick refreshes and one full refresh a night to clear ghosting, which is much easier on the battery than `full`, a full refresh every time.
- **`ttl`** applies once. A long value means the tag cannot be updated again until it has passed.
- `refresh_type` and `ttl` apply to tags connected to an Access Point. ATC tags ignore them.

Calls written for 3.x keep working: the old numeric `dither` (`0`, `1`, `2`) and `refresh_type` (`0`–`3`) values are still accepted, and options that no longer exist are ignored.

## Colours

Colours are given by name (`black`, `white`, `red`, `yellow`, `gray`, …), shortcut (`b`, `w`, `r`, `y`), halftone (`half_red`, `hr`, …) or hex (`"#FF0000"`). The full list is in the [odl-renderer colour reference](https://github.com/OpenDisplay/odl-renderer/blob/odl-renderer-v0.5.15/README.md#colors).

Use `accent` (or `a`, `half_accent`, `ha`) to draw in the tag's accent colour. It becomes red or yellow depending on the tag, which keeps one payload working on both. On a black and white tag, `accent` is black.

```yaml
- type: text
  value: Hello World!
  x: 0
  y: 0
  size: 40
  color: accent
```

> [!IMPORTANT]
> Always quote hex colours in YAML: `fill: "#FF0000"`, not `fill: #FF0000`. An unquoted `#` starts a comment, so the colour is silently dropped.

## Element types

The integration passes elements to odl-renderer unchanged. See the [odl-renderer element reference](https://github.com/OpenDisplay/odl-renderer/blob/odl-renderer-v0.5.15/README.md#element-types) for every field.

| Type                | Purpose                                                                |
|---------------------|------------------------------------------------------------------------|
| `text`              | Single-line text with wrapping, truncation, stroke and inline colours |
| `multiline`         | Text split into lines by a delimiter                                   |
| `line`              | Straight line                                                          |
| `rectangle`         | Rectangle, filled or outlined                                          |
| `rectangle_pattern` | Repeated grid of rectangles                                            |
| `polygon`           | Any polygon                                                            |
| `circle`            | Circle                                                                 |
| `ellipse`           | Ellipse                                                                |
| `arc`               | Arc or pie slice                                                       |
| `icon`              | Material Design Icon                                                   |
| `icon_sequence`     | Row of icons                                                           |
| `dlimg`             | Image from a URL, a local file or embedded data                        |
| `qrcode`            | QR code                                                                |
| `progress_bar`      | Progress bar with optional percentage                                  |
| `plot`              | Line chart of Home Assistant history (see [Plots](#plots))             |
| `diagram`           | Bar chart with labelled axes                                           |
| `debug_grid`        | Coordinate grid for laying out a payload                               |

Every element also takes `visible`, `rotation`, `mirror` and `pivot`, and positions can be given in pixels or percent with an [anchor](https://github.com/OpenDisplay/odl-renderer/blob/odl-renderer-v0.5.15/README.md#anchor).

## Fonts

```yaml
# The default font, ppb.ttf. The line can be left out.
- type: text
  value: Default font
  font: ppb.ttf
  x: 10
  y: 10

# A file name, looked up in the font folders below.
- type: text
  value: Custom font
  font: CustomFont.ttf
  x: 10
  y: 50

# An absolute path, in a folder Home Assistant allows (see Local files).
- type: text
  value: Custom font with a path
  font: /media/GothamBold-Rnd.ttf
  x: 10
  y: 90
```

A font given by file name is looked up in these folders, in order:

1. `/config/www/fonts/`
2. `/config/media/fonts/`
3. `/media/fonts/`

None of them exist by default. Create the one you want to use, for example with the File editor or Studio Code Server app, over Samba, or over SSH.

`ppb.ttf` and `rbm.ttf` come with odl-renderer and are always available. If a font cannot be found, a warning is logged and `ppb.ttf` is used instead.

## Local files

Images (`dlimg` with an absolute path as its `url`) and fonts given by absolute path can only be read from folders Home Assistant allows: `/config/www`, your media folders, and any folder listed under [`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs). A file anywhere else is refused, and the action fails with an error naming it. Fonts found by name in the [font folders](#fonts) are not affected.

To use another folder, add it to your configuration:

```yaml
# configuration.yaml
homeassistant:
  allowlist_external_dirs:
    - /share/images
```

```yaml
- type: dlimg
  url: /share/images/logo.png
  x: 0
  y: 0
  xsize: 120
  ysize: 60
```

## Plots

`plot` draws the recorded history of Home Assistant entities. Name the entity in each series and the integration fetches its history from the recorder for the plot's `duration` (in seconds, a day by default):

```yaml
- type: plot
  duration: 86400
  data:
    - entity: sensor.living_room_temperature
      color: red
    - entity: sensor.outside_temperature
      color: black
      line_style: dashed
```

The series, axis and legend options are in the [odl-renderer plot reference](https://github.com/OpenDisplay/odl-renderer/blob/odl-renderer-v0.5.15/README.md#plot). Entities excluded from the recorder have no history to plot.

## Templates

Home Assistant renders templates in the payload before drawing, so any field can come from your entities.

```yaml
- type: text
  value: "Temperature: {{ states('sensor.temperature') }}°C"
  x: 10
  y: 10
```

Colours that change with a state:

```yaml
- type: icon
  value: mdi:battery
  x: 10
  y: 10
  size: 24
  color: "{{ 'red' if states('sensor.battery') | float < 20 else 'black' }}"
- type: text
  value: "{{ states('sensor.battery') }}%"
  x: 40
  y: 10
```

Inline colours within one text:

```yaml
- type: text
  value: >
    Door: [{{ 'red' if is_state('binary_sensor.door', 'on') else 'black' }}]{{ states('binary_sensor.door') }}[/{{ 'red' if is_state('binary_sensor.door', 'on') else 'black' }}]
  parse_colors: true
  x: 10
  y: 10
```

Hiding an element: `visible` hides it when it renders to `false` or to nothing.

```yaml
- type: icon
  value: mdi:door-open
  x: 260
  y: 10
  size: 24
  visible: "{{ is_state('binary_sensor.door', 'on') }}"
```

Centring with percent positions and an anchor:

```yaml
- type: text
  value: Centred
  x: 50%
  y: 50%
  anchor: mm
```
