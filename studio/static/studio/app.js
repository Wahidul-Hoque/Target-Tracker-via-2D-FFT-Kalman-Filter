'use strict';
const $ = id => document.getElementById(id);
const canvas = $('video'), ctx = canvas.getContext('2d');
let state = null, frameImage = null, playing = false, selecting = false, drag = null;
let page = 'studio', timer = null, chain = Promise.resolve(), busy = 0, playbackEpoch = 0;
let displayedTimes = [];
const plots = [
  ['Target crop', 'Spatial template'], ['Windowed search', 'Mean removed · Hann window'],
  ['Log FFT magnitude', 'Centered frequency spectrum'], ['Correlation surface', 'Centered peak marked +']
];
const cards = [...document.querySelectorAll('.dsp-card')];
cards.forEach((card, i) => {
  card.querySelector('.plot-title').textContent = plots[i][0].toUpperCase();
  card.querySelector('.plot-description').textContent = plots[i][1];
  card.querySelector('img').alt = plots[i][0];
});
const format = (n, digits = 1) => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—';
function notice(text, error = false) { $('notice').textContent = text; $('notice').classList.toggle('error', error); }
function controls() {
  const loaded = !!state?.loaded, ended = !!state?.ended;
  ['upload', 'demo', 'empty-demo'].forEach(id => $(id).disabled = busy > 0);
  ['restart', 'roi', 'close-source'].forEach(id => $(id).disabled = !loaded || busy > 0);
  $('play').disabled = !loaded || ended || busy > 0 || selecting;
  $('step').disabled = !loaded || ended || playing || busy > 0 || selecting;
  $('snapshot').disabled = !state?.ready || busy > 0;
  $('export').disabled = !state?.analytics.total || busy > 0;
  $('play').textContent = playing ? 'Ⅱ Pause' : '▶ Play';
  document.body.classList.toggle('busy', busy > 0);
}
function csrf() { return document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=').slice(1).join('=') || ''; }
function enqueue(action, data = {}, quiet = false) {
  const run = async () => {
    if (!quiet) { busy++; controls(); }
    try {
      const form = data instanceof FormData;
      const response = await fetch(`/api/${action}/`, {method: 'POST', credentials: 'same-origin',
        headers: {'X-CSRFToken': decodeURIComponent(csrf()), ...(!form ? {'Content-Type': 'application/json'} : {})},
        body: form ? data : JSON.stringify(data)});
      if (!response.ok) {
        let message = `Request failed (${response.status}). Reload the page and try again.`;
        try { message = (await response.json()).error || message; } catch (_) {}
        throw new Error(message);
      }
      const next = await response.json();
      await render(next);
      return next;
    } catch (error) {
      pause(); notice(error.message || 'Connection lost. Check that the Django server is running.', true);
      throw error;
    } finally { if (!quiet) busy--; controls(); }
  };
  const result = chain.then(run);
  chain = result.catch(() => {});
  return result;
}
function pause() { playing = false; playbackEpoch++; clearTimeout(timer); controls(); }
function cancelSelection() { selecting = false; drag = null; $('selection-hint').hidden = true; canvas.style.cursor = ''; drawVideo(); controls(); }
async function mutate(action, data = {}, message = '') {
  pause(); cancelSelection(); notice('Preparing your workspace…');
  try {
    const s = await enqueue(action, data);
    displayedTimes = [];
    notice(s.warning || message || (s.ready ? 'Target initialized. Press Play to follow the signal.' : 'Select target, then drag a tight rectangle around a textured object.'));
  } catch (_) {}
}
async function tick(epoch) {
  if (!playing || epoch !== playbackEpoch) return;
  const started = performance.now(), previousIndex = state.index;
  try {
    const s = await enqueue('step', {diagnostics: page === 'dsp'}, true);
    if (!playing || epoch !== playbackEpoch) return;
    if (s.ended) { pause(); notice('End of video. Export your session or restart the source.'); return; }
    displayedTimes.push(performance.now()); displayedTimes = displayedTimes.slice(-30);
    if (displayedTimes.length > 1) {
      const actual = (displayedTimes.length - 1) * 1000 / (displayedTimes.at(-1) - displayedTimes[0]);
      $('frame-label').textContent = `FRAME ${s.index + 1} · ${actual.toFixed(1)} FPS ACTUAL`;
    }
    timer = setTimeout(() => tick(epoch), Math.max(0, Math.max(1, s.index - previousIndex) * 1000 / s.fps - (performance.now() - started)));
  } catch (_) {}
}
function togglePlay() {
  if (!state?.loaded || state.ended || busy || selecting) return;
  if (playing) { pause(); notice('Paused. Inspect the current frame, or step forward.'); }
  else { playing = true; displayedTimes = []; const epoch = ++playbackEpoch; controls(); notice('Following the signal. Press Space to pause.'); tick(epoch); }
}
async function render(s) {
  let image = null;
  if (s.image) {
    image = new Image(); image.src = s.image;
    await image.decode();
  }
  state = s; frameImage = image;
  $('empty').hidden = s.loaded; canvas.hidden = !s.loaded;
  if (s.loaded) { canvas.width = s.width; canvas.height = s.height; }
  $('resolution').textContent = s.loaded ? `${s.width} × ${s.height} · ${format(s.fps, 0)} FPS` : 'NO SOURCE';
  $('source-name').textContent = s.name || 'No source loaded';
  $('source-name').title = s.name || '';
  $('frame-label').textContent = s.loaded ? `FRAME ${s.index + 1} / ${s.total || '—'}` : 'FRAME — / —';
  $('progress').style.width = s.total ? `${100 * (s.index + 1) / s.total}%` : '0';
  const r = s.result;
  $('tracker-status').textContent = r?.status || (s.ready ? 'Ready to track' : s.loaded ? 'Select a target' : 'Awaiting source');
  $('tracker-status').classList.toggle('warning', !!r && r.status !== 'TRACKING');
  $('tracker-reason').textContent = r?.reason || (r ? 'Tracking with the original engine.' : s.ready ? 'Target initialized. Ready when you are.' : 'Your live metrics will appear here.');
  $('psr').textContent = format(r?.psr);
  $('psr-meter').style.width = r ? `${Math.min(100, Math.max(0, r.psr / 30 * 100))}%` : '0';
  $('position').textContent = r ? `${format(r.center[0])} / ${format(r.center[1])}` : '— / —';
  $('speed').textContent = r ? format(Math.hypot(...r.velocity)) : '—';
  $('latency').textContent = format(r?.processing_ms);
  $('recorded').textContent = s.analytics.total.toLocaleString();
  $('accepted').textContent = s.analytics.accepted.toLocaleString();
  $('predicted').textContent = (s.analytics.total - s.analytics.accepted).toLocaleString();
  cards.forEach((card, i) => {
    const plot = s.diagnostics[plots[i][0]], img = card.querySelector('img');
    img.hidden = !plot; card.querySelector('.plot-placeholder').hidden = !!plot;
    card.querySelector('.peak').hidden = true;
    card.querySelector('.plot-shape').textContent = plot ? `${plot.width} × ${plot.height}` : '—';
    card.querySelector('.plot-range').textContent = plot ? `${format(plot.minimum, 2)} … ${format(plot.maximum, 2)}` : '';
    if (plot && img.getAttribute('src') !== plot.image) { img.onload = () => positionPeak(card, plot); img.src = plot.image; }
    else if (plot) positionPeak(card, plot);
  });
  $('dsp-caption').textContent = s.diagnostic_frame ? `Showing source frame ${s.diagnostic_frame} · ${playing ? 'Live diagnostics' : 'Read-only snapshot'}` : 'Select a target and refresh, or play with DSP Lab open.';
  drawVideo(); if (page === 'analytics') drawCharts(); controls();
}
function positionPeak(card, plot) {
  if (!plot.peak || page !== 'dsp') return;
  const img = card.querySelector('img'), holder = card.querySelector('.plot-image'), marker = card.querySelector('.peak');
  const scale = Math.min(holder.clientWidth / plot.width, holder.clientHeight / plot.height);
  marker.style.left = `${(holder.clientWidth - plot.width * scale) / 2 + plot.peak[0] * plot.width * scale}px`;
  marker.style.top = `${(holder.clientHeight - plot.height * scale) / 2 + plot.peak[1] * plot.height * scale}px`;
  marker.hidden = false;
}
function drawVideo() {
  if (!frameImage || !state?.loaded) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(frameImage, 0, 0);
  const scale = canvas.width / Math.max(1, canvas.getBoundingClientRect().width);
  const box = (center, size, color, width = 1.5) => {
    ctx.strokeStyle = color; ctx.lineWidth = width * scale;
    ctx.strokeRect(center[0] - size[0] / 2, center[1] - size[1] / 2, ...size);
  };
  const r = state.result;
  if (r) {
    if (r.search_box?.length) { ctx.strokeStyle = '#97a9b5'; ctx.lineWidth = scale; ctx.setLineDash([4 * scale, 4 * scale]); ctx.strokeRect(...r.search_box); ctx.setLineDash([]); }
    if (r.trajectory.length > 1) { ctx.beginPath(); ctx.strokeStyle = '#829eff'; ctx.lineWidth = 1.5 * scale; r.trajectory.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke(); }
    if (r.measurement) box(r.measurement, r.bbox_size, '#6ee7be');
    box(r.center, r.bbox_size, '#ff8796', 2);
    ctx.font = `${10 * scale}px monospace`; ctx.fillStyle = '#ff8796';
    ctx.fillText(r.status + (r.reason ? ` · ${r.reason}` : ''), Math.max(4, r.center[0] - r.bbox_size[0] / 2), Math.max(14 * scale, r.center[1] - r.bbox_size[1] / 2 - 8 * scale));
  } else if (state.target) box(state.target.center, state.target.size, '#6ee7be', 2);
  if (drag) {
    ctx.strokeStyle = '#6ee7be'; ctx.lineWidth = 2 * scale; ctx.setLineDash([5 * scale, 3 * scale]);
    ctx.fillStyle = '#6ee7be20'; const rectangle = [drag.start[0], drag.start[1], drag.end[0] - drag.start[0], drag.end[1] - drag.start[1]];
    ctx.fillRect(...rectangle); ctx.strokeRect(...rectangle); ctx.setLineDash([]);
  }
}
function toImage(event) {
  const rect = canvas.getBoundingClientRect(), scale = Math.min(rect.width / canvas.width, rect.height / canvas.height);
  const ox = (rect.width - canvas.width * scale) / 2, oy = (rect.height - canvas.height * scale) / 2;
  return [Math.max(0, Math.min(canvas.width, (event.clientX - rect.left - ox) / scale)), Math.max(0, Math.min(canvas.height, (event.clientY - rect.top - oy) / scale))];
}
canvas.addEventListener('pointerdown', event => { if (!selecting || !state?.loaded) return; canvas.setPointerCapture(event.pointerId); drag = {start: toImage(event), end: toImage(event)}; drawVideo(); });
canvas.addEventListener('pointermove', event => { if (drag) { drag.end = toImage(event); drawVideo(); } });
canvas.addEventListener('pointerup', async event => {
  if (!drag) return;
  const a = drag.start, b = toImage(event), x = Math.round(Math.min(a[0], b[0])), y = Math.round(Math.min(a[1], b[1]));
  const bbox = [x, y, Math.round(Math.max(a[0], b[0])) - x, Math.round(Math.max(a[1], b[1])) - y];
  cancelSelection(); await mutate('select', {bbox}, 'Target initialized. Press Play or step one frame.');
});
canvas.addEventListener('pointercancel', cancelSelection);
function drawChart(id, key, color) {
  const c = $(id), rect = c.getBoundingClientRect(); if (!rect.width) return;
  const dpr = window.devicePixelRatio || 1; c.width = rect.width * dpr; c.height = rect.height * dpr;
  const g = c.getContext('2d'); g.scale(dpr, dpr);
  const w = rect.width, h = rect.height, left = 55, right = w - 25, top = 24, bottom = h - 36;
  const rows = state?.analytics.rows || [], max = Math.max(1, ...rows.map(r => r[key] || 0)) * 1.1;
  g.font = '10px monospace';
  for (let i = 0; i <= 4; i++) {
    const y = top + (bottom - top) * i / 4;
    g.strokeStyle = '#26323b'; g.lineWidth = .6; g.beginPath(); g.moveTo(left, y); g.lineTo(right, y); g.stroke();
    g.fillStyle = '#728795'; g.textAlign = 'right'; g.fillText((max * (1 - i / 4)).toFixed(1), left - 12, y + 4);
  }
  if (!rows.length) { g.fillStyle = '#79909e'; g.textAlign = 'center'; g.fillText('Track a target to build your session history.', w / 2, h / 2); return; }
  const first = rows[0].frame, last = rows.at(-1).frame;
  const points = rows.map(r => [left + (r.frame - first) / Math.max(1, last - first) * (right - left), bottom - (r[key] || 0) / max * (bottom - top)]);
  const gradient = g.createLinearGradient(0, top, 0, bottom); gradient.addColorStop(0, color + '32'); gradient.addColorStop(1, color + '00');
  g.beginPath(); g.moveTo(points[0][0], bottom); points.forEach(p => g.lineTo(...p)); g.lineTo(points.at(-1)[0], bottom); g.closePath(); g.fillStyle = gradient; g.fill();
  g.beginPath(); points.forEach((p, i) => i ? g.lineTo(...p) : g.moveTo(...p)); g.strokeStyle = color; g.lineWidth = 1.7; g.stroke();
  if (points.length === 1) { g.beginPath(); g.arc(...points[0], 3, 0, Math.PI * 2); g.fillStyle = color; g.fill(); }
  g.fillStyle = '#728795'; g.textAlign = 'left'; g.fillText(String(first), left, h - 14); g.textAlign = 'right'; g.fillText(String(last), right, h - 14);
  g.textAlign = 'center'; g.fillText('Source frame (zero-based)', (left + right) / 2, h - 14);
}
function drawCharts() { drawChart('psr-chart', 'psr', '#6ee7be'); drawChart('latency-chart', 'processing_ms', '#829eff'); }
function route() {
  const next = location.hash.slice(1); page = ['studio', 'dsp', 'analytics'].includes(next) ? next : 'studio';
  const titles = {studio: ['Tracking Studio', '01 / LOCALIZE + PREDICT', 'A clearer view of every movement.'], dsp: ['DSP Lab', '02 / INSPECT + UNDERSTAND', 'Look inside the signal behind the movement.'], analytics: ['Session Analytics', '03 / MEASURE + EVALUATE', 'Every frame tells part of the story.']};
  document.querySelectorAll('.page').forEach(p => p.hidden = p.id !== `page-${page}`);
  document.querySelectorAll('.nav-link').forEach(a => { a.classList.toggle('active', a.dataset.page === page); if (a.dataset.page === page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  $('page-title').replaceChildren(document.createTextNode(titles[page][0]), Object.assign(document.createElement('span'), {textContent: '.'}));
  $('breadcrumb').textContent = titles[page][0]; $('eyebrow').textContent = titles[page][1]; $('page-description').textContent = titles[page][2];
  if (page === 'analytics') drawCharts();
  if (page === 'dsp' && state?.ready && !playing) enqueue('snapshot').catch(() => {});
  drawVideo();
}
$('demo').onclick = $('empty-demo').onclick = () => mutate('demo');
$('upload').onclick = () => { pause(); $('video-file').click(); };
function upload(file) {
  if (!file) return;
  if (file.size > 512 * 1024 * 1024) { notice('Please choose a video smaller than 512 MB.', true); return; }
  const data = new FormData(); data.append('video', file); mutate('upload', data);
}
$('video-file').onchange = event => { upload(event.target.files[0]); event.target.value = ''; };
$('restart').onclick = () => mutate('restart');
$('close-source').onclick = () => mutate('close', {}, 'Source closed. Open a video or start the demo.');
$('play').onclick = togglePlay;
$('step').onclick = () => { cancelSelection(); enqueue('step', {diagnostics: page === 'dsp'}).then(s => notice(s.ended ? 'End of video. Export your session or restart.' : `Paused at source frame ${s.index + 1}.`)).catch(() => {}); };
$('roi').onclick = async () => { pause(); await chain; if (!state?.loaded) return; location.hash = 'studio'; selecting = true; $('selection-hint').hidden = false; canvas.style.cursor = 'crosshair'; notice('Drag around a textured target. Keep each side between 8 and 170 original pixels.'); controls(); };
$('snapshot').onclick = () => enqueue('snapshot').catch(() => {});
$('export').onclick = async () => {
  pause(); await chain;
  try {
    const response = await fetch('/export/'); if (!response.ok) throw new Error(await response.text());
    const url = URL.createObjectURL(await response.blob()), a = document.createElement('a');
    a.href = url; a.download = 'signal13_session.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    notice('Session CSV exported. Playback is paused.');
  } catch (e) { notice(e.message, true); }
};
document.addEventListener('keydown', event => {
  if (event.code === 'Escape') { cancelSelection(); notice('Selection cancelled.'); }
  if (event.code === 'Space' && !event.repeat && !['INPUT', 'BUTTON', 'TEXTAREA', 'A'].includes(event.target.tagName)) { event.preventDefault(); togglePlay(); }
});
const stage = $('video-stage');
['dragenter', 'dragover'].forEach(type => stage.addEventListener(type, e => { e.preventDefault(); stage.classList.add('dragover'); }));
stage.addEventListener('dragleave', () => stage.classList.remove('dragover'));
stage.addEventListener('drop', e => { e.preventDefault(); stage.classList.remove('dragover'); if (!busy) upload(e.dataTransfer.files[0]); });
window.addEventListener('hashchange', route);
window.addEventListener('resize', () => { drawVideo(); drawCharts(); cards.forEach((c, i) => { const p = state?.diagnostics[plots[i][0]]; if (p) positionPeak(c, p); }); });
document.addEventListener('visibilitychange', () => { if (document.hidden && playing) { pause(); notice('Playback paused while the tab is hidden.'); } });
route(); enqueue('state').then(s => { if (s.loaded) notice('Workspace restored. Press Play to continue.'); }).catch(() => {});
