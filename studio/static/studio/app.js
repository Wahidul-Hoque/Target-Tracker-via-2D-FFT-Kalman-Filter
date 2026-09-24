'use strict';

const $ = id => document.getElementById(id);
const canvas = $('video'), ctx = canvas.getContext('2d');
const referenceCanvas = $('reference-canvas'), referenceCtx = referenceCanvas.getContext('2d');

let state = null;
let frameImage = null;
let playing = false;
let selecting = false;
let drag = null;
let referenceImage = null;
let referenceSelecting = false;
let referenceDrag = null;
let referenceSelectionBox = null;
let page = 'studio';
let timer = null;
let chain = Promise.resolve();
let busy = 0;
let playbackEpoch = 0;
let displayedTimes = [];

const plots = [
  ['Target crop', 'Spatial template'],
  ['Windowed search', 'Mean removed · Hann window'],
  ['Log FFT magnitude', 'Centered frequency spectrum'],
  ['Correlation surface', 'Centered peak marked +']
];

const cards = [...document.querySelectorAll('.dsp-card')];
cards.forEach((card, i) => {
  card.querySelector('.plot-title').textContent = plots[i][0].toUpperCase();
  card.querySelector('.plot-description').textContent = plots[i][1];
  card.querySelector('img').alt = plots[i][0];
});

const format = (n, digits = 1) =>
  typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—';

function notice(text, error = false) {
  $('notice').textContent = text;
  $('notice').classList.toggle('error', error);
}

function controls() {
  const loaded = !!state?.loaded, ended = !!state?.ended;
  ['upload', 'target-upload', 'demo', 'empty-demo'].forEach(id => {
    $(id).disabled = busy > 0;
  });
  ['restart', 'roi', 'close-source'].forEach(id => {
    $(id).disabled = !loaded || busy > 0;
  });
  $('reference-roi').disabled = !referenceImage || busy > 0;
  $('play').disabled = !loaded || ended || busy > 0 || selecting || referenceSelecting;
  $('step').disabled = !loaded || ended || playing || busy > 0 || selecting || referenceSelecting;
  $('snapshot').disabled = !state?.ready || !state?.loaded || busy > 0;
  $('export').disabled = !state?.analytics.total || busy > 0;
  $('play').textContent = playing ? 'Ⅱ Pause' : '▶ Play';
  document.body.classList.toggle('busy', busy > 0);
}

function csrf() {
  return document.cookie
    .split('; ')
    .find(c => c.startsWith('csrftoken='))
    ?.split('=')
    .slice(1)
    .join('=') || '';
}

function enqueue(action, data = {}, quiet = false) {
  const run = async () => {
    if (!quiet) {
      busy++;
      controls();
    }
    try {
      const form = data instanceof FormData;
      const response = await fetch(`/api/${action}/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': decodeURIComponent(csrf()),
          ...(!form ? {'Content-Type': 'application/json'} : {})
        },
        body: form ? data : JSON.stringify(data)
      });

      if (!response.ok) {
        let message = `Request failed (${response.status}). Reload the page and try again.`;
        try {
          message = (await response.json()).error || message;
        } catch (_) {}
        throw new Error(message);
      }

      const next = await response.json();
      await render(next);
      return next;
    } catch (error) {
      pause();
      notice(error.message || 'Connection lost. Check that the Django server is running.', true);
      throw error;
    } finally {
      if (!quiet) busy--;
      controls();
    }
  };

  const result = chain.then(run);
  chain = result.catch(() => {});
  return result;
}

function pause() {
  playing = false;
  playbackEpoch++;
  clearTimeout(timer);
  controls();
}

function cancelVideoSelection() {
  selecting = false;
  drag = null;
  $('selection-hint').hidden = true;
  canvas.style.cursor = '';
  drawVideo();
  controls();
}

function cancelReferenceSelection() {
  referenceSelecting = false;
  referenceDrag = null;
  $('reference-selection-hint').hidden = true;
  referenceCanvas.style.cursor = '';
  drawReference();
  controls();
}

function cancelSelections() {
  cancelVideoSelection();
  cancelReferenceSelection();
}

async function mutate(action, data = {}, message = '') {
  pause();
  cancelSelections();
  notice('Preparing your workspace…');
  try {
    const s = await enqueue(action, data);
    displayedTimes = [];
    let fallback;
    if (s.reference?.selected && !s.loaded) {
      fallback = 'Reference target selected. Open a video to begin global searching.';
    } else if (s.reference?.selected && s.loaded && !s.locked) {
      fallback = 'Reference target ready. Press Play: global search will continue until the object is found.';
    } else if (s.ready) {
      fallback = 'Target initialized. Press Play to follow the signal.';
    } else {
      fallback = 'Select a target in the video, or upload a target image and select its target region.';
    }
    notice(s.warning || message || fallback);
    return s;
  } catch (_) {
    return null;
  }
}

async function tick(epoch) {
  if (!playing || epoch !== playbackEpoch) return;
  const started = performance.now(), previousIndex = state.index;

  try {
    const s = await enqueue('step', {diagnostics: page === 'dsp'}, true);
    if (!playing || epoch !== playbackEpoch) return;

    if (s.ended) {
      pause();
      notice('End of video. Export your session or restart the source.');
      return;
    }

    displayedTimes.push(performance.now());
    displayedTimes = displayedTimes.slice(-30);
    if (displayedTimes.length > 1) {
      const actual = (displayedTimes.length - 1) * 1000 /
        (displayedTimes.at(-1) - displayedTimes[0]);
      $('frame-label').textContent = `FRAME ${s.index + 1} · ${actual.toFixed(1)} FPS ACTUAL`;
    }

    timer = setTimeout(
      () => tick(epoch),
      Math.max(
        0,
        Math.max(1, s.index - previousIndex) * 1000 / s.fps -
          (performance.now() - started)
      )
    );
  } catch (_) {}
}

function togglePlay() {
  if (!state?.loaded || state.ended || busy || selecting || referenceSelecting) return;
  if (playing) {
    pause();
    notice('Paused. Inspect the current frame, or step forward.');
  } else {
    playing = true;
    displayedTimes = [];
    const epoch = ++playbackEpoch;
    controls();
    notice(
      state?.reference?.selected && !state?.locked
        ? 'Searching globally for the uploaded target. Press Space to pause.'
        : 'Following the signal. Press Space to pause.'
    );
    tick(epoch);
  }
}

async function render(s) {
  let image = null;
  if (s.image) {
    image = new Image();
    image.src = s.image;
    await image.decode();
  }

  state = s;
  frameImage = image;

  $('empty').hidden = s.loaded;
  canvas.hidden = !s.loaded;
  if (s.loaded) {
    canvas.width = s.width;
    canvas.height = s.height;
  }

  $('resolution').textContent = s.loaded
    ? `${s.width} × ${s.height} · ${format(s.fps, 0)} FPS`
    : 'NO SOURCE';
  $('source-name').textContent = s.name || 'No source loaded';
  $('source-name').title = s.name || '';
  $('frame-label').textContent = s.loaded
    ? `FRAME ${s.index + 1} / ${s.total || '—'}`
    : 'FRAME — / —';
  $('progress').style.width = s.total
    ? `${100 * (s.index + 1) / s.total}%`
    : '0';

  const r = s.result;
  let statusText;
  if (r?.status) statusText = r.status;
  else if (s.reference?.selected && s.loaded && !s.locked) statusText = 'SEARCHING';
  else if (s.reference?.selected && !s.loaded) statusText = 'Reference ready';
  else if (s.ready) statusText = 'Ready to track';
  else if (s.loaded) statusText = 'Select a target';
  else statusText = 'Awaiting source';

  $('tracker-status').textContent = statusText;
  $('tracker-status').classList.toggle(
    'warning',
    statusText === 'SEARCHING'
  );

  $('tracker-reason').textContent = r?.reason || (
    s.reference?.selected
      ? (s.loaded
          ? 'Global tiled search is waiting for the reference target to appear.'
          : 'Open a video. The target will be searched globally when playback begins.')
      : s.ready
        ? 'Target initialized. Ready when you are.'
        : 'Your live metrics will appear here.'
  );

  $('psr').textContent = format(r?.psr);
  $('psr-meter').style.width = r
    ? `${Math.min(100, Math.max(0, r.psr / 30 * 100))}%`
    : '0';

  $('appearance').textContent = format(r?.appearance, 2);
  $('appearance-meter').style.width = r
    ? `${Math.min(100, Math.max(0, r.appearance * 100))}%`
    : '0';

  $('position').textContent = (r && r.status === 'TRACKING')
    ? `${format(r.center[0])} / ${format(r.center[1])}`
    : '— / —';
  $('speed').textContent = (r && r.status === 'TRACKING')
    ? format(Math.hypot(...r.velocity))
    : '—';
  $('latency').textContent = format(r?.processing_ms);

  $('recorded').textContent = s.analytics.total.toLocaleString();
  $('accepted').textContent = s.analytics.accepted.toLocaleString();
  $('predicted').textContent = (s.analytics.total - s.analytics.accepted).toLocaleString();

  if (s.reference?.loaded) {
    $('reference-panel').hidden = false;
    $('reference-name').textContent = s.reference.name || 'Target image';
    $('reference-status').textContent = s.reference.selected
      ? `Target selected · ${s.target?.size?.[0] || '—'} × ${s.target?.size?.[1] || '—'} px`
      : 'Image loaded · select the target region';
  } else {
    $('reference-panel').hidden = true;
  }

  cards.forEach((card, i) => {
    const plot = s.diagnostics[plots[i][0]], img = card.querySelector('img');
    img.hidden = !plot;
    card.querySelector('.plot-placeholder').hidden = !!plot;
    card.querySelector('.peak').hidden = true;
    card.querySelector('.plot-shape').textContent = plot
      ? `${plot.width} × ${plot.height}`
      : '—';
    card.querySelector('.plot-range').textContent = plot
      ? `${format(plot.minimum, 2)} … ${format(plot.maximum, 2)}`
      : '';
    if (plot && img.getAttribute('src') !== plot.image) {
      img.onload = () => positionPeak(card, plot);
      img.src = plot.image;
    } else if (plot) {
      positionPeak(card, plot);
    }
  });

  $('dsp-caption').textContent = s.diagnostic_frame
    ? `Showing source frame ${s.diagnostic_frame} · ${playing ? 'Live diagnostics' : 'Read-only snapshot'}`
    : 'Select a target and refresh, or play with DSP Lab open.';

  drawVideo();
  drawReference();
  if (page === 'analytics') drawCharts();
  controls();
}

function positionPeak(card, plot) {
  if (!plot.peak || page !== 'dsp') return;
  const img = card.querySelector('img');
  const holder = card.querySelector('.plot-image');
  const marker = card.querySelector('.peak');
  const scale = Math.min(holder.clientWidth / plot.width, holder.clientHeight / plot.height);
  marker.style.left = `${(holder.clientWidth - plot.width * scale) / 2 + plot.peak[0] * plot.width * scale}px`;
  marker.style.top = `${(holder.clientHeight - plot.height * scale) / 2 + plot.peak[1] * plot.height * scale}px`;
  marker.hidden = false;
}

function drawVideo() {
  if (!frameImage || !state?.loaded) return;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(frameImage, 0, 0);

  const scale = canvas.width / Math.max(1, canvas.getBoundingClientRect().width);
  const box = (center, size, color, width = 1.5) => {
    if (!center) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width * scale;
    ctx.strokeRect(
      center[0] - size[0] / 2,
      center[1] - size[1] / 2,
      ...size
    );
  };

  const r = state.result;
  if (r) {
    if (r.search_box?.length) {
      ctx.strokeStyle = '#97a9b5';
      ctx.lineWidth = scale;
      ctx.setLineDash([4 * scale, 4 * scale]);
      ctx.strokeRect(...r.search_box);
      ctx.setLineDash([]);
    }

    if (r.status === 'TRACKING') {
      if (r.trajectory.length > 1) {
        ctx.beginPath();
        ctx.strokeStyle = '#829eff';
        ctx.lineWidth = 1.5 * scale;
        r.trajectory.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p));
        ctx.stroke();
      }
      if (r.measurement) box(r.measurement, r.bbox_size, '#6ee7be');
      box(r.center, r.bbox_size, '#ff8796', 2);

      ctx.font = `${10 * scale}px monospace`;
      ctx.fillStyle = '#ff8796';
      ctx.fillText(
        r.status + (r.reason ? ` · ${r.reason}` : ''),
        Math.max(4, r.center[0] - r.bbox_size[0] / 2),
        Math.max(14 * scale, r.center[1] - r.bbox_size[1] / 2 - 8 * scale)
      );
    } else if (r.search_box?.length) {
      ctx.font = `${10 * scale}px monospace`;
      ctx.fillStyle = '#97a9b5';
      ctx.fillText(
        'SEARCHING · ' + (r.reason || 'global scan'),
        Math.max(4, r.search_box[0]),
        Math.max(14 * scale, r.search_box[1] - 6 * scale)
      );
    }
  } else if (state.target?.center) {
    box(state.target.center, state.target.size, '#6ee7be', 2);
  }

  if (drag) {
    ctx.strokeStyle = '#6ee7be';
    ctx.lineWidth = 2 * scale;
    ctx.setLineDash([5 * scale, 3 * scale]);
    ctx.fillStyle = '#6ee7be20';
    const rectangle = [
      drag.start[0],
      drag.start[1],
      drag.end[0] - drag.start[0],
      drag.end[1] - drag.start[1]
    ];
    ctx.fillRect(...rectangle);
    ctx.strokeRect(...rectangle);
    ctx.setLineDash([]);
  }
}

function toVideoImage(event) {
  const rect = canvas.getBoundingClientRect();
  const scale = Math.min(rect.width / canvas.width, rect.height / canvas.height);
  const ox = (rect.width - canvas.width * scale) / 2;
  const oy = (rect.height - canvas.height * scale) / 2;
  return [
    Math.max(0, Math.min(canvas.width, (event.clientX - rect.left - ox) / scale)),
    Math.max(0, Math.min(canvas.height, (event.clientY - rect.top - oy) / scale))
  ];
}

canvas.addEventListener('pointerdown', event => {
  if (!selecting || !state?.loaded) return;
  canvas.setPointerCapture(event.pointerId);
  drag = {start: toVideoImage(event), end: toVideoImage(event)};
  drawVideo();
});

canvas.addEventListener('pointermove', event => {
  if (drag) {
    drag.end = toVideoImage(event);
    drawVideo();
  }
});

canvas.addEventListener('pointerup', async event => {
  if (!drag) return;
  const a = drag.start, b = toVideoImage(event);
  const x = Math.round(Math.min(a[0], b[0]));
  const y = Math.round(Math.min(a[1], b[1]));
  const bbox = [
    x,
    y,
    Math.round(Math.max(a[0], b[0])) - x,
    Math.round(Math.max(a[1], b[1])) - y
  ];
  cancelVideoSelection();
  await mutate('select', {bbox}, 'Video target initialized. Press Play or step one frame.');
});

canvas.addEventListener('pointercancel', cancelVideoSelection);

// ============================================================
// REFERENCE IMAGE SELECTOR
// ============================================================

function setReferenceImage(file) {
  if (!file) return;
  const objectUrl = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    referenceImage = img;
    referenceSelectionBox = null;
    referenceCanvas.width = img.naturalWidth;
    referenceCanvas.height = img.naturalHeight;
    $('reference-panel').hidden = false;
    drawReference();
    URL.revokeObjectURL(objectUrl);
    controls();
  };
  img.onerror = () => {
    URL.revokeObjectURL(objectUrl);
    notice('Could not preview this target image.', true);
  };
  img.src = objectUrl;
}

function drawReference() {
  if (!referenceImage) return;
  referenceCtx.clearRect(0, 0, referenceCanvas.width, referenceCanvas.height);
  referenceCtx.drawImage(referenceImage, 0, 0);

  const selected = referenceDrag || referenceSelectionBox;
  if (selected) {
    const scale = referenceCanvas.width /
      Math.max(1, referenceCanvas.getBoundingClientRect().width);
    referenceCtx.strokeStyle = '#6ee7be';
    referenceCtx.lineWidth = 2 * scale;
    referenceCtx.setLineDash([5 * scale, 3 * scale]);
    referenceCtx.fillStyle = '#6ee7be20';
    const rectangle = [
      selected.start[0],
      selected.start[1],
      selected.end[0] - selected.start[0],
      selected.end[1] - selected.start[1]
    ];
    referenceCtx.fillRect(...rectangle);
    referenceCtx.strokeRect(...rectangle);
    referenceCtx.setLineDash([]);
  }
}

function toReferenceImage(event) {
  const rect = referenceCanvas.getBoundingClientRect();
  const scale = Math.min(
    rect.width / referenceCanvas.width,
    rect.height / referenceCanvas.height
  );
  const ox = (rect.width - referenceCanvas.width * scale) / 2;
  const oy = (rect.height - referenceCanvas.height * scale) / 2;
  return [
    Math.max(0, Math.min(
      referenceCanvas.width,
      (event.clientX - rect.left - ox) / scale
    )),
    Math.max(0, Math.min(
      referenceCanvas.height,
      (event.clientY - rect.top - oy) / scale
    ))
  ];
}

referenceCanvas.addEventListener('pointerdown', event => {
  if (!referenceSelecting || !referenceImage) return;
  referenceCanvas.setPointerCapture(event.pointerId);
  referenceDrag = {
    start: toReferenceImage(event),
    end: toReferenceImage(event)
  };
  drawReference();
});

referenceCanvas.addEventListener('pointermove', event => {
  if (referenceDrag) {
    referenceDrag.end = toReferenceImage(event);
    drawReference();
  }
});

referenceCanvas.addEventListener('pointerup', async event => {
  if (!referenceDrag) return;
  const a = referenceDrag.start, b = toReferenceImage(event);
  const x = Math.round(Math.min(a[0], b[0]));
  const y = Math.round(Math.min(a[1], b[1]));
  const bbox = [
    x,
    y,
    Math.round(Math.max(a[0], b[0])) - x,
    Math.round(Math.max(a[1], b[1])) - y
  ];
  referenceSelectionBox = {
    start: [bbox[0], bbox[1]],
    end: [bbox[0] + bbox[2], bbox[1] + bbox[3]]
  };
  cancelReferenceSelection();
  await mutate(
    'target-select',
    {bbox},
    state?.loaded
      ? 'Reference target selected. Press Play: SEARCHING continues until the object appears.'
      : 'Reference target selected. Open a video; SEARCHING will begin when playback starts.'
  );
});

referenceCanvas.addEventListener('pointercancel', cancelReferenceSelection);

function drawChart(id, key, color) {
  const c = $(id), rect = c.getBoundingClientRect();
  if (!rect.width) return;

  const dpr = window.devicePixelRatio || 1;
  c.width = rect.width * dpr;
  c.height = rect.height * dpr;
  const g = c.getContext('2d');
  g.scale(dpr, dpr);

  const w = rect.width, h = rect.height;
  const left = 55, right = w - 25, top = 24, bottom = h - 36;
  const rows = state?.analytics.rows || [];
  const max = Math.max(1, ...rows.map(r => r[key] || 0)) * 1.1;

  g.font = '10px monospace';
  for (let i = 0; i <= 4; i++) {
    const y = top + (bottom - top) * i / 4;
    g.strokeStyle = '#26323b';
    g.lineWidth = .6;
    g.beginPath();
    g.moveTo(left, y);
    g.lineTo(right, y);
    g.stroke();
    g.fillStyle = '#728795';
    g.textAlign = 'right';
    g.fillText((max * (1 - i / 4)).toFixed(1), left - 12, y + 4);
  }

  if (!rows.length) {
    g.fillStyle = '#79909e';
    g.textAlign = 'center';
    g.fillText('Track a target to build your session history.', w / 2, h / 2);
    return;
  }

  const first = rows[0].frame, last = rows.at(-1).frame;
  const points = rows.map(r => [
    left + (r.frame - first) / Math.max(1, last - first) * (right - left),
    bottom - (r[key] || 0) / max * (bottom - top)
  ]);

  const gradient = g.createLinearGradient(0, top, 0, bottom);
  gradient.addColorStop(0, color + '32');
  gradient.addColorStop(1, color + '00');
  g.beginPath();
  g.moveTo(points[0][0], bottom);
  points.forEach(p => g.lineTo(...p));
  g.lineTo(points.at(-1)[0], bottom);
  g.closePath();
  g.fillStyle = gradient;
  g.fill();

  g.beginPath();
  points.forEach((p, i) => i ? g.lineTo(...p) : g.moveTo(...p));
  g.strokeStyle = color;
  g.lineWidth = 1.7;
  g.stroke();

  if (points.length === 1) {
    g.beginPath();
    g.arc(...points[0], 3, 0, Math.PI * 2);
    g.fillStyle = color;
    g.fill();
  }

  g.fillStyle = '#728795';
  g.textAlign = 'left';
  g.fillText(String(first), left, h - 14);
  g.textAlign = 'right';
  g.fillText(String(last), right, h - 14);
  g.textAlign = 'center';
  g.fillText('Source frame (zero-based)', (left + right) / 2, h - 14);
}

function drawCharts() {
  drawChart('psr-chart', 'psr', '#6ee7be');
  drawChart('latency-chart', 'processing_ms', '#829eff');
}

function route() {
  const next = location.hash.slice(1);
  page = ['studio', 'dsp', 'analytics'].includes(next) ? next : 'studio';
  const titles = {
    studio: ['Tracking Studio', '01 / LOCALIZE + PREDICT', 'A clearer view of every movement.'],
    dsp: ['DSP Lab', '02 / INSPECT + UNDERSTAND', 'Look inside the signal behind the movement.'],
    analytics: ['Session Analytics', '03 / MEASURE + EVALUATE', 'Every frame tells part of the story.']
  };

  document.querySelectorAll('.page').forEach(p => {
    p.hidden = p.id !== `page-${page}`;
  });
  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
    if (a.dataset.page === page) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });

  $('page-title').replaceChildren(
    document.createTextNode(titles[page][0]),
    Object.assign(document.createElement('span'), {textContent: '.'})
  );
  $('breadcrumb').textContent = titles[page][0];
  $('eyebrow').textContent = titles[page][1];
  $('page-description').textContent = titles[page][2];

  if (page === 'analytics') drawCharts();
  if (page === 'dsp' && state?.ready && state?.loaded && !playing) {
    enqueue('snapshot').catch(() => {});
  }
  drawVideo();
}

$('demo').onclick = $('empty-demo').onclick = () => mutate('demo');

$('upload').onclick = () => {
  pause();
  $('video-file').click();
};

function uploadVideo(file) {
  if (!file) return;
  if (file.size > 512 * 1024 * 1024) {
    notice('Please choose a video smaller than 512 MB.', true);
    return;
  }
  const data = new FormData();
  data.append('video', file);
  mutate('upload', data);
}

$('video-file').onchange = event => {
  uploadVideo(event.target.files[0]);
  event.target.value = '';
};

$('target-upload').onclick = () => {
  pause();
  $('target-image-file').click();
};

$('target-image-file').onchange = async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) {
    notice('Please choose a target image smaller than 20 MB.', true);
    return;
  }

  setReferenceImage(file);
  const data = new FormData();
  data.append('target_image', file);
  await mutate(
    'target-upload',
    data,
    'Target image loaded. Press “Select target from image” and drag a tight box around the object.'
  );
};

$('reference-roi').onclick = async () => {
  pause();
  await chain;
  if (!referenceImage) {
    notice('Open the target image again so its native pixels can be selected.', true);
    return;
  }
  location.hash = 'studio';
  referenceSelecting = true;
  $('reference-selection-hint').hidden = false;
  referenceCanvas.style.cursor = 'crosshair';
  notice('Drag a tight rectangle around the target in the uploaded image. The crop is not resized.');
  controls();
};

$('restart').onclick = () => mutate('restart');
$('close-source').onclick = () => mutate(
  'close',
  {},
  'Video source closed. The selected image target is preserved for the next video.'
);
$('play').onclick = togglePlay;
$('step').onclick = () => {
  cancelSelections();
  enqueue('step', {diagnostics: page === 'dsp'})
    .then(s => notice(
      s.ended
        ? 'End of video. Export your session or restart.'
        : `Paused at source frame ${s.index + 1}.`
    ))
    .catch(() => {});
};

$('roi').onclick = async () => {
  pause();
  await chain;
  if (!state?.loaded) return;
  location.hash = 'studio';
  selecting = true;
  $('selection-hint').hidden = false;
  canvas.style.cursor = 'crosshair';
  notice('Drag around a textured target in the video. This switches to normal video-ROI mode.');
  controls();
};

$('snapshot').onclick = () => enqueue('snapshot').catch(() => {});

$('export').onclick = async () => {
  pause();
  await chain;
  try {
    const response = await fetch('/export/');
    if (!response.ok) throw new Error(await response.text());
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = 'signal13_session.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    notice('Session CSV exported. Playback is paused.');
  } catch (e) {
    notice(e.message, true);
  }
};

document.addEventListener('keydown', event => {
  if (event.code === 'Escape') {
    cancelSelections();
    notice('Selection cancelled.');
  }
  if (
    event.code === 'Space'
    && !event.repeat
    && !['INPUT', 'BUTTON', 'TEXTAREA', 'A'].includes(event.target.tagName)
  ) {
    event.preventDefault();
    togglePlay();
  }
});

const stage = $('video-stage');
['dragenter', 'dragover'].forEach(type => {
  stage.addEventListener(type, e => {
    e.preventDefault();
    stage.classList.add('dragover');
  });
});
stage.addEventListener('dragleave', () => stage.classList.remove('dragover'));
stage.addEventListener('drop', e => {
  e.preventDefault();
  stage.classList.remove('dragover');
  if (!busy) uploadVideo(e.dataTransfer.files[0]);
});

window.addEventListener('hashchange', route);
window.addEventListener('resize', () => {
  drawVideo();
  drawReference();
  drawCharts();
  cards.forEach((c, i) => {
    const p = state?.diagnostics[plots[i][0]];
    if (p) positionPeak(c, p);
  });
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden && playing) {
    pause();
    notice('Playback paused while the tab is hidden.');
  }
});

route();
enqueue('state')
  .then(s => {
    if (s.reference?.loaded && !referenceImage) {
      notice('Workspace restored. Re-open the target image only if you want to change its ROI.');
    } else if (s.loaded) {
      notice('Workspace restored. Press Play to continue.');
    }
  })
  .catch(() => {});
