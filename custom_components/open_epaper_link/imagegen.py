from __future__ import annotations

import io
import logging
import os
import pprint
import json
import requests
from PIL import Image, ImageDraw, ImageFont
from requests_toolbelt.multipart.encoder import MultipartEncoder

_LOGGER = logging.getLogger(__name__)

# font imports
rbmp = os.path.join(os.path.dirname(__file__), 'rbm.ttf')
ppbp = os.path.join(os.path.dirname(__file__), 'ppb.ttf')
rbm = ImageFont.truetype(rbmp, 11)
ppb = ImageFont.truetype(ppbp, 23)

# color definitions for picture generation
color_palette = [
    255, 255, 255,  # white
    0, 0, 0,        # black
    255, 0, 0       # red
]

white = 0
black = 1
red = 2


splitth = 147
splitth2 = 280

# img downloader
def downloadimg(entity_id, service, hass):
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

def displayimg(entity_id, service, hass):
    file = service.data.get("file", "")
    rotate = service.data.get("rotation", 0)

    # get image
#    response = requests.get(file)
    response = open(file, "r")
    
    # load the res of the esl
    res = [hass.states.get(entity_id).attributes['width'], hass.states.get(entity_id).attributes['height']]

    img = Image.open(io.BytesIO(response.read()))
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

def get_wrapped_text(text: str, font: ImageFont.ImageFont,
                     line_length: int):
        lines = ['']
        for word in text.split():
            line = f'{lines[-1]} {word}'.strip()
            if font.getlength(line) <= line_length:
                lines[-1] = line
            else:
                lines.append(word)
        return '\n'.join(lines)

# converts a color name to the corresponding color index for the palette
def getIndexColor(color):
    color_str = str(color)
    if color_str == "black" or color_str == "b":
        return black
    elif color_str == "red" or color_str == "r":
        return red
    else:
        return white

# custom image generator
def customimage(entity_id, service, hass):
        
    payload = service.data.get("payload", "")
    rotate = service.data.get("rotate", "0")
    background = getIndexColor(service.data.get("background","white"))

    canvas_width = hass.states.get(entity_id).attributes['width']
    canvas_height = hass.states.get(entity_id).attributes['height']

    if rotate == 0:
        img = Image.new('P', (canvas_width, canvas_height), color=background)
    elif rotate == 90:
        img = Image.new('P', (canvas_height, canvas_width), color=background)
    elif rotate == 180:
        img = Image.new('P', (canvas_width, canvas_height), color=background)
    elif rotate == 270:
        img = Image.new('P', (canvas_height, canvas_width), color=background)
    else:
        img = Image.new('P', (canvas_width, canvas_height), color=background)

    pos_y = 0

    img.putpalette(color_palette)

    d = ImageDraw.Draw(img)
    d.fontmode = "1"

    for element in payload:
        if element["type"] == "line":
            img_line = ImageDraw.Draw(img)  

            if not "y_start" in element:
                if "y_padding" in element:
                    y_start = pos_y + element["y_padding"]
                else:
                    y_start = pos_y
                y_end = y_start
            else:
                y_start = element["y_start"]
                y_end = element["y_end"]


            img_line.line([(element['x_start'],y_start),(element['x_end'],y_end)],fill = getIndexColor(element['fill']), width=element['width'])
            pos_y = y_start
        
        if element["type"] == "rectangle":
            img_rect = ImageDraw.Draw(img)  
            img_rect.rectangle([(element['x_start'],element['y_start']),(element['x_end'],element['y_end'])],fill = getIndexColor(element['fill']), outline=getIndexColor(element['outline']), width=element['width'])

        if element["type"] == "text":

            if not "size" in element:
                size = 20
            else: 
                size = element['size']  

            if not "font" in element:
                font = "ppb.ttf"
            else: 
                font = element['font']

            font_file = os.path.join(os.path.dirname(__file__), font)
            font = ImageFont.truetype(font_file, size)

            if not "y" in element:
                if not "y_padding" in element:
                    akt_pos_y = pos_y + 10
                else: 
                    akt_pos_y = pos_y + element['y_padding']
            else:
                akt_pos_y = element['y']

            if not "color" in element:
                color = "black"
            else: 
                color = element['color']
            
            if not "anchor" in element:
                anchor = "lt"
            else: 
                anchor = element['anchor']
            
            if not "align" in element:
                align = "left"
            else: 
                align = element['align']
            
            if not "spacing" in element:
                spacing = 5
            else: 
                spacing = element['spacing']

            if "max_width" in element:
                text = get_wrapped_text(str(element['value']), font, line_length=element['max_width'])
                anchor = None
            else:
                text = str(element['value'])

            d.text((element['x'],  akt_pos_y), text, fill=getIndexColor(color), font=font, anchor=anchor, align=align, spacing=spacing)
            textbbox = d.textbbox((element['x'],  akt_pos_y), text, font=font, anchor=anchor, align=align, spacing=spacing)
            pos_y = textbbox[3]

        if element["type"] == "multiline":
            font_file = os.path.join(os.path.dirname(__file__), element['font'])
            font = ImageFont.truetype(font_file, element['size'])
            _LOGGER.debug("Got Multiline string: %s with delimiter: %s" % (element['value'],element["delimiter"]))
            lst = element['value'].replace("\n","").split(element["delimiter"])

            if not "start_y" in element:
                pos = pos_y + + element['y_padding']
            else:
                pos = element['start_y']

            for elem in lst:
                _LOGGER.debug("String: %s" % (elem))
                d.text((element['x'], pos ), str(elem), fill=getIndexColor(element['color']), font=font)
                pos = pos + element['offset_y']
            
            pos_y = pos

        if element["type"] == "icon":
            # ttf from https://github.com/Templarian/MaterialDesign-Webfont/blob/master/fonts/materialdesignicons-webfont.ttf
            font_file = os.path.join(os.path.dirname(__file__), 'materialdesignicons-webfont.ttf')
            meta_file = os.path.join(os.path.dirname(__file__), "materialdesignicons-webfont_meta.json") 
            f = open(meta_file) 
            data = json.load(f)
            chr_hex = ""
            for icon in data:
                if icon['name'] == element['value']:
                    chr_hex = icon['codepoint']
                    break

            font = ImageFont.truetype(font_file, element['size'])
            d.text((element['x'],  element['y']), chr(int(chr_hex, 16)), fill=getIndexColor(element['color']), font=font)
        
        if element["type"] == "diagram":
            img_draw = ImageDraw.Draw(img)

            if not "font" in element:
                font = "ppb.ttf"
            else:
                font = element['font']

            pos_x = element['x']
            pos_y = element['y']

            if not "width" in element:
                width = canvas_width
            else:
                width = element['width']
            
            height = element['height']

            if not "margin" in element:
                offset_lines = 20
            else:
                offset_lines = element["margin"]

            # x axis line
            img_draw.line([(pos_x+offset_lines, pos_y+height-offset_lines),(pos_x+width,pos_y+height-offset_lines)],fill = getIndexColor('black'), width = 1)
            # y axis line
            img_draw.line([(pos_x+offset_lines, pos_y),(pos_x+offset_lines,pos_y+height-offset_lines)],fill = getIndexColor('black'), width = 1)

            if "bars" in element:
                if not "margin" in element["bars"]:
                    bar_margin = 10
                else:
                    bar_margin = element["bars"]["margin"]

                bars = element["bars"]["values"].split(";")
                barcount = len(bars)
                bar_width = math.floor((width - offset_lines - ((barcount + 1) * bar_margin)) / barcount)
                _LOGGER.info("Found %i in bars width: %i" % (barcount,bar_width))

                if not "legend_size" in element["bars"]:
                    size = 10
                else:
                    size = element["bars"]["legend_size"]

                font_file = os.path.join(os.path.dirname(__file__), font)
                font = ImageFont.truetype(font_file, size)

                if not "legend_color" in element["bars"]:
                    legend_color = "black"
                else:
                    legend_color = element["bars"]["legend_color"]

                max_val = 0
                for bar in bars:
                    name, value  = bar.split(",",1)
                    if int(value) > max_val:
                        max_val = int(value)

                height_factor = (height - offset_lines) / max_val
                bar_pos = 0
                for bar in bars:
                    name, value  = bar.split(",",1)

                    # legend bottom
                    x_pos = ((bar_margin + bar_width) * bar_pos) + offset_lines
                    d.text((x_pos + (bar_width/2),  pos_y + height - offset_lines /2), str(name), fill=getIndexColor(legend_color), font=font, anchor="mm")
                    img_draw.rectangle([(x_pos, pos_y+height-offset_lines-(height_factor*int(value))),(x_pos+bar_width, pos_y+height-offset_lines)],fill = getIndexColor(element["bars"]["color"]))
                    bar_pos = bar_pos + 1

    img = img.rotate(rotate, expand=True)

    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")

    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()

    return byte_im

# 5 line text generator for 1.54 esls
def gen5line(entity_id, service, hass):
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

    img = Image.new('P', (w, h), color=white)
    img.putpalette(color_palette)
    
    d = ImageDraw.Draw(img)
    # we don't want interpolation
    d.fontmode = "1"
    # border
    d.rectangle([(0, 0), (w - 1, h - 1)], fill=white, outline=getIndexColor(border))
    # text backgrounds
    d.rectangle([(1, 1), (150, 30)], fill=getIndexColor(format1[1]), outline=getIndexColor(format1[2]))
    d.rectangle([(1, 31), (150, 60)], fill=getIndexColor(format2[1]), outline=getIndexColor(format2[2]))
    d.rectangle([(1, 61), (150, 90)], fill=getIndexColor(format3[1]), outline=getIndexColor(format3[2]))
    d.rectangle([(1, 91), (150, 120)], fill=getIndexColor(format4[1]), outline=getIndexColor(format4[2]))
    d.rectangle([(1, 121), (150, 150)], fill=getIndexColor(format5[1]), outline=getIndexColor(format5[2]))
    # text lines
    d = textgen(d, str(line1), getIndexColor(format1[3]), format1[0], 0)
    d = textgen(d, str(line2), getIndexColor(format2[3]), format2[0], 30)
    d = textgen(d, str(line3), getIndexColor(format3[3]), format3[0], 60)
    d = textgen(d, str(line4), getIndexColor(format4[3]), format4[0], 90)
    d = textgen(d, str(line5), getIndexColor(format5[3]), format5[0], 120)

    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")

    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()

    return byte_im


def gen4line(entity_id, service, hass):
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
    img = Image.new('P', (w, h), color=white)
    img.putpalette(color_palette)
    d = ImageDraw.Draw(img)
    # we don't want interpolation
    d.fontmode = "1"
    # border
    d.rectangle([(0, 0), (w - 2, h - 2)], fill=getIndexColor(border))
    # text backgrounds
    d.rectangle([(2, 2), (292, 32)], fill=getIndexColor(format1[1]), outline=getIndexColor(format1[2]))
    d.rectangle([(2, 33), (292, 63)], fill=getIndexColor(format2[1]), outline=getIndexColor(format2[2]))
    d.rectangle([(2, 64), (292, 94)], fill=getIndexColor(format3[1]), outline=getIndexColor(format3[2]))
    d.rectangle([(2, 95), (292, 124)], fill=getIndexColor(format4[1]), outline=getIndexColor(format4[2]))
    # text lines
    d = textgen2(d, str(line1), getIndexColor(format1[3]), format1[0], 2)
    d = textgen2(d, str(line2), getIndexColor(format2[3]), format2[0], 33)
    d = textgen2(d, str(line3), getIndexColor(format3[3]), format3[0], 64)
    d = textgen2(d, str(line4), getIndexColor(format4[3]), format4[0], 95)
    
    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(os.path.dirname(__file__), entity_id + '.jpg'), format='JPEG', quality="maximum")

    buf = io.BytesIO()
    rgb_image.save(buf, format='JPEG', quality="maximum")
    byte_im = buf.getvalue()

    return byte_im


# handles Text alignment
def textgen(d, text, col, just, yofs):
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
    elif d.textlength(text, font=ppb) < splitth:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=ppb)
    else:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=rbm)
    return d


# handles Text alignment
def textgen2(d, text, col, just, yofs):
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
    elif d.textlength(text, font=ppb) < splitth2:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=ppb)
    else:
        d.text((x, 15 + yofs), text, fill=col, anchor=just + "m", font=rbm)
    return d


# upload an image to the tag
def uploadimg(img, mac, ip, dither=False):
    url = "http://" + ip + "/imgupload"
    mp_encoder = MultipartEncoder(
        fields={
            'mac': mac,
            'dither': "1" if dither else "0",
            'image': ('image.jpg', img, 'image/jpeg'),
        }
    )
    response = requests.post(url, headers={'Content-Type': mp_encoder.content_type}, data=mp_encoder)
    if response.status_code != 200:
        _LOGGER.warning(response.status_code)

# upload a cmd to the tag
def uploadcfg(cfg, mac, contentmode, ip):
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
            'contentmode': str(contentmode),
            'modecfgjson': cfg,
            'alias': alias,
            'rotate': str(rotate),
            'lut':str(lut),
        }
    )
    response = requests.post(url, headers={'Content-Type': mp_encoder.content_type}, data=mp_encoder)
    if response.status_code != 200:
        _LOGGER.warning(response.status_code)
