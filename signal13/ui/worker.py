"""Worker-owned video source and tracker. Never calls Tk or Matplotlib."""
import math
from ..io.sources import DemoSource, VideoSource
from ..core.tracker import TargetTracker

# The Kalman filter works in px/s, so dt = 1/fps must be right: a clip reported
# at 60 fps but really 30 fps made the filter reject a clearly visible U-turn.
MIN_FPS, MAX_FPS, FALLBACK_FPS = 1., 240., 30.


class ProcessingEngine:
    def __init__(self):
        self.source = None
        self.tracker = TargetTracker()
        self.frame = self.result = None
        self.fps, self.fps_warning = FALLBACK_FPS, ''

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
        else:  # OpenCV reports 0 or 1000+ for some containers
            self.fps, self.fps_warning = FALLBACK_FPS, f'Source reports {candidate.fps!r} fps; assuming {FALLBACK_FPS:g} fps.'
        self.tracker = TargetTracker()
        if path is None:
            self.tracker.initialize(frame, candidate.initial_bbox)
        return frame, candidate.name, self.fps, candidate.total, self.tracker.ready

    def select(self, bbox):
        candidate = TargetTracker()
        candidate.initialize(self.frame, bbox)
        self.tracker, self.result = candidate, None

    def step(self, diagnostics):
        frame = self.source.next_frame()
        if frame is None:
            return None
        self.frame = frame
        # frame_step > 1 when repeated frames were skipped: more time passed than one frame.
        dt = getattr(self.source, 'frame_step', 1)/self.fps
        self.result = self.tracker.process(frame, dt, diagnostics) if self.tracker.ready else None
        return frame, self.result, self.source.index

    def snapshot(self):
        """Read-only DSP view of the crop last searched in the current frame; no Kalman state advance."""
        from ..core.preprocessing import grayscale, crop_center, generate_2d_hann_window
        from ..core.phase_correlation import correlate_spectrum
        import numpy as np
        tracker = self.tracker
        box = getattr(self.result, 'search_box', ())
        if box:  # show exactly what was searched (it grows and moves while coasting)
            x, y, w, h = box
            center, shape = (x+w/2, y+h/2), (h, w)
        else:  # nothing searched yet, or an older tracker without search_box
            center, shape = tracker.filter.state[:2], tracker.shape
        spectrum_for = getattr(tracker, '_spectrum', None)
        template_spectrum = spectrum_for(shape) if spectrum_for else tracker.template_spectrum
        patch, _ = crop_center(grayscale(self.frame), center, shape)
        windowed = (patch-patch.mean())*generate_2d_hann_window(*shape)
        surface, spectrum = correlate_spectrum(template_spectrum, windowed)
        shifted = np.roll(spectrum, (spectrum.shape[0]//2, spectrum.shape[1]//2), axis=(0, 1))
        return {'Target crop': tracker.template.copy(), 'Windowed search': windowed,
                'Log FFT magnitude': np.log1p(np.abs(shifted)), 'Correlation surface': surface}

    def close(self):
        if self.source:
            self.source.close()
