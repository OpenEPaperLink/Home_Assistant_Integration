const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let elements = [];

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
      return { type: 'text', value: 'Text', x: 0, y: 10, size: 12, color: '#000' };
    case 'multiline':
      return { type: 'multiline', value: 'Line1|Line2', x: 0, y: 10, size: 12 };
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
      return { type: 'icon', value: 'mdi-home', x: 0, y: 24, size: 24 };
    case 'icon_sequence':
      return { type: 'icon_sequence', icons: ['A', 'B'], x: 0, y: 24, size: 24 };
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
  let w = canvas.width;
  let h = canvas.height;
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
  canvas.width = w;
  canvas.height = h;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  draw();
}

function drawElement(el) {
  switch (el.type) {
    case 'text':
      ctx.fillStyle = el.color || '#000';
      ctx.font = `${el.size || 12}px ${el.font || 'sans-serif'}`;
      ctx.fillText(el.value || 'Text', el.x || 0, el.y || 10);
      break;
    case 'multiline':
      ctx.fillStyle = el.color || '#000';
      ctx.font = `${el.size || 12}px ${el.font || 'sans-serif'}`;
      const lines = (el.value || '').split(el.delimiter || '|');
      let y = el.start_y || el.y || 10;
      lines.forEach((line, i) => {
        ctx.fillText(line, el.x || 0, y + i * (el.offset_y || 20));
      });
      break;
    case 'line':
      ctx.strokeStyle = el.color || '#000';
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.moveTo(el.x_start || 0, el.y_start || 0);
      ctx.lineTo(el.x_end || 0, el.y_end || 0);
      ctx.stroke();
      break;
    case 'rectangle':
      ctx.strokeStyle = el.outline || '#000';
      ctx.lineWidth = el.width || 1;
      if (el.fill) {
        ctx.fillStyle = el.fill;
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
          ctx.strokeStyle = el.outline || '#000';
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
      ctx.strokeStyle = el.outline || '#000';
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.moveTo(el.points[0][0], el.points[0][1]);
      for (let i = 1; i < el.points.length; i++) {
        ctx.lineTo(el.points[i][0], el.points[i][1]);
      }
      if (el.closed) ctx.closePath();
      if (el.fill) {
        ctx.fillStyle = el.fill;
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'circle':
      ctx.strokeStyle = el.outline || '#000';
      ctx.lineWidth = el.width || 1;
      ctx.beginPath();
      ctx.arc(el.x || 0, el.y || 0, el.radius || 10, 0, Math.PI * 2);
      if (el.fill) {
        ctx.fillStyle = el.fill;
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'ellipse':
      ctx.strokeStyle = el.outline || '#000';
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
        ctx.fillStyle = el.fill;
        ctx.fill();
      }
      ctx.stroke();
      break;
    case 'arc':
      ctx.strokeStyle = el.color || '#000';
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
      ctx.fillStyle = el.color || '#000';
      ctx.font = `${el.size || 24}px sans-serif`;
      ctx.fillText(el.value || '?', el.x || 0, el.y || 10);
      break;
    case 'icon_sequence':
      ctx.fillStyle = el.color || '#000';
      ctx.font = `${el.size || 24}px sans-serif`;
      let dx = 0;
      (el.icons || []).forEach((ic) => {
        ctx.fillText(ic, (el.x || 0) + dx, el.y || 10);
        dx += el.size || 24;
      });
      break;
    case 'qrcode':
      ctx.fillStyle = '#000';
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
      ctx.strokeStyle = el.outline || '#000';
      ctx.lineWidth = 1;
      const w = (el.x_end || 0) - (el.x_start || 0);
      const h = (el.y_end || 0) - (el.y_start || 0);
      ctx.strokeRect(el.x_start || 0, el.y_start || 0, w, h);
      ctx.fillStyle = el.fill || '#000';
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

function draw() {
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
    // Floyd-Steinberg
    const gray = new Float32Array(w * h);
    for (let i = 0; i < data.length; i += 4) {
      gray[i / 4] = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
    }
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        const old = gray[i];
        const newVal = old < 128 ? 0 : 255;
        const err = old - newVal;
        gray[i] = newVal;
        if (x + 1 < w) gray[i + 1] += (err * 7) / 16;
        if (y + 1 < h) {
          if (x > 0) gray[i + w - 1] += (err * 3) / 16;
          gray[i + w] += (err * 5) / 16;
          if (x + 1 < w) gray[i + w + 1] += err / 16;
        }
      }
    }
    for (let i = 0; i < gray.length; i++) {
      const v = gray[i] < 128 ? 0 : 255;
      data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = v;
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
        const v = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
        const threshold = (bayer[y % 4][x % 4] + 0.5) * 16;
        const val = v < threshold ? 0 : 255;
        data[i] = data[i + 1] = data[i + 2] = val;
      }
    }
  }
  ctx.putImageData(imageData, 0, 0);
}

function renderElementList() {
  const container = document.getElementById('elements');
  container.innerHTML = '';
  elements.forEach((el, i) => {
    const div = document.createElement('div');
    div.className = 'element';
    const ta = document.createElement('textarea');
    ta.rows = 6;
    ta.value = jsyaml.dump(el);
    ta.onchange = () => {
      try {
        elements[i] = jsyaml.load(ta.value);
        draw();
      } catch (e) {
        alert('Parse error: ' + e.message);
      }
    };
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
  });
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

document.getElementById('background').onchange = draw;

document.getElementById('export-yaml').onclick = () => {
  const data = {
    payload: elements,
    background: document.getElementById('background').value,
    rotate: parseInt(document.getElementById('rotate').value) || 0,
    dither: parseInt(document.getElementById('dither').value) || 0,
    ttl: parseInt(document.getElementById('ttl').value) || 0,
    'dry-run': document.getElementById('dry-run').checked,
  };
  document.getElementById('yaml').value = jsyaml.dump(data);
};

document.getElementById('import-yaml').onclick = () => {
  try {
    const data = jsyaml.load(document.getElementById('yaml').value);
    if (data.payload) elements = data.payload;
    if (data.background)
      document.getElementById('background').value = data.background;
    if (data.rotate !== undefined)
      document.getElementById('rotate').value = data.rotate;
    if (data.dither !== undefined)
      document.getElementById('dither').value = data.dither;
    if (data.ttl !== undefined) document.getElementById('ttl').value = data.ttl;
    if (data['dry-run'] !== undefined)
      document.getElementById('dry-run').checked = data['dry-run'];
    renderElementList();
    draw();
  } catch (e) {
    alert('Parse error: ' + e.message);
  }
};
createElementButtons();
updateScreenSize();
