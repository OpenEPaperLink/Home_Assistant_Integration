from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import shutil
from datetime import timedelta, datetime

import qrcode
import requests
from PIL import Image, ImageDraw, ImageFont
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt
from requests_toolbelt.multipart.encoder import MultipartEncoder

from .const import DOMAIN
from .util import get_image_folder, get_image_path

_LOGGER = logging.getLogger(__name__)

white = (255, 255, 255, 255)
black = (0, 0, 0, 255)
red = (255, 0, 0, 255)
yellow = (255, 255, 0, 255)
queue = []
not_setup = True
running = False


# setup
def setup(hass, not_setup):
    if not_setup:
        hass.bus.listen(DOMAIN + "_event", handle_event)
        not_setup = False
    return True


# handle_event
def handle_event(self):
    handle_queue()


# is_decimal
def is_decimal(string):
    if not string:
        return False
    if string.startswith("-"):
        string = string[1:]
    return len(string.split(".")) <= 2 and string.replace(".", "").isdecimal()


# min_max
def min_max(data):
    if not data:
        raise HomeAssistantError("data error, someting is not in range of the recorder")
    mi, ma = data[0], data[0]
    for d in data[1:]:
        mi = min(mi, d)
        ma = max(ma, d)
    return mi, ma


# img downloader
def download_img(entity_id, service, hass):
    entity = hass.states.get(entity_id)
    if not (entity and 'width' in entity.attributes):
        raise HomeAssistantError(
            "id was not found yet, please wait for the display to check in at least once " + entity_id)
    url = service.data.get("url", "")
    rotate = service.data.get("rotation", 0)
    # get image
    response = requests.get(url)
    # load the res of the esl
    res = [hass.states.get(entity_id).attributes['width'], hass.states.get(entity_id).attributes['height']]
    img = Image.open(io.BytesIO(response.content))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    if rotate != 0:
        img = img.rotate(-rotate, expand=1)
    width, height = img.size
    if width != res[0] or height != res[1]:
        img = img.resize((res[0], res[1]))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality="maximum")
    img.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")
    byte_im = buf.getvalue()
    return byte_im


# get_wrapped_text
def get_wrapped_text(text: str, font: ImageFont.ImageFont, line_length: int):
    lines = ['']
    for word in text.split():
        line = f'{lines[-1]} {word}'.strip()
        if font.getlength(line) <= line_length:
            lines[-1] = line
        else:
            lines.append(word)
    return '\n'.join(lines)


# converts a color name to the corresponding color index for the palette
def get_index_color(color):
    if color is None:
        return None
    color_str = str(color)
    if color_str == "black" or color_str == "b":
        return black
    elif color_str == "red" or color_str == "r":
        return red
    elif color_str == "yellow" or color_str == "y":
        return yellow
    else:
        return white


# should_show_element
def should_show_element(element):
    return element['visible'] if 'visible' in element else True


# custom image generator
def generate_custom_image(entity_id, service, hass):
    payload = service.data.get("payload", "")
    rotate = service.data.get("rotate", 0)
    dither = service.data.get("dither", False)
    background = get_index_color(service.data.get("background", "white"))
    entity = hass.states.get(entity_id)
    if not (entity and 'width' in entity.attributes):
        raise HomeAssistantError(
            "id was not found yet, please wait for the display to check in at least once " + entity_id)
    canvas_width = hass.states.get(entity_id).attributes['width']
    canvas_height = hass.states.get(entity_id).attributes['height']
    if rotate == 0:
        img = Image.new('RGBA', (canvas_width, canvas_height), color=background)
    elif rotate == 90:
        img = Image.new('RGBA', (canvas_height, canvas_width), color=background)
    elif rotate == 180:
        img = Image.new('RGBA', (canvas_width, canvas_height), color=background)
    elif rotate == 270:
        img = Image.new('RGBA', (canvas_height, canvas_width), color=background)
    else:
        img = Image.new('RGBA', (canvas_width, canvas_height), color=background)
    pos_y = 0
    for element in payload:
        _LOGGER.debug("type: " + element["type"])
        if not should_show_element(element):
            continue
        # line
        if element["type"] == "line":
            check_for_missing_required_arguments(element, ["x_start", "x_end"], "line")
            img_line = ImageDraw.Draw(img)
            if "y_start" not in element:
                y_start = pos_y + element.get("y_padding", 0)
                y_end = y_start
            else:
                y_start = element["y_start"]
                y_end = element["y_end"]

            fill = get_index_color(element['fill']) if 'fill' in element else black
            width = element['width'] if 'width' in element else 1

            img_line.line([(element['x_start'], y_start), (element['x_end'], y_end)], fill=fill, width=width)
            pos_y = y_start
        # rectangle
        if element["type"] == "rectangle":
            check_for_missing_required_arguments(element, ["x_start", "x_end", "y_start", "y_end"], "rectangle")
            img_rect = ImageDraw.Draw(img)
            rect_fill = get_index_color(element['fill']) if 'fill' in element else None
            rect_outline = get_index_color(element['outline']) if 'outline' in element else "black"
            rect_width = element['width'] if 'width' in element else 1
            radius = element['radius'] if 'radius' in element else 10 if 'corners' in element else 0
            corners = rounded_corners(element['corners']) if 'corners' in element else rounded_corners(
                "all") if 'radius' in element else (False, False, False, False)

            img_rect.rounded_rectangle([(element['x_start'], element['y_start']), (element['x_end'], element['y_end'])],
                                       fill=rect_fill, outline=rect_outline, width=rect_width, radius=radius,
                                       corners=corners)
        # rectangle pattern
        if element["type"] == "rectangle_pattern":
            check_for_missing_required_arguments(element, ["x_start", "x_size",
                                                           "y_start", "y_size",
                                                           "x_repeat", "y_repeat",
                                                           "x_offset", "y_offset"], "rectangle_pattern")
            img_rect_pattern = ImageDraw.Draw(img)
            fill = get_index_color(element['fill']) if 'fill' in element else None
            outline = get_index_color(element['outline']) if 'outline' in element else "black"
            width = element['width'] if 'width' in element else 1
            radius = element['radius'] if 'radius' in element else 10 if 'corners' in element else 0
            corners = rounded_corners(element['corners']) if 'corners' in element else rounded_corners(
                "all") if 'radius' in element else (False, False, False, False)

            for x in range(element["x_repeat"]):
                for y in range(element["y_repeat"]):
                    img_rect_pattern.rounded_rectangle(
                        [(element['x_start'] + x * (element['x_offset'] + element['x_size']),
                          element['y_start'] + y * (element['y_offset'] + element['y_size'])),
                         (element['x_start'] + x * (element['x_offset'] + element['x_size'])
                          + element['x_size'], element['y_start'] + y * (element['y_offset']
                                                                         + element['y_size']) + element['y_size'])],
                        fill=fill, outline=outline, width=width, radius=radius, corners=corners)

        # circle
        if element["type"] == "circle":
            check_for_missing_required_arguments(element, ["x", "y", "radius"], "circle")
            img_circle = ImageDraw.Draw(img)
            fill = get_index_color(element['fill']) if 'fill' in element else None
            outline = get_index_color(element['outline']) if 'outline' in element else "black"
            width = element['width'] if 'width' in element else 1
            img_circle.circle((element['x'], element['y']), element['radius'], fill=fill, outline=outline, width=width)

        # ellipse
        if element["type"] == "ellipse":
            check_for_missing_required_arguments(element, ["x_start", "x_end", "y_start", "y_end"], "ellipse")
            img_ellipse = ImageDraw.Draw(img)
            fill = get_index_color(element['fill']) if 'fill' in element else None
            outline = get_index_color(element['outline']) if 'outline' in element else "black"
            width = element['width'] if 'width' in element else 1
            img_ellipse.ellipse([(element['x_start'], element['y_start']), (element['x_end'], element['y_end'])],
                                fill=fill, outline=outline, width=width)

        # text
        if element["type"] == "text":
            check_for_missing_required_arguments(element, ["x", "value"], "text")
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            size = element.get('size', 20)
            font = element.get('font', "ppb.ttf")
            font_file = os.path.join(os.path.dirname(__file__), font)
            font = ImageFont.truetype(font_file, size)
            if not "y" in element:
                akt_pos_y = pos_y + element.get('y_padding', 10)
            else:
                akt_pos_y = element['y']
            color = element.get('color', "black")
            anchor = element.get('anchor', '')
            align = element.get('align', "left")
            spacing = element.get('spacing', 5)
            stroke_width = element.get('stroke_width', 0)
            stroke_fill = element.get('stroke_fill', 'white')
            if "max_width" in element:
                text = get_wrapped_text(str(element['value']), font, line_length=element['max_width'])
            else:
                text = str(element['value'])
            anchor = anchor or ('la' if '\n' in text else 'lt')
            d.text((element['x'], akt_pos_y), text, fill=get_index_color(color), font=font, anchor=anchor, align=align,
                   spacing=spacing, stroke_width=stroke_width, stroke_fill=stroke_fill)
            textbbox = d.textbbox((element['x'], akt_pos_y), text, font=font, anchor=anchor, align=align,
                                  spacing=spacing, stroke_width=stroke_width)
            pos_y = textbbox[3]
        if element["type"] == "multiline":
            check_for_missing_required_arguments(element, ["x", "value", "delimiter"], "multiline")
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            size = element.get('size', 20)
            font = element.get('font', "ppb.ttf")
            font_file = os.path.join(os.path.dirname(__file__), font)
            font = ImageFont.truetype(font_file, size)
            color = element.get('color', "black")
            anchor = element.get('anchor', "lm")
            stroke_width = element.get('stroke_width', 0)
            stroke_fill = element.get('stroke_fill', 'white')
            _LOGGER.debug("Got Multiline string: %s with delimiter: %s" % (element['value'], element["delimiter"]))
            lst = element['value'].replace("\n", "").split(element["delimiter"])
            pos = element.get('start_y', pos_y + element.get('y_padding', 10))
            for elem in lst:
                _LOGGER.debug("String: %s" % (elem))
                d.text((element['x'], pos), str(elem), fill=get_index_color(color), font=font, anchor=anchor,
                       stroke_width=stroke_width, stroke_fill=stroke_fill)
                pos = pos + element['offset_y']
            pos_y = pos
        # icon
        if element["type"] == "icon":
            check_for_missing_required_arguments(element, ["x", "y", "value", "size"], "icon")
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            # ttf from https://github.com/Templarian/MaterialDesign-Webfont/blob/master/fonts/materialdesignicons-webfont.ttf
            font_file = os.path.join(os.path.dirname(__file__), 'materialdesignicons-webfont.ttf')
            meta_file = os.path.join(os.path.dirname(
                __file__), "materialdesignicons-webfont_meta.json")
            f = open(meta_file)
            data = json.load(f)
            chr_hex = ""
            value = element['value']
            if value.startswith("mdi:"):
                value = value[4:]
            for icon in data:
                if icon['name'] == value:
                    chr_hex = icon['codepoint']
                    break
            if chr_hex == "":
                for icon in data:
                    if value in icon['aliases']:
                        chr_hex = icon['codepoint']
                        break
            if chr_hex == "":
                raise HomeAssistantError("Non valid icon used: " + value)
            stroke_width = element.get('stroke_width', 0)
            stroke_fill = element.get('stroke_fill', 'white')
            font = ImageFont.truetype(font_file, element['size'])
            anchor = element['anchor'] if 'anchor' in element else "la"
            fill = get_index_color(element['color']) if 'color' in element \
                else get_index_color(element['fill']) if 'fill' in element else "black"
            d.text((element['x'], element['y']), chr(int(chr_hex, 16)), fill=fill, font=font,
                   anchor=anchor, stroke_width=stroke_width, stroke_fill=stroke_fill)
        # dlimg
        if element["type"] == "dlimg":
            check_for_missing_required_arguments(element, ["x", "y", "url", "xsize", "ysize"], "dlimg")
            url = element['url']
            pos_x = element['x']
            pos_y = element['y']
            x_size = element['xsize']
            y_size = element['ysize']
            rotate2 = element['rotate'] if 'rotate' in element else 0
            res = [x_size, y_size]
            imgdl = ""
            if "http://" in url or "https://" in url:
                response = requests.get(url)
                imgdl = Image.open(io.BytesIO(response.content))
            elif "data:" in url:
                s = url[5:]
                if not s or ',' not in s:
                    raise HomeAssistantError('invalid data url')
                media_type, _, raw_data = s.partition(',')
                is_base64_encoded = media_type.endswith(';base64')
                if is_base64_encoded:
                    media_type = media_type[:-7]
                    missing_padding = '=' * (-len(raw_data) % 4)
                    if missing_padding:
                        raw_data += missing_padding
                    try:
                        data = base64.b64decode(raw_data)
                    except ValueError as exc:
                        raise HomeAssistantError('invalid base64 in data url') from exc
                else:
                    # Note: unquote_to_bytes() does not raise exceptions for invalid
                    # or partial escapes, so there is no error handling here.
                    data = urllib.parse.unquote_to_bytes(raw_data)
                imgdl = Image.open(io.BytesIO(data))
            else:
                imgdl = Image.open(url)

            if rotate2 != 0:
                imgdl = imgdl.rotate(-rotate2, expand=1)
            width2, height2 = imgdl.size
            if width2 != res[0] or height2 != res[1]:
                imgdl = imgdl.resize((res[0], res[1]))
            imgdl = imgdl.convert("RGBA")
            temp_image = Image.new("RGBA", img.size)
            temp_image.paste(imgdl, (pos_x, pos_y), imgdl)
            img = Image.alpha_composite(img, temp_image)
            img.convert('RGBA')
        # qrcode
        if element["type"] == "qrcode":
            check_for_missing_required_arguments(element, ["x", "y", "data"], "qrcode")
            data = element['data']
            pos_x = element['x']
            pos_y = element['y']
            color = element['color'] if 'color' in element else "black"
            bg_color = element['bgcolor'] if 'bgcolor' in element else "white"
            border = element['border'] if 'border' in element else 1
            box_size = element['boxsize'] if 'boxsize' in element else 2
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=box_size,
                border=border,
            )
            qr.add_data(data)
            qr.make(fit=True)
            qr_image = qr.make_image(fill_color=color, back_color=bg_color)
            position = (pos_x, pos_y)
            qr_image = qr_image.convert("RGBA")
            img.paste(qr_image, position, qr_image)
            img.convert('RGBA')
        # diagram
        if element["type"] == "diagram":
            img_draw = ImageDraw.Draw(img)
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            font = element.get('font', "ppb.ttf")
            pos_x = element['x']
            pos_y = element['y']
            width = element.get('width', canvas_width)
            height = element['height']
            offset_lines = element.get('margin', 20)
            # x axis line
            img_draw.line(
                [(pos_x + offset_lines, pos_y + height - offset_lines), (pos_x + width, pos_y + height - offset_lines)],
                fill=get_index_color('black'), width=1)
            # y axis line
            img_draw.line([(pos_x + offset_lines, pos_y), (pos_x + offset_lines, pos_y + height - offset_lines)],
                          fill=get_index_color('black'), width=1)
            if "bars" in element:
                bar_margin = element["bars"].get('margin', 10)
                bars = element["bars"]["values"].split(";")
                bar_count = len(bars)
                bar_width = math.floor((width - offset_lines - ((bar_count + 1) * bar_margin)) / bar_count)
                _LOGGER.info("Found %i in bars width: %i" % (bar_count, bar_width))
                size = element["bars"].get('legend_size', 10)
                font_file = os.path.join(os.path.dirname(__file__), font)
                font = ImageFont.truetype(font_file, size)
                legend_color = element["bars"].get('legend_color', "black")
                max_val = 0
                for bar in bars:
                    name, value = bar.split(",", 1)
                    if int(value) > max_val:
                        max_val = int(value)
                height_factor = (height - offset_lines) / max_val
                bar_pos = 0
                for bar in bars:
                    name, value = bar.split(",", 1)
                    # legend bottom
                    x_pos = ((bar_margin + bar_width) * bar_pos) + offset_lines
                    d.text((x_pos + (bar_width / 2), pos_y + height - offset_lines / 2), str(name),
                           fill=get_index_color(legend_color), font=font, anchor="mm")
                    img_draw.rectangle([(x_pos, pos_y + height - offset_lines - (height_factor * int(value))),
                                        (x_pos + bar_width, pos_y + height - offset_lines)],
                                       fill=get_index_color(element["bars"]["color"]))
                    bar_pos = bar_pos + 1
        # plot
        if element["type"] == "plot":
            check_for_missing_required_arguments(element, ["data"], "plot")
            img_draw = ImageDraw.Draw(img)
            img_draw.fontmode = "1"
            # Obtain drawing region, assume whole canvas if nothing is given
            x_start = element.get("x_start", 0)
            y_start = element.get("y_start", 0)
            x_end = element.get("x_end", canvas_width - 1 - x_start)
            y_end = element.get("y_end", canvas_height - 1 - x_start)
            width = x_end - x_start + 1
            height = y_end - y_start + 1
            # The duration of history to look at (default 1 day)
            duration = timedelta(seconds=element.get("duration", 60 * 60 * 24))

            end = dt.utcnow()
            start = end - duration
            # The label font and size
            size = element.get("size", 10)
            font_file = element.get("font", "ppb.ttf")
            abs_font_file = os.path.join(os.path.dirname(__file__), font_file)
            font = ImageFont.truetype(abs_font_file, size)
            # The value legend
            y_legend = element.get("ylegend", dict())
            if y_legend is None:
                y_legend_width = 0
            else:
                y_legend_width = y_legend.get("width", -1)
                y_legend_color = y_legend.get("color", "black")
                y_legend_pos = y_legend.get("position", "left")
                if y_legend_pos not in ("left", "right", None):
                    y_legend_pos = "left"
                y_legend_font_file = y_legend.get("font", font_file)
                y_legend_size = y_legend.get("size", size)
                if y_legend_font_file != font_file or y_legend_size != size:
                    y_legend_abs_font_file = os.path.join(os.path.dirname(__file__), y_legend_font_file)
                    y_legend_font = ImageFont.truetype(y_legend_abs_font_file, y_legend_size)
                else:
                    y_legend_font = font
            # The value axis
            y_axis = element.get("yaxis", dict())
            if y_axis is None:
                y_axis_width = 0
                y_axis_tick_width = 0
            else:
                y_axis_width = y_axis.get("width", 1)
                y_axis_color = y_axis.get("color", "black")
                y_axis_tick_width = y_axis.get("tick_width", 2)
                y_axis_tick_every = float(y_axis.get("tick_every", 1))
                y_axis_grid = y_axis.get("grid", 5)
                y_axis_grid_color = y_axis.get("grid_color", "black")
            # The minimum and maximum values that are always shown
            min_v = element.get("low", None)
            max_v = element.get("high", None)
            # Obtain all states of all given entities in the given duration
            all_states = get_significant_states(hass, start_time=start,
                                                entity_ids=[plot["entity"] for plot in element["data"]],
                                                significant_changes_only=False, minimal_response=True,
                                                no_attributes=False)

            # prepare data and obtain min_v and max_v with it
            raw_data = []
            for plot in element["data"]:
                if not (plot["entity"] in all_states):
                    raise HomeAssistantError("no recorded data found for " + plot["entity"])
                states = all_states[plot["entity"]]
                state_obj = states[0]
                states[0] = {"state": state_obj.state, "last_changed": str(state_obj.last_changed)}
                states = [(datetime.fromisoformat(s["last_changed"]), float(s["state"])) for s in states if
                          is_decimal(s["state"])]

                min_v_local, max_v_local = min_max([s[1] for s in states])
                min_v = min(min_v or min_v_local, min_v_local)
                max_v = max(max_v or max_v_local, max_v_local)

                raw_data.append(states)

            max_v = math.ceil(max_v)
            min_v = math.floor(min_v)
            # Prevent division by zero errors
            if max_v == min_v:
                min_v -= 1
            spread = max_v - min_v

            # calculate ylenged_width if it should be automatically determined
            if y_legend_width == -1:
                y_legend_width = math.ceil(max(
                    img_draw.textlength(str(max_v), font=y_legend_font),
                    img_draw.textlength(str(min_v), font=y_legend_font),
                ))

            # effective diagram dimensions
            diag_x = x_start + (y_legend_width if y_legend_pos == "left" else 0)
            diag_y = y_start
            diag_width = width - y_legend_width
            diag_height = height

            if element.get("debug", False):
                img_draw.rectangle([(x_start, y_start), (x_end, y_end)], fill=None, outline=get_index_color("black"),
                                   width=1)
                img_draw.rectangle([(diag_x, diag_y), (diag_x + diag_width - 1, diag_y + diag_height - 1)], fill=None,
                                   outline=get_index_color("red"), width=1)

            # print y grid
            if y_axis is not None:
                if y_axis_grid is not None:
                    grid_points = []
                    curr = min_v
                    while curr <= max_v:
                        curr_y = round(diag_y + (1 - ((curr - min_v) / spread)) * (diag_height - 1))
                        grid_points.extend((x, curr_y) for x in range(diag_x, diag_x + diag_width, y_axis_grid))
                        curr += y_axis_tick_every
                    img_draw.point(grid_points, fill=get_index_color(y_axis_grid_color))

            # scale data and draw plot
            for plot, data in zip(element["data"], raw_data):
                xy_raw = []
                for time, value in data:
                    rel_time = (time - start) / duration
                    rel_value = (value - min_v) / spread
                    xy_raw.append((round(diag_x + rel_time * (diag_width - 1)),
                                   round(diag_y + (1 - rel_value) * (diag_height - 1))))
                # smooth out the data, i.e. if x values appear multiple times, only add them once with the average of all y values
                xy = []
                last_x = None
                ys = []
                for x, y in xy_raw:
                    if x != last_x:
                        if ys:
                            xy.append((last_x, round(sum(ys) / len(ys))))
                            ys = []
                        last_x = x
                    ys.append(y)
                if ys:
                    xy.append((last_x, round(sum(ys) / len(ys))))

                img_draw.line(xy, fill=get_index_color(plot.get("color", "black")), width=plot.get("width", 1),
                              joint=plot.get("joint", None))

            # print y legend
            if y_legend_pos == "left":
                img_draw.text((x_start, y_start), str(max_v), fill=get_index_color(y_legend_color), font=y_legend_font,
                              anchor="lt")
                img_draw.text((x_start, y_end), str(min_v), fill=get_index_color(y_legend_color), font=y_legend_font,
                              anchor="ls")
            elif y_legend_pos == "right":
                img_draw.text((x_end, y_start), str(max_v), fill=get_index_color(y_legend_color), font=y_legend_font,
                              anchor="rt")
                img_draw.text((x_end, y_end), str(min_v), fill=get_index_color(y_legend_color), font=y_legend_font,
                              anchor="rs")
            # print y axis
            if y_axis is not None:
                img_draw.rectangle([(diag_x, diag_y), (diag_x + y_axis_width - 1, diag_y + diag_height - 1)], width=0,
                                   fill=get_index_color(y_axis_color))
                if y_axis_tick_width > 0:
                    curr = min_v
                    while curr <= max_v:
                        curr_y = round(diag_y + (1 - ((curr - min_v) / spread)) * (diag_height - 1))
                        img_draw.rectangle(
                            [(diag_x + y_axis_width, curr_y), (diag_x + y_axis_width + y_axis_tick_width - 1, curr_y)],
                            width=0, fill=get_index_color(y_axis_color))
                        curr += y_axis_tick_every

        # progress_bar
        if element["type"] == "progress_bar":
            check_for_missing_required_arguments(element, ["x_start", "x_end", "y_start", "y_end", "progress"],
                                                 "progress_bar")
            img_draw = ImageDraw.Draw(img)

            x_start = element['x_start']
            y_start = element['y_start']
            x_end = element['x_end']
            y_end = element['y_end']
            progress = element['progress']
            direction = element.get('direction', 'right')
            background = get_index_color(element.get('background', 'white'))
            fill = get_index_color(element.get('fill', 'red'))
            outline = get_index_color(element.get('outline', 'black'))
            width = element.get('width', 1)
            show_percentage = element.get('show_percentage', False)

            # background
            img_draw.rectangle([(x_start, y_start), (x_end, y_end)], fill=background, outline=outline, width=width)

            # Calculate progress dimensions
            if direction in ['right', 'left']:
                progress_width = int((x_end - x_start) * (progress / 100))
                progress_height = y_end - y_start
            else:  # up or down
                progress_width = x_end - x_start
                progress_height = int((y_end - y_start) * (progress / 100))

            # Draw progress
            if direction == 'right':
                img_draw.rectangle([(x_start, y_start), (x_start + progress_width, y_end)], fill=fill)
            elif direction == 'left':
                img_draw.rectangle([(x_end - progress_width, y_start), (x_end, y_end)], fill=fill)
            elif direction == 'up':
                img_draw.rectangle([(x_start, y_end - progress_height), (x_end, y_end)], fill=fill)
            elif direction == 'down':
                img_draw.rectangle([(x_start, y_start), (x_end, y_start + progress_height)], fill=fill)

            img_draw.rectangle([(x_start, y_start), (x_end, y_end)], fill=None, outline=outline, width=width)

            # display percentage text if enabled
            if show_percentage:
                font_size = min(y_end - y_start - 4, x_end - x_start - 4, 20)  # Adjust max font size as needed
                font = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'ppb.ttf'), font_size)
                percentage_text = f"{progress}%"

                # Calculate text position
                text_bbox = img_draw.textbbox((0, 0), percentage_text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                text_x = (x_start + x_end - text_width) / 2
                text_y = (y_start + y_end - text_height) / 2

                # text color based on progress
                if progress > 50:
                    text_color = background
                else:
                    text_color = fill

                # Draw text
                img_draw.text((text_x, text_y), percentage_text, font=font, fill=text_color,
                              anchor='lt')  # TODO anchor is still off

    # post processing
    img = img.rotate(rotate, expand=True)
    rgb_image = img.convert('RGB')
    path_a = os.path.join(os.path.dirname(__file__), entity_id + '.jpg')
    path_b = get_image_path(hass, entity_id)
    path_c = get_image_folder(hass)
    file_exists = os.path.exists(path_c)
    if not file_exists:
        os.makedirs(path_c)
    rgb_image.save(path_a, format='JPEG', quality="maximum")
    shutil.copy2(path_a, path_b)
    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()
    return byte_im


# adds an image to the queue
def queue_image(url, content):
    queue.append([url, content])


# if the timing is right, processes the queue
def handle_queue():
    global running
    if running:
        return True
    if len(queue) == 0:
        return True
    running = True;
    time_between_calls = 10
    file_path = os.path.join(os.path.dirname(__file__), "lastapinteraction" + '.txt')
    file_content = "0";
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            file_content = file.read()
    current_time = round(datetime.timestamp(datetime.now()))
    if round(float(file_content)) + time_between_calls < current_time:
        with open(file_path, 'w') as file:
            file.write(str(datetime.timestamp(datetime.now())))
        tp = queue.pop(0)
        running = False;
        response = requests.post(tp[0], headers={'Content-Type': tp[1].content_type}, data=tp[1])
        if response.status_code != 200:
            _LOGGER.warning(response.status_code)
            queue.append(tp)
    running = False;


# upload an image to the tag
def upload_image(img, mac, ip, dither, ttl, preloadtype, preloadlut, hass):
    setup(hass, not_setup)
    url = "http://" + ip + "/imgupload"
    mp_encoder = ""
    if preloadtype == 0:
        mp_encoder = MultipartEncoder(
            fields={
                'mac': mac,
                'contentmode': "25",
                'dither': "1" if dither else "0",
                'ttl': str(ttl),
                'image': ('image.jpg', img, 'image/jpeg'),
            }
        )
    else:
        mp_encoder = MultipartEncoder(
            fields={
                'mac': mac,
                'contentmode': "25",
                'dither': "1" if dither else "0",
                'ttl': str(ttl),
                'preloadtype': str(preloadtype),
                'preloadlut': str(preloadlut),
                'image': ('image.jpg', img, 'image/jpeg'),
            }
        )
    queue_image(url, mp_encoder)


# upload a cmd to the tag
def upload_cfg(cfg, mac, content_mode, ip):
    url = "http://" + ip + "/get_db?mac=" + mac
    response = requests.get(url)
    respjson = json.loads(response.text)
    alias = respjson["tags"][0]["alias"];
    rotate = respjson["tags"][0]["rotate"];
    lut = respjson["tags"][0]["lut"];
    url = "http://" + ip + "/save_cfg"
    mp_encoder = MultipartEncoder(
        fields={
            'mac': mac,
            'contentmode': str(content_mode),
            'modecfgjson': cfg,
            'alias': alias,
            'rotate': str(rotate),
            'lut': str(lut),
        }
    )
    response = requests.post(url, headers={'Content-Type': mp_encoder.content_type}, data=mp_encoder)
    if response.status_code != 200:
        _LOGGER.warning(response.status_code)


# 5 line text generator for 1.54 esls (deprecated)
def generate_5_line(entity_id, service, hass):
    entity = hass.states.get(entity_id)
    if not (entity and 'width' in entity.attributes):
        raise HomeAssistantError(
            "id was not found yet, please wait for the display to check in at least once " + entity_id)
    line1 = service.data.get("line1", "")
    line2 = service.data.get("line2", "")
    line3 = service.data.get("line3", "")
    line4 = service.data.get("line4", "")
    line5 = service.data.get("line5", "")
    border = service.data.get("border", "w")
    format1 = service.data.get("format1", "mwwb")
    format2 = service.data.get("format2", "mwwb")
    format3 = service.data.get("format3", "mwwb")
    format4 = service.data.get("format4", "mwwb")
    format5 = service.data.get("format5", "mwwb")
    w = 152
    h = 152
    img = Image.new('RGBA', (w, h), color=white)
    d = ImageDraw.Draw(img)
    # we don't want interpolation
    d.fontmode = "1"
    # border
    d.rectangle([(0, 0), (w - 1, h - 1)], fill=white, outline=get_index_color(border))
    # text backgrounds
    d.rectangle([(1, 1), (150, 30)], fill=get_index_color(format1[1]), outline=get_index_color(format1[2]))
    d.rectangle([(1, 31), (150, 60)], fill=get_index_color(format2[1]), outline=get_index_color(format2[2]))
    d.rectangle([(1, 61), (150, 90)], fill=get_index_color(format3[1]), outline=get_index_color(format3[2]))
    d.rectangle([(1, 91), (150, 120)], fill=get_index_color(format4[1]), outline=get_index_color(format4[2]))
    d.rectangle([(1, 121), (150, 150)], fill=get_index_color(format5[1]), outline=get_index_color(format5[2]))
    # text lines
    d = generate_text(d, str(line1), get_index_color(format1[3]), format1[0], 0)
    d = generate_text(d, str(line2), get_index_color(format2[3]), format2[0], 30)
    d = generate_text(d, str(line3), get_index_color(format3[3]), format3[0], 60)
    d = generate_text(d, str(line4), get_index_color(format4[3]), format4[0], 90)
    d = generate_text(d, str(line5), get_index_color(format5[3]), format5[0], 120)
    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")
    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()
    return byte_im


# 4 line text generator for 2.9 esls (deprecated)
def generate_4_line(entity_id, service, hass):
    entity = hass.states.get(entity_id)
    if not (entity and 'width' in entity.attributes):
        raise HomeAssistantError(
            "id was not found yet, please wait for the display to check in at least once " + entity_id)
    line1 = service.data.get("line1", "")
    line2 = service.data.get("line2", "")
    line3 = service.data.get("line3", "")
    line4 = service.data.get("line4", "")
    border = service.data.get("border", "w")
    format1 = service.data.get("format1", "mwwb")
    format2 = service.data.get("format2", "mwwb")
    format3 = service.data.get("format3", "mwwb")
    format4 = service.data.get("format4", "mwwb")
    w = 296
    h = 128
    img = Image.new('RGBA', (w, h), color=white)
    d = ImageDraw.Draw(img)
    # we don't want interpolation
    d.fontmode = "1"
    # border
    d.rectangle([(0, 0), (w - 2, h - 2)], fill=get_index_color(border))
    # text backgrounds
    d.rectangle([(2, 2), (292, 32)], fill=get_index_color(format1[1]), outline=get_index_color(format1[2]))
    d.rectangle([(2, 33), (292, 63)], fill=get_index_color(format2[1]), outline=get_index_color(format2[2]))
    d.rectangle([(2, 64), (292, 94)], fill=get_index_color(format3[1]), outline=get_index_color(format3[2]))
    d.rectangle([(2, 95), (292, 124)], fill=get_index_color(format4[1]), outline=get_index_color(format4[2]))
    # text lines
    d = generate_text2(d, str(line1), get_index_color(format1[3]), format1[0], 2)
    d = generate_text2(d, str(line2), get_index_color(format2[3]), format2[0], 33)
    d = generate_text2(d, str(line3), get_index_color(format3[3]), format3[0], 64)
    d = generate_text2(d, str(line4), get_index_color(format4[3]), format4[0], 95)
    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")
    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()

    return byte_im


# handles Text alignment (deprecated)
def generate_text(d, text, col, just, yofs):
    rbm = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'rbm.ttf'), 11)
    ppb = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'ppb.ttf'), 23)
    x = 76
    if just == "l":
        x = 3
    if just == "r":
        x = 147
    if "\n" in text:
        split1 = text.split("\n")[0]
        split2 = text.split("\n")[1]
        d.text((x, 8 + yofs), split1, fill=col, anchor=just + "m", font=rbm)
        d.text((x, 22 + yofs), split2, fill=col, anchor=just + "m", font=rbm)
    elif d.textlength(text, font=ppb) < 147:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=ppb)
    else:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=rbm)
    return d


# handles Text alignment (deprecated)
def generate_text2(d, text, col, just, yofs):
    rbm = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'rbm.ttf'), 11)
    ppb = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'ppb.ttf'), 23)
    x = 148
    if just == "l":
        x = 3
    if just == "r":
        x = 290
    if "\n" in text:
        split1 = text.split("\n")[0]
        split2 = text.split("\n")[1]
        d.text((x, 8 + yofs), split1, fill=col, anchor=just + "m", font=rbm)
        d.text((x, 22 + yofs), split2, fill=col, anchor=just + "m", font=rbm)
    elif d.textlength(text, font=ppb) < 280:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=ppb)
    else:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=rbm)
    return d


def check_for_missing_required_arguments(element, required_keys, func_name):
    missing_keys = []
    for key in required_keys:
        if key not in element:
            missing_keys.append(key)
    if missing_keys:
        raise HomeAssistantError(f"Missing required argument(s) '{', '.join(missing_keys)}' in '{func_name}'")


def rounded_corners(corner_string):
    if corner_string == "all":
        return True, True, True, True

    corners = corner_string.split(",")
    corner_map = {
        "top_left": 0,
        "top_right": 1,
        "bottom_right": 2,
        "bottom_left": 3
    }
    result = [False] * 4
    for corner in corners:
        corner = corner.strip()
        if corner in corner_map:
            result[corner_map[corner]] = True

    return tuple(result)
