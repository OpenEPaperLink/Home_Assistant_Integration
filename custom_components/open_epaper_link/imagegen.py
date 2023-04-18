from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont
import requests
import io
from requests_toolbelt.multipart.encoder import MultipartEncoder
import logging
from pathlib import Path
import os
_LOGGER = logging.getLogger(__name__)

#font imports
rbmp = os.path.join(os.path.dirname(__file__), 'rbm.ttf')
ppbp = os.path.join(os.path.dirname(__file__), 'ppb.ttf')
rbm = ImageFont.truetype(rbmp, 11)
ppb = ImageFont.truetype(ppbp, 23)
#colour definitions for picture generation
red = (255, 0, 0)
white = (255, 255, 255)
black = (0, 0, 0)
splitth = 147
splitth2 = 280
size0 = [152,152]
size1 = [296,128]
size2 = [400,300]
#img downloader
def downloadimg(url,hwtype,rotate):
    #load the res of the esl
    res = getres(hwtype)
    response = requests.get(url)
    img = Image.open(io.BytesIO(response.content))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    if rotate != 0:
        img = img.rotate(rotate,expand = 1)
    width, height = img.size
    #swap for big display
    if hwtype == "2":
        b = res[0]
        res[0] = res[1]
        res[1] = b
    #open esl expects the image rotated
    if width == res[1] and height == res[0]:
        print("all clear, pass")
    elif width == res[0] and height == res[1]:
        print("90 degree rotation needed")
        img = img.rotate(90,expand = 1)
    else:
        print("rotate + resize required")
        img = img.rotate(90,expand = 1)
        img = img.resize((res[1],res[0]))    
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    byte_im = buf.getvalue()
    #img.save('img.png')
    return byte_im
#hw type to size converter
def getres(hwtype):
   if hwtype == "0":
       return size0
   if hwtype == "1":
       return size1
   if hwtype == "2":
       return size2
#5 line text generator for 1.54 esls
def gen5line(line1,line2,line3,line4,line5,border,format1,format2,format3,format4,format5):
   w = 152
   h = 152
   img = Image.new('RGB', (w, h), color = white)
   d = ImageDraw.Draw(img)
   #we dont want interpolation
   d.fontmode = "1"
   #border
   d.rectangle([(0, 0), (w - 1,h - 1)], fill = white, outline = chartocol(border))
   #text backgrounds
   d.rectangle([(1, 1), (150,30)], fill = chartocol(format1[1]), outline = chartocol(format1[2]))
   d.rectangle([(1, 31), (150,60)], fill = chartocol(format2[1]), outline = chartocol(format2[2]))
   d.rectangle([(1, 61), (150,90)], fill = chartocol(format3[1]), outline = chartocol(format3[2]))
   d.rectangle([(1, 91), (150,120)], fill = chartocol(format4[1]), outline = chartocol(format4[2]))
   d.rectangle([(1, 121), (150,150)], fill = chartocol(format5[1]), outline = chartocol(format5[2]))
   #text lines
   d =  textgen(d,line1,chartocol(format1[3]),format1[0],0)
   d =  textgen(d,line2,chartocol(format2[3]),format2[0],30)
   d =  textgen(d,line3,chartocol(format3[3]),format3[0],60)
   d =  textgen(d,line4,chartocol(format4[3]),format4[0],90)
   d =  textgen(d,line5,chartocol(format5[3]),format5[0],120)
   buf = io.BytesIO()
   img.save(buf, format='JPEG', quality=95)
   byte_im = buf.getvalue()
   #img.save('img.png')
   return byte_im
def gen4line(line1,line2,line3,line4,border,format1,format2,format3,format4):
   w = 296
   h = 128
   img = Image.new('RGB', (w, h), color = white)
   d = ImageDraw.Draw(img)
   #we dont want interpolation
   d.fontmode = "1"
   #border
   d.rectangle([(0, 0), (w - 2,h - 2)], fill = chartocol(border))
   #text backgrounds
   d.rectangle([(2, 2), (292,32)], fill = chartocol(format1[1]), outline = chartocol(format1[2]))
   d.rectangle([(2, 33), (292,63)], fill = chartocol(format2[1]), outline = chartocol(format2[2]))
   d.rectangle([(2, 64), (292,94)], fill = chartocol(format3[1]), outline = chartocol(format3[2]))
   d.rectangle([(2, 95), (292,124)], fill = chartocol(format4[1]), outline = chartocol(format4[2]))
   #text lines
   d =  textgen2(d,line1,chartocol(format1[3]),format1[0],2)
   d =  textgen2(d,line2,chartocol(format2[3]),format2[0],33)
   d =  textgen2(d,line3,chartocol(format3[3]),format3[0],64)
   d =  textgen2(d,line4,chartocol(format4[3]),format4[0],95)
   buf = io.BytesIO()
   img.save(buf, format='JPEG', quality=95)
   byte_im = buf.getvalue()
   #img.save('img.png')
   return byte_im
#handels Text alignment
def textgen(d,text,col,just,yofs):
   x = 76
   if just == "l":
       x = 3
   if just == "r":
       x = 147
   if "\n" in text:
       split1 = text.split("\n")[0]
       split2 = text.split("\n")[1]
       d.text((x,8 + yofs), split1, fill=col, anchor=just+"m", font=rbm)
       d.text((x,22 + yofs),split2, fill=col, anchor=just+"m", font=rbm)
   elif d.textlength(text, font=ppb) < splitth:
       d.text((x,15 + yofs), text, fill=col, anchor=just+"m", font=ppb)
   else:
       d.text((x,15 + yofs), text, fill=col, anchor=just+"m", font=rbm)
   return d
#handels Text alignment
def textgen2(d,text,col,just,yofs):
   x = 148
   if just == "l":
       x = 3
   if just == "r":
       x = 290
   if "\n" in text:
       split1 = text.split("\n")[0]
       split2 = text.split("\n")[1]
       d.text((x,8 + yofs), split1, fill=col, anchor=just+"m", font=rbm)
       d.text((x,22 + yofs),split2, fill=col, anchor=just+"m", font=rbm)
   elif d.textlength(text, font=ppb) < splitth2:
       d.text((x,15 + yofs), text, fill=col, anchor=just+"m", font=ppb)
   else:
       d.text((x,15 + yofs), text, fill=col, anchor=just+"m", font=rbm)
   return d
#converts a char to a colour
def chartocol(c):
    if c == "r":
        return red
    if c == "w":
        return white    
    if c == "b":
        return black
#upload an immage to the tag
def uploadimg(img,mac,ip):
   url = "http://" + ip + "/imgupload"
   mp_encoder = MultipartEncoder(
       fields={
           'mac': mac,
           'image': ('image.jpg', img , 'image/jpeg'),
       }
   )
   response = requests.post(url, headers={'Content-Type': mp_encoder.content_type}, data=mp_encoder)
   if response.status_code != 200:
       _LOGGER.warning(response.status_code)
