"""Luminance, cached Hann windows and explicitly padded search crops."""
from functools import lru_cache
import numpy as np


def grayscale(frame):
    frame = np.asarray(frame)
    if frame.ndim == 2:
        return frame.astype(np.float32, copy=False)
    return (frame[..., :3].astype(np.float32) @
            np.array([0.299, 0.587, 0.114], dtype=np.float32))


@lru_cache(maxsize=16)
def generate_2d_hann_window(rows, cols):
    def hann(n):
        if n < 1:
            raise ValueError('Window dimensions must be positive')
        return np.ones(1) if n == 1 else .5 - .5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))
    window = np.outer(hann(rows), hann(cols)).astype(np.float32)
    window.flags.writeable = False
    return window


def crop_center(frame, center, shape):
    """Return zero-padded crop and its integer origin (x, y), even at borders."""
    h, w = shape
    x0, y0 = int(round(center[0] - w / 2)), int(round(center[1] - h / 2))
    x1, y1 = max(0, x0), max(0, y0)
    x2, y2 = min(frame.shape[1], x0 + w), min(frame.shape[0], y0 + h)
    patch = np.zeros((h, w), dtype=np.float32)
    if x2 > x1 and y2 > y1:
        patch[y1-y0:y2-y0, x1-x0:x2-x0] = frame[y1:y2, x1:x2]
    return patch, (x0, y0)
