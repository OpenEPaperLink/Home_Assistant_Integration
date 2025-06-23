const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let elements = [];
let zoom = 1;
let backend = 'js';
let screenWidth = canvas.width;
let screenHeight = canvas.height;
let selectedIndex = null;
let elementRefs = [];
let dragging = false;
let dragStartX = 0;
let dragStartY = 0;

function log(msg) {
  const out = document.getElementById('debug-output');
  if (!out) return;
  out.textContent += msg + '\n';
  out.scrollTop = out.scrollHeight;
}

let pyodideReady = false;
const PY_RENDERER_CODE = `
import io
import base64
import yaml
from PIL import Image, ImageDraw, ImageFont

# Use the integration's default font if available
DEFAULT_FONT = "ppb.ttf"


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a truetype font, falling back to PIL's default."""
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def _draw_text(draw: ImageDraw.ImageDraw, el: dict) -> None:
    font = _load_font(el.get("font", DEFAULT_FONT), el.get("size", 12))
    anchor = el.get("anchor", "lt")
    draw.text(
        (el.get("x", 0), el.get("y", 0)),
        str(el.get("value", "")),
        fill=el.get("color", "black"),
        font=font,
        anchor=anchor,
    )


def _draw_multiline(draw: ImageDraw.ImageDraw, el: dict) -> None:
    font = _load_font(el.get("font", DEFAULT_FONT), el.get("size", 12))
    anchor = el.get("anchor", "lt")
    y = el.get("start_y", el.get("y", 0))
    for idx, line in enumerate(str(el.get("value", "")).split(el.get("delimiter", "|"))):
        draw.text(
            (el.get("x", 0), y + idx * el.get("offset_y", 20)),
            line,
            fill=el.get("color", "black"),
            font=font,
            anchor=anchor,
        )


def render_image(yaml_text: str) -> str:
    data = yaml.safe_load(yaml_text)
    width = data.get("width", 296)
    height = data.get("height", 128)
    background = data.get("background", "white")
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    for el in data.get("payload", []):
        t = el.get("type")
        if t == "text":
            _draw_text(draw, el)
        elif t == "multiline":
            _draw_multiline(draw, el)
        elif t == "line":
            draw.line(
                [
                    (el.get("x_start", 0), el.get("y_start", 0)),
                    (el.get("x_end", 0), el.get("y_end", 0)),
                ],
                fill=el.get("color", "black"),
                width=el.get("width", 1),
            )
        elif t == "rectangle":
            draw.rectangle(
                [
                    el.get("x_start", 0),
                    el.get("y_start", 0),
                    el.get("x_end", 0),
                    el.get("y_end", 0),
                ],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "rectangle_pattern":
            for xi in range(el.get("x_repeat", 1)):
                for yi in range(el.get("y_repeat", 1)):
                    x = el.get("x_start", 0) + xi * el.get("x_size", 10) + el.get("x_offset", 0)
                    y = el.get("y_start", 0) + yi * el.get("y_size", 10) + el.get("y_offset", 0)
                    draw.rectangle(
                        [x, y, x + el.get("x_size", 10), y + el.get("y_size", 10)],
                        outline=el.get("outline", "black"),
                        width=el.get("width", 1),
                    )
        elif t == "polygon":
            pts = el.get("points", [])
            if pts:
                draw.polygon(
                    pts,
                    outline=el.get("outline", "black"),
                    fill=el.get("fill"),
                )
        elif t == "circle":
            r = el.get("radius", 10)
            x = el.get("x", 0)
            y = el.get("y", 0)
            draw.ellipse(
                [x - r, y - r, x + r, y + r],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "ellipse":
            draw.ellipse(
                [
                    el.get("x_start", 0),
                    el.get("y_start", 0),
                    el.get("x_end", 0),
                    el.get("y_end", 0),
                ],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "arc":
            r = el.get("radius", 10)
            x = el.get("x", 0)
            y = el.get("y", 0)
            draw.arc(
                [x - r, y - r, x + r, y + r],
                el.get("start_angle", 0),
                el.get("end_angle", 180),
                fill=el.get("color", "black"),
                width=el.get("width", 1),
            )
        elif t == "progress_bar":
            x0, y0 = el.get("x_start", 0), el.get("y_start", 0)
            x1, y1 = el.get("x_end", 0), el.get("y_end", 0)
            draw.rectangle([x0, y0, x1, y1], outline=el.get("outline", "black"), width=1)
            prog = max(0, min(1, el.get("progress", 0) / 100))
            fill_w = x0 + (x1 - x0) * prog
            draw.rectangle([x0, y0, fill_w, y1], fill=el.get("fill", "black"))
        elif t == "debug_grid":
            for x in range(0, img.width, 10):
                draw.line([(x, 0), (x, img.height)], fill="#cccccc", width=1)
            for y in range(0, img.height, 10):
                draw.line([(0, y), (img.width, y)], fill="#cccccc", width=1)

    rotate = data.get("rotate", 0)
    if rotate:
        img = img.rotate(rotate, expand=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
`;

async function initPyodide() {
  if (pyodideReady) return;
  self.pyodide = await loadPyodide({ indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.27.1/full/' });
  await self.pyodide.loadPackage(['Pillow', 'PyYAML']);
  for (const f of ['ppb.ttf', 'rbm.ttf', 'materialdesignicons-webfont.ttf']) {
    const resp = await fetch(`../../custom_components/open_epaper_link/${f}`);
    if (resp.ok) {
      const buf = await resp.arrayBuffer();
      self.pyodide.FS.writeFile(f, new Uint8Array(buf));
    }
  }
  await self.pyodide.runPython(PY_RENDERER_CODE);
  pyodideReady = true;
  log('pyodide ready');
}

const anchorMap = {
  lt: ['left', 'top'],
  lm: ['left', 'middle'],
  lb: ['left', 'bottom'],
  la: ['left', 'alphabetic'],
  mt: ['center', 'top'],
  mm: ['center', 'middle'],
  mb: ['center', 'bottom'],
  ma: ['center', 'alphabetic'],
  rt: ['right', 'top'],
  rm: ['right', 'middle'],
  rb: ['right', 'bottom'],
  ra: ['right', 'alphabetic'],
};

function applyAnchor(anchor) {
  const [align, baseline] = anchorMap[anchor] || anchorMap.lt;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
}

function resolveColor(name) {
  if (!name) return '#000';
  const map = {
    black: '#000000',
    b: '#000000',
    white: '#ffffff',
    w: '#ffffff',
    red: '#ff0000',
    r: '#ff0000',
    yellow: '#ffff00',
    y: '#ffff00',
    accent: '#ff0000',
    a: '#ff0000',
    half_black: '#808080',
    gray: '#808080',
    grey: '#808080',
    hb: '#808080',
    g: '#808080',
    half_red: '#ff8080',
    hr: '#ff8080',
    half_yellow: '#ffff80',
    hy: '#ffff80',
    half_accent: '#ff8080',
    ha: '#ff8080',
  };
  return map[name.toLowerCase()] || name;
}

async function drawPython() {
  await initPyodide();
  try {
    const rot = parseInt(document.getElementById('rotate').value) || 0;
    const data = {
      payload: elements,
      background: document.getElementById('background').value,
      rotate: rot % 180 === 0 ? rot : 0,
      dither: parseInt(document.getElementById('dither').value) || 0,
      ttl: parseInt(document.getElementById('ttl').value) || 0,
      'dry-run': document.getElementById('dry-run').checked,
      width: canvas.width,
      height: canvas.height,
    };
    const renderImage = self.pyodide.globals.get('render_image');
    const dataUrl = renderImage(jsyaml.dump(data));
    const img = new Image();
    img.onload = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
    };
    img.src = dataUrl;
  } catch (e) {
    log('Pyodide error: ' + e);
  }
}

const elementTypes = [
  'text',
  'multiline',
  'line',
  'rectangle',
  'rectangle_pattern',
  'polygon',
  'circle',
  'ellipse',
  'arc',
  'icon',
  'icon_sequence',
  'qrcode',
  'plot',
  'progress_bar',
  'diagram',
  'dlimg',
  'debug_grid',
];

function defaultElement(type) {
  switch (type) {
    case 'text':
      return { type: 'text', value: 'Text', x: 0, y: 10, size: 12, color: '#000', anchor: 'lt' };
    case 'multiline':
      return { type: 'multiline', value: 'Line1|Line2', x: 0, y: 10, size: 12, anchor: 'lm' };
    case 'line':
      return { type: 'line', x_start: 0, y_start: 0, x_end: 50, y_end: 50 };
    case 'rectangle':
      return { type: 'rectangle', x_start: 0, y_start: 0, x_end: 50, y_end: 30 };
    case 'rectangle_pattern':
      return { type: 'rectangle_pattern', x_start: 0, y_start: 0, x_size: 10, y_size: 10 };
    case 'polygon':
      return { type: 'polygon', points: [[0, 0], [40, 0], [20, 30]], closed: true };
    case 'circle':
      return { type: 'circle', x: 20, y: 20, radius: 10 };
    case 'ellipse':
      return { type: 'ellipse', x_start: 0, y_start: 0, x_end: 40, y_end: 20 };
    case 'arc':
      return { type: 'arc', x: 20, y: 20, radius: 10, start_angle: 0, end_angle: 180 };
    case 'icon':
      return { type: 'icon', value: 'mdi-home', x: 0, y: 24, size: 24, anchor: 'la' };
    case 'icon_sequence':
      return { type: 'icon_sequence', icons: ['A', 'B'], x: 0, y: 24, size: 24, anchor: 'la' };
    case 'qrcode':
      return { type: 'qrcode', data: 'https://example.com', x: 0, y: 0, size: 50 };
    case 'plot':
      return { type: 'plot', x: 0, y: 0, width: 100, height: 50 };
    case 'progress_bar':
      return { type: 'progress_bar', x_start: 0, y_start: 0, x_end: 100, y_end: 20, progress: 50 };
    case 'diagram':
      return { type: 'diagram', x: 0, y: 0, width: 100, height: 50 };
    case 'dlimg':
      return { type: 'dlimg', url: '', x: 0, y: 0, xsize: 50, ysize: 50 };
    case 'debug_grid':
      return { type: 'debug_grid' };
    default:
      return { type };
  }
}

function addElement(type) {
  elements.push(defaultElement(type));
  renderElementList();
  draw();
}

function updateScreenSize() {
  const sel = document.getElementById('screen-size').value;
  const widthInput = document.getElementById('screen-width');
  const heightInput = document.getElementById('screen-height');
  let w = screenWidth;
  let h = screenHeight;
  if (sel === 'custom') {
    widthInput.disabled = false;
    heightInput.disabled = false;
    w = parseInt(widthInput.value) || w;
    h = parseInt(heightInput.value) || h;
  } else {
    [w, h] = sel.split('x').map((n) => parseInt(n));
    widthInput.value = w;
    heightInput.value = h;
    widthInput.disabled = true;
    heightInput.disabled = true;
  }
  screenWidth = w;
  screenHeight = h;
  applyRotation();
}

function applyRotation() {
  const rot = parseInt(document.getElementById('rotate').value) || 0;
  if (rot % 180 === 0) {
    canvas.width = screenWidth;
    canvas.height = screenHeight;
  } else {
    canvas.width = screenHeight;
    canvas.height = screenWidth;
  }
  updateZoom();
  draw();
}

function updateZoom() {
  zoom = parseInt(document.getElementById('zoom').value) || 1;
  canvas.style.width = canvas.width * zoom + 'px';
  canvas.style.height = canvas.height * zoom + 'px';
}

function drawElement(el) {
  switch (el.type) {
    case 'text':
      ctx.fillStyle = resolveColor(el.color);
      ctx.font = `${el.size || 12}px ${el.font || 'sans-serif'}`;
      applyAnchor(el.anchor || 'lt');
      ctx.fillText(el.value || 'Text', el.x || 0, el.y || 10);
      break;
    case 'multiline':
      ctx.fillStyle = resolveColor(el.color);
      ctx.font = `${el.size || 12}px ${el.font || 'sans-serif'}`;
      applyAnchor(el.anchor || 'lm');
      const lines = (el.value || '').split(el.delimiter || '|');
      let y = el.start_y || el.y || 10;
      lines.forEach((line, i) => {
        ctx.fillText(line, el.x || 0, y + i * (el.offset_y || 20));
      });
      break;
    case 'line':
      ctx.strokeStyle = resolveColor(el.color);
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.moveTo(el.x_start || 0, el.y_start || 0);
      ctx.lineTo(el.x_end || 0, el.y_end || 0);
      ctx.stroke();
      break;
    case 'rectangle':
      ctx.strokeStyle = resolveColor(el.outline);
      ctx.lineWidth = el.width || 1;
      if (el.fill) {
        ctx.fillStyle = resolveColor(el.fill);
        ctx.fillRect(
          el.x_start || 0,
          el.y_start || 0,
          (el.x_end || 0) - (el.x_start || 0),
          (el.y_end || 0) - (el.y_start || 0)
        );
      }
      ctx.strokeRect(
        el.x_start || 0,
        el.y_start || 0,
        (el.x_end || 0) - (el.x_start || 0),
        (el.y_end || 0) - (el.y_start || 0)
      );
      break;
    case 'rectangle_pattern':
      for (let xi = 0; xi < (el.x_repeat || 1); xi++) {
        for (let yi = 0; yi < (el.y_repeat || 1); yi++) {
          ctx.strokeStyle = resolveColor(el.outline);
          ctx.lineWidth = el.width || 1;
          ctx.strokeRect(
            (el.x_start || 0) + xi * (el.x_size || 10) + (el.x_offset || 0),
            (el.y_start || 0) + yi * (el.y_size || 10) + (el.y_offset || 0),
            el.x_size || 10,
            el.y_size || 10
          );
        }
      }
      break;
    case 'polygon':
      if (!el.points || !el.points.length) return;
      ctx.strokeStyle = resolveColor(el.outline);
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.moveTo(el.points[0][0], el.points[0][1]);
      for (let i = 1; i < el.points.length; i++) {
        ctx.lineTo(el.points[i][0], el.points[i][1]);
      }
      if (el.closed) ctx.closePath();
      if (el.fill) {
        ctx.fillStyle = resolveColor(el.fill);
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'circle':
      ctx.strokeStyle = resolveColor(el.outline);
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.arc(el.x || 0, el.y || 0, el.radius || 10, 0, Math.PI * 2);
      if (el.fill) {
        ctx.fillStyle = resolveColor(el.fill);
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'ellipse':
      ctx.strokeStyle = resolveColor(el.outline);
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.ellipse(
        (el.x_start + el.x_end) / 2 || 0,
        (el.y_start + el.y_end) / 2 || 0,
        Math.abs(el.x_end - el.x_start) / 2 || 10,
        Math.abs(el.y_end - el.y_start) / 2 || 10,
        0,
        0,
        Math.PI * 2
      );
      if (el.fill) {
        ctx.fillStyle = resolveColor(el.fill);
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'arc':
      ctx.strokeStyle = resolveColor(el.color);
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.arc(
        el.x || 0,
        el.y || 0,
        el.radius || 10,
        ((el.start_angle || 0) * Math.PI) / 180,
        ((el.end_angle || 0) * Math.PI) / 180
      );
      ctx.stroke();
      break;
    case 'icon':
      ctx.fillStyle = resolveColor(el.color);
      ctx.font = `${el.size || 24}px sans-serif`;
      applyAnchor(el.anchor || 'la');
      ctx.fillText(el.value || '?', el.x || 0, el.y || 10);
      break;
    case 'icon_sequence':
      ctx.fillStyle = resolveColor(el.color);
      ctx.font = `${el.size || 24}px sans-serif`;
      applyAnchor(el.anchor || 'la');
      let dx = 0;
      (el.icons || []).forEach((ic) => {
        ctx.fillText(ic, (el.x || 0) + dx, el.y || 10);
        dx += el.size || 24;
      });
      break;
    case 'qrcode':
      ctx.fillStyle = resolveColor('black');
      ctx.fillRect(el.x || 0, el.y || 0, el.size || 50, el.size || 50);
      break;
    case 'plot':
    case 'diagram':
      ctx.fillStyle = '#aaa';
      ctx.fillRect(el.x || 0, el.y || 0, el.width || 100, el.height || 50);
      break;
    case 'dlimg':
      if (!el.url) break;
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        ctx.drawImage(
          img,
          el.x || 0,
          el.y || 0,
          el.xsize || img.width,
          el.ysize || img.height
        );
      };
      img.src = el.url;
      break;
    case 'progress_bar':
      ctx.strokeStyle = resolveColor(el.outline);
      ctx.lineWidth = 1;
      const w = (el.x_end || 0) - (el.x_start || 0);
      const h = (el.y_end || 0) - (el.y_start || 0);
      ctx.strokeRect(el.x_start || 0, el.y_start || 0, w, h);
      ctx.fillStyle = resolveColor(el.fill || 'black');
      const prog = Math.max(0, Math.min(1, (el.progress || 0) / 100));
      ctx.fillRect(el.x_start || 0, el.y_start || 0, w * prog, h);
      break;
    case 'debug_grid':
      ctx.strokeStyle = '#ccc';
      for (let x = 0; x < canvas.width; x += 10) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y < canvas.height; y += 10) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
      }
      break;
  }
}

function drawJS() {
  ctx.save();
  ctx.fillStyle = document.getElementById('background').value;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  elements.forEach((el) => drawElement(el));
  ctx.restore();
  applyDither();
}

function applyDither() {
  const mode = parseInt(document.getElementById('dither').value) || 0;
  if (mode === 0) return; // no dithering preview
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;
  const w = canvas.width;
  const h = canvas.height;
  if (mode === 1) {
    const errR = new Float32Array(w * h);
    const errG = new Float32Array(w * h);
    const errB = new Float32Array(w * h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const idx = y * w + x;
        let r = data[idx * 4] + errR[idx];
        let g = data[idx * 4 + 1] + errG[idx];
        let b = data[idx * 4 + 2] + errB[idx];
        const nr = r < 128 ? 0 : 255;
        const ng = g < 128 ? 0 : 255;
        const nb = b < 128 ? 0 : 255;
        data[idx * 4] = nr;
        data[idx * 4 + 1] = ng;
        data[idx * 4 + 2] = nb;
        const dr = r - nr;
        const dg = g - ng;
        const db = b - nb;
        if (x + 1 < w) {
          errR[idx + 1] += (dr * 7) / 16;
          errG[idx + 1] += (dg * 7) / 16;
          errB[idx + 1] += (db * 7) / 16;
        }
        if (y + 1 < h) {
          if (x > 0) {
            errR[idx + w - 1] += (dr * 3) / 16;
            errG[idx + w - 1] += (dg * 3) / 16;
            errB[idx + w - 1] += (db * 3) / 16;
          }
          errR[idx + w] += (dr * 5) / 16;
          errG[idx + w] += (dg * 5) / 16;
          errB[idx + w] += (db * 5) / 16;
          if (x + 1 < w) {
            errR[idx + w + 1] += dr / 16;
            errG[idx + w + 1] += dg / 16;
            errB[idx + w + 1] += db / 16;
          }
        }
      }
    }
  } else if (mode === 2) {
    const bayer = [
      [0, 8, 2, 10],
      [12, 4, 14, 6],
      [3, 11, 1, 9],
      [15, 7, 13, 5],
    ];
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        const threshold = (bayer[y % 4][x % 4] + 0.5) * 16;
        data[i] = data[i] < threshold ? 0 : 255;
        data[i + 1] = data[i + 1] < threshold ? 0 : 255;
        data[i + 2] = data[i + 2] < threshold ? 0 : 255;
      }
    }
  }
  ctx.putImageData(imageData, 0, 0);
}

function draw() {
  const rot = parseInt(document.getElementById('rotate').value) || 0;
  if (backend === 'py' || rot !== 0) {
    drawPython();
  } else {
    drawJS();
  }
}

function selectElement(i) {
  selectedIndex = i;
  elementRefs.forEach((ref, idx) => {
    if (!ref) return;
    if (idx === i) ref.div.classList.add('selected');
    else ref.div.classList.remove('selected');
  });
}

function updateElementTextarea(i) {
  const ref = elementRefs[i];
  if (ref) {
    ref.ta.value = jsyaml.dump(elements[i]);
  }
}

function renderElementList() {
  const container = document.getElementById('elements');
  const scroll = container.scrollTop;
  container.innerHTML = '';
  elementRefs = [];
  elements.forEach((el, i) => {
    const div = document.createElement('div');
    div.className = 'element';
    if (i === selectedIndex) div.classList.add('selected');
    div.onclick = () => selectElement(i);
    const ta = document.createElement('textarea');
    ta.rows = 6;
    ta.value = jsyaml.dump(el);
    let taTimer;
    ta.addEventListener('input', () => {
      clearTimeout(taTimer);
      taTimer = setTimeout(() => {
        try {
          elements[i] = jsyaml.load(ta.value);
          draw();
        } catch (e) {
          log('Parse error: ' + e.message);
        }
      }, 300);
    });
    const del = document.createElement('button');
    del.textContent = 'Delete';
    del.onclick = () => {
      elements.splice(i, 1);
      renderElementList();
      draw();
    };
    div.appendChild(ta);
    div.appendChild(del);
    container.appendChild(div);
    elementRefs[i] = { div, ta };
  });
  container.scrollTop = scroll;
}

function createElementButtons() {
  const container = document.getElementById('element-buttons');
  elementTypes.forEach((t) => {
    const btn = document.createElement('button');
    btn.textContent = t;
    btn.onclick = () => addElement(t);
    container.appendChild(btn);
  });
}


document.getElementById('screen-size').onchange = updateScreenSize;
document.getElementById('screen-width').onchange = () => {
  document.getElementById('screen-size').value = 'custom';
  updateScreenSize();
};
document.getElementById('screen-height').onchange = () => {
  document.getElementById('screen-size').value = 'custom';
  updateScreenSize();
};
document.getElementById('zoom').onchange = () => {
  updateZoom();
  draw();
};
document.getElementById('rotate').onchange = applyRotation;

document.querySelectorAll('input[name="renderer"]').forEach((el) => {
  el.onchange = () => {
    if (el.checked) {
      backend = el.value;
      draw();
    }
  };
});

document.getElementById('background').onchange = draw;

document.getElementById('export-yaml').onclick = () => {
  const data = {
    payload: elements,
    background: document.getElementById('background').value,
    rotate: parseInt(document.getElementById('rotate').value) || 0,
    dither: parseInt(document.getElementById('dither').value) || 0,
    ttl: parseInt(document.getElementById('ttl').value) || 0,
    'dry-run': document.getElementById('dry-run').checked,
    width: screenWidth,
    height: screenHeight,
  };
  document.getElementById('yaml').value = jsyaml.dump(data);
};

document.getElementById('import-yaml').onclick = () => {
  parseYamlField();
};

document.getElementById('clear-elements').onclick = () => {
  if (elements.length === 0) return;
  if (confirm('Clear all elements?')) {
    elements = [];
    renderElementList();
    draw();
  }
};

let yamlTimer;
function parseYamlField() {
  try {
    const data = jsyaml.load(document.getElementById('yaml').value);
    if (data.payload) elements = data.payload;
    if (data.background)
      document.getElementById('background').value = resolveColor(data.background);
    if (data.rotate !== undefined) {
      document.getElementById('rotate').value = data.rotate;
      applyRotation();
    }
    if (data.dither !== undefined)
      document.getElementById('dither').value = data.dither;
    if (data.ttl !== undefined) document.getElementById('ttl').value = data.ttl;
    if (data['dry-run'] !== undefined)
      document.getElementById('dry-run').checked = data['dry-run'];
    if (data.width && data.height) {
      document.getElementById('screen-size').value = 'custom';
      document.getElementById('screen-width').value = data.width;
      document.getElementById('screen-height').value = data.height;
      updateScreenSize();
    }
    renderElementList();
    draw();
  } catch (e) {
    log('Parse error: ' + e.message);
  }
}

document.getElementById('yaml').addEventListener('input', () => {
  clearTimeout(yamlTimer);
  yamlTimer = setTimeout(parseYamlField, 400);
});

canvas.addEventListener('mousedown', (e) => {
  if (selectedIndex === null) return;
  dragging = true;
  dragStartX = Math.round(e.offsetX / zoom);
  dragStartY = Math.round(e.offsetY / zoom);
});

canvas.addEventListener('mousemove', (e) => {
  if (!dragging || selectedIndex === null) return;
  const x = Math.round(e.offsetX / zoom);
  const y = Math.round(e.offsetY / zoom);
  const dx = x - dragStartX;
  const dy = y - dragStartY;
  const el = elements[selectedIndex];
  if ('x' in el) el.x = Math.round((el.x || 0) + dx);
  if ('y' in el) el.y = Math.round((el.y || 0) + dy);
  if ('x_start' in el) {
    el.x_start = Math.round((el.x_start || 0) + dx);
    if ('x_end' in el) el.x_end = Math.round((el.x_end || 0) + dx);
  }
  if ('y_start' in el) {
    el.y_start = Math.round((el.y_start || 0) + dy);
    if ('y_end' in el) el.y_end = Math.round((el.y_end || 0) + dy);
  }
  if (Array.isArray(el.points)) {
    el.points = el.points.map((p) => [
      Math.round(p[0] + dx),
      Math.round(p[1] + dy),
    ]);
  }
  dragStartX = x;
  dragStartY = y;
  updateElementTextarea(selectedIndex);
  draw();
});

canvas.addEventListener('mouseup', () => {
  dragging = false;
});

canvas.addEventListener('mouseleave', () => {
  dragging = false;
});
createElementButtons();
updateScreenSize();
updateZoom();
renderElementList();
draw();
