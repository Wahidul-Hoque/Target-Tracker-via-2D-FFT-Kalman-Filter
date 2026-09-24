"""Worker-owned video source and tracker. Never calls Tk or Matplotlib."""
import math

import numpy as np

from ..core.tracker import TargetTracker
from ..io.sources import DemoSource, VideoSource

# The Kalman filter works in px/s, so dt = 1/fps must be right.
MIN_FPS, MAX_FPS, FALLBACK_FPS = 1., 240., 30.


class ProcessingEngine:
    def __init__(self):
        self.source = None
        self.tracker = TargetTracker()
        self.frame = self.result = None
        self.fps, self.fps_warning = FALLBACK_FPS, ''

        # Exact native-resolution crop selected from an uploaded reference image.
        # Keeping it here lets Restart/Open Video preserve reference-image mode.
        self.reference_target = None

    def load(self, path=None):
        candidate = VideoSource(path) if path else DemoSource()
        try:
            frame = candidate.next_frame()
            if frame is None:
                raise ValueError('The source contains no readable frames.')
        except Exception:
            candidate.close()
            raise

        if self.source:
            self.source.close()

        self.source, self.frame, self.result = candidate, frame, None

        try:
            fps = float(candidate.fps)
        except (TypeError, ValueError):
            fps = math.nan

        if math.isfinite(fps) and MIN_FPS <= fps <= MAX_FPS:
            self.fps, self.fps_warning = fps, ''
        else:
            self.fps = FALLBACK_FPS
            self.fps_warning = (
                f'Source reports {candidate.fps!r} fps; '
                f'assuming {FALLBACK_FPS:g} fps.'
            )

        self.tracker = TargetTracker()

        # If a reference-image target was already selected, do not initialize
        # at frame 1. Start in SEARCHING and wait for that object to appear.
        if self.reference_target is not None:
            self.tracker.initialize_template(self.reference_target)
        elif path is None:
            # Preserve the original demo behavior when no image target is active.
            self.tracker.initialize(frame, candidate.initial_bbox)

        return frame, candidate.name, self.fps, candidate.total, self.tracker.ready

    def select(self, bbox):
        """Manual selection directly from the currently displayed video frame."""
        candidate = TargetTracker()
        candidate.initialize(self.frame, bbox)

        # Manual video selection switches out of reference-image mode.
        self.reference_target = None
        self.tracker, self.result = candidate, None

    def select_template(self, target):
        """Use an exact, unscaled image crop as the persistent reference target."""
        target = np.asarray(target).copy()
        candidate = TargetTracker()
        candidate.initialize_template(target)

        self.reference_target = target
        self.tracker, self.result = candidate, None

    def step(self, diagnostics):
        frame = self.source.next_frame()
        if frame is None:
            return None

        self.frame = frame
        dt = getattr(self.source, 'frame_step', 1) / self.fps

        self.result = (
            self.tracker.process(frame, dt, diagnostics)
            if self.tracker.ready
            else None
        )
        return frame, self.result, self.source.index

    def snapshot(self):
        """Read-only DSP view of the crop last searched in the current frame."""
        from ..core.preprocessing import (
            crop_center,
            generate_2d_hann_window,
            grayscale,
        )
        from ..core.phase_correlation import correlate_spectrum

        tracker = self.tracker
        if not tracker.ready:
            raise ValueError('Select a target first.')

        box = getattr(self.result, 'search_box', ())
        if box:
            x, y, w, h = box
            center, shape = (x + w / 2, y + h / 2), (h, w)
        elif tracker.locked and tracker.filter is not None:
            center, shape = tracker.filter.state[:2], tracker.shape
        else:
            # No video position exists yet in reference-image SEARCHING mode.
            center = (self.frame.shape[1] / 2, self.frame.shape[0] / 2)
            shape = tracker.global_shape

        use_reference = not tracker.locked
        template_spectrum = tracker._spectrum(shape, reference=use_reference)

        patch, _ = crop_center(grayscale(self.frame), center, shape)
        windowed = (
            patch - patch.mean()
        ) * generate_2d_hann_window(*shape)
        surface, spectrum = correlate_spectrum(template_spectrum, windowed)

        shifted = np.roll(
            spectrum,
            (spectrum.shape[0] // 2, spectrum.shape[1] // 2),
            axis=(0, 1),
        )

        target = (
            tracker.reference_template
            if use_reference
            else tracker.template
        )
        return {
            'Target crop': target.copy(),
            'Windowed search': windowed,
            'Log FFT magnitude': np.log1p(np.abs(shifted)),
            'Correlation surface': surface,
        }

    def close(self):
        if self.source:
            self.source.close()
