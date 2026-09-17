"""HTTP presentation adapter. All DSP, decoding and CSV logic stays in signal13.

Each browser has an engine and a lock. Requests are serialized; no speculative
frames are queued. Idle sessions and their temporary uploads expire after 30 min.
"""
import atexit
import base64
import io
import math
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image
from matplotlib import colormaps
from signal13.ui.worker import ProcessingEngine
from signal13.io.session import SessionLog


def image_url(array, fmt='JPEG'):
    out = io.BytesIO()
    Image.fromarray(array).save(out, format=fmt)
    return 'data:image/' + fmt.lower() + ';base64,' + base64.b64encode(out.getvalue()).decode()


def native(value):
    if isinstance(value, np.generic):
        return native(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (tuple, list)):
        return [native(v) for v in value]
    if isinstance(value, dict):
        return {k: native(v) for k, v in value.items()}
    return value


class Workspace:
    def __init__(self):
        self.lock = threading.RLock()
        self.touched = time.monotonic()
        self.engine = ProcessingEngine()
        self.log = SessionLog()
        self.directory = tempfile.TemporaryDirectory(prefix='signal13-')
        self.path = None
        self.name = ''
        self.total = None
        self.ended = False
        self.diagnostics = {}
        self.diagnostic_frame = None
        self.last_diagnostic = 0

    def new_log(self):
        self.log.close()
        self.log = SessionLog()
        self.diagnostics = {}
        self.diagnostic_frame = None

    def load(self, path=None, name=None):
        _, source_name, _, self.total, _ = self.engine.load(path)
        old_path = self.path
        self.path = path
        self.name = name or source_name
        self.ended = False
        self.new_log()
        if old_path and old_path != path:
            Path(old_path).unlink(missing_ok=True)

    def plots(self, arrays):
        plots = {}
        for name, original in arrays.items():
            array = np.asarray(original)
            peak = None
            if name == 'Correlation surface':
                array = np.roll(array, (array.shape[0] // 2, array.shape[1] // 2), axis=(0, 1))
                if array.max() > 0:
                    row, col = np.unravel_index(np.argmax(array), array.shape)
                    peak = [float((col + .5) / array.shape[1]), float((row + .5) / array.shape[0])]
            lo, hi = float(array.min()), float(array.max())
            normalized = (array - lo) / max(hi - lo, 1e-9)
            if name in ('Target crop', 'Windowed search'):
                pixels = (normalized * 255).astype(np.uint8)
            else:
                pixels = (colormaps['magma'](normalized)[..., :3] * 255).astype(np.uint8)
            plots[name] = dict(image=image_url(pixels, 'PNG'), minimum=lo, maximum=hi,
                               width=array.shape[1], height=array.shape[0], peak=peak)
        self.diagnostics = plots
        self.diagnostic_frame = self.engine.source.index + 1

    def payload(self, include_image=True):
        e, r = self.engine, self.engine.result
        result = None
        if r is not None:
            result = {key: getattr(r, key) for key in (
                'center', 'measurement', 'velocity', 'bbox_size', 'status', 'psr',
                'appearance', 'misses', 'processing_ms', 'trajectory', 'reason', 'search_box')}
        loaded = e.frame is not None
        return native(dict(
            loaded=loaded, ready=e.tracker.ready, ended=self.ended,
            name=self.name, fps=e.fps, warning=e.fps_warning,
            total=self.total, index=e.source.index if loaded else -1,
            width=e.frame.shape[1] if loaded else 0,
            height=e.frame.shape[0] if loaded else 0,
            image=image_url(e.frame) if loaded and include_image else None,
            result=result,
            target=dict(center=list(e.tracker.filter.state[:2]), size=list(e.tracker.size))
                   if e.tracker.ready else None,
            diagnostics=self.diagnostics, diagnostic_frame=self.diagnostic_frame,
            analytics=dict(total=self.log.total, accepted=self.log.accepted, rows=list(self.log.rows))))

    def close(self):
        self.engine.close()
        self.log.close()
        self.directory.cleanup()


_registry = {}
_registry_lock = threading.RLock()
TTL = 30 * 60
MAX_SESSIONS = 8


@contextmanager
def workspace(key):
    with _registry_lock:
        if key not in _registry:
            if len(_registry) >= MAX_SESSIONS:
                raise ValueError('All 8 workspaces are in use. Close an unused workspace or try later.')
            _registry[key] = Workspace()
        item = _registry[key]
        item.lock.acquire()
        item.touched = time.monotonic()
    try:
        yield item
    finally:
        item.touched = time.monotonic()
        item.lock.release()


def cleanup(all_sessions=False):
    with _registry_lock:
        for key, item in list(_registry.items()):
            if all_sessions or time.monotonic() - item.touched > TTL:
                if item.lock.acquire(blocking=False):
                    try:
                        item.close()
                        del _registry[key]
                    finally:
                        item.lock.release()


def reap():
    while True:
        time.sleep(60)
        cleanup()


threading.Thread(target=reap, daemon=True, name='signal13-cleanup').start()
atexit.register(cleanup, True)
