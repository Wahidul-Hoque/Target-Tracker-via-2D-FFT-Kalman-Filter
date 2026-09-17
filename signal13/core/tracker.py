"""Translation tracker with a slowly adapting template. UI and video decoding are independent."""
from collections import deque
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from .fft_engine import fft_2d, next_power_of_two
from .preprocessing import grayscale, crop_center, generate_2d_hann_window
from .phase_correlation import correlate_spectrum, locate_peak
from .kalman import KalmanFilter


@dataclass(frozen=True)
class TrackerConfig:
    psr_threshold: float = 10.         # no-target noise floor measured at ~5-8
    appearance_threshold: float = .35
    search_factor: float = 3.
    max_search_side: int = 512
    max_misses: int = 30
    smoothing: float = 1.              # Optional display-only IIR; 1 disables extra lag.
    acceleration_noise: float = 800.   # px/s^2; 80 was far below real target manoeuvres
    coast_damping: float = 0.          # 1/s; >0 makes velocity decay while occluded (see notes)
    coast_search_scale: int = 2        # search window grows by this factor while coasting
    strong_psr_factor: float = 1.5     # "clearly the target": reacquire / template update
    strong_appearance: float = .6
    template_learning_rate: float = .1  # 0 keeps the original fixed template


@dataclass
class TrackingResult:
    center: tuple
    measurement: tuple | None
    velocity: tuple
    bbox_size: tuple
    status: str
    psr: float
    appearance: float
    misses: int
    processing_ms: float
    trajectory: tuple
    diagnostics: dict
    reason: str = ''                   # why the measurement was rejected (or 'reacquired')
    search_box: tuple = ()             # (x, y, w, h) of the crop actually searched this frame


class TargetTracker:
    def __init__(self, config=None):
        self.config = config or TrackerConfig()
        self.ready = False

    def _set_template(self, target):
        centered = target-target.mean()
        self.template = target
        self.template_centered = centered
        self.template_energy = float(np.sum(centered*centered))
        self._spectra = {}
        self.template_spectrum = self._spectrum(self.shape)

    def _offset(self, shape):
        w, h = self.size
        return (shape[1]-w)//2, (shape[0]-h)//2

    def _spectrum(self, shape):
        """Windowed, zero-padded template spectrum for a search shape (cached until the template changes)."""
        if shape not in self._spectra:
            w, h = self.size
            ox, oy = self._offset(shape)
            padded = np.zeros(shape, dtype=np.float32)
            padded[oy:oy+h, ox:ox+w] = self.template_centered
            self._spectra[shape] = fft_2d(padded*generate_2d_hann_window(*shape))
        return self._spectra[shape]

    def _next_scan_center(self, image_shape, shape):
        """Cycle crop centres spaced so that any fully visible target fits inside one crop."""
        w, h = self.size
        ox, oy = self._offset(shape)

        def centres(size, target, margin):
            first, last = target/2+margin, size-target/2-margin
            if last <= first:
                return np.array([size/2])
            return np.linspace(first, last, int(np.ceil((last-first)/(2*margin)))+1)

        xs, ys = centres(image_shape[1], w, ox), centres(image_shape[0], h, oy)
        self._scan_index = (getattr(self, '_scan_index', -1)+1) % (len(xs)*len(ys))
        return np.array([xs[self._scan_index % len(xs)], ys[self._scan_index // len(xs)]])

    def initialize(self, frame, bbox):
        image = grayscale(frame)
        x, y, w, h = (int(round(v)) for v in bbox)
        if min(w, h) < 8 or x < 0 or y < 0 or x+w > image.shape[1] or y+h > image.shape[0]:
            raise ValueError('Select a target at least 8 × 8 pixels, entirely inside the image.')
        shape = tuple(next_power_of_two(int(np.ceil(n*self.config.search_factor))) for n in (h, w))
        if max(shape) > self.config.max_search_side:
            raise ValueError('Target too large for the 512-pixel search budget. Select a tighter ROI (up to 170 pixels per side).')
        target = image[y:y+h, x:x+w].copy()
        centered = target-target.mean()
        if float(np.sum(centered*centered)) / target.size < 4.:
            raise ValueError('This target has too little texture. Include visible edges or a pattern.')
        self.shape, self.size = shape, (w, h)
        self.window = generate_2d_hann_window(*shape)
        self.offset = self._offset(shape)
        grown = tuple(min(n*self.config.coast_search_scale, self.config.max_search_side) for n in shape)
        self.coast_shape = grown if self.config.coast_search_scale > 1 else shape
        self._set_template(target)
        self.filter = KalmanFilter(x+w/2, y+h/2, acceleration_noise=self.config.acceleration_noise)
        self.display_center = self.filter.state[:2].copy()
        self.tail = deque([tuple(self.display_center)], maxlen=60)
        self.last_seen = self.filter.state[:2].copy()
        self.misses = 0
        self.ready = True

    def process(self, frame, dt, diagnostics=False):
        if not self.ready:
            raise RuntimeError('Select a target first')
        start = perf_counter()
        cfg = self.config
        coasting = self.misses > 0
        # Extrapolate while occluded (optionally damped); stop extrapolating once LOST.
        predicted = (self.filter.predict(dt, damping=cfg.coast_damping if coasting else 0.)
                     if self.misses < cfg.max_misses else self.filter.state[:2].copy())
        image = grayscale(frame)
        # Prediction error grows while coasting, so look in a bigger area.
        shape = self.coast_shape if coasting else self.shape
        # A constant-velocity guess is wrong when the target stopped or turned behind the
        # occluder, so alternate between the prediction and where it was last seen.
        center = self.last_seen if coasting and self.misses % 2 == 0 else predicted
        if self.misses >= cfg.max_misses and self.misses % 2 == 1:
            center = self._next_scan_center(image.shape, shape)  # LOST: sweep the frame to re-detect
        search, origin = crop_center(image, center, shape)
        tapered = (search-search.mean())*generate_2d_hann_window(*shape)
        surface, spectrum = correlate_spectrum(self._spectrum(shape), tapered)
        w, h = self.size
        ox, oy = self._offset(shape)
        (dy, dx), psr = locate_peak(surface, max_shift=(oy, ox))  # target must fit inside the crop
        measurement = (origin[0]+ox+w/2+dx, origin[1]+oy+h/2+dy)
        mx, my = measurement
        inside = mx-w/2 >= 0 and my-h/2 >= 0 and mx+w/2 <= image.shape[1] and my+h/2 <= image.shape[0]
        raw_patch, _ = crop_center(image, measurement, (h, w))
        patch = raw_patch-raw_patch.mean()
        denominator = float(np.sqrt(np.sum(patch*patch)*self.template_energy))
        appearance = float(np.sum(patch*self.template_centered)/denominator) if denominator > 1e-9 else 0.

        # While coasting the Kalman gate is wide, so demand stronger evidence.
        strong = psr >= cfg.strong_psr_factor*cfg.psr_threshold and appearance >= cfg.strong_appearance
        psr_needed = cfg.psr_threshold*(cfg.strong_psr_factor if coasting else 1.)
        appearance_needed = cfg.strong_appearance if coasting else cfg.appearance_threshold
        reason = ('outside image' if not inside else
                  f'psr {psr:.1f} < {psr_needed:.1f}' if psr < psr_needed else
                  f'appearance {appearance:.2f} < {appearance_needed:.2f}' if appearance < appearance_needed else '')
        accepted = False
        if not reason:
            # Marginal matches move the filter less, protecting the velocity estimate.
            weight = np.clip((appearance-cfg.appearance_threshold)/(.8-cfg.appearance_threshold), .1, 1.)
            accepted = self.filter.update(measurement, r=self.filter.measurement_noise/weight)
            if not accepted and strong:
                self.filter.reacquire(measurement)  # clearly the target: the filter diverged
                accepted, reason = True, 'reacquired'
            elif not accepted:
                reason = 'kalman gate'
        if accepted and strong and cfg.template_learning_rate > 0:
            lr = cfg.template_learning_rate
            self._set_template((1-lr)*self.template + lr*raw_patch)

        if accepted:
            self.last_seen = np.array(measurement, dtype=float)
        self.misses = 0 if accepted else self.misses+1
        if self.misses == cfg.max_misses:
            self.filter.stop()  # don't carry a stale velocity into LOST / reacquisition
        status = 'TRACKING' if accepted else ('OCCLUDED' if self.misses < cfg.max_misses else 'LOST')
        alpha = cfg.smoothing
        self.display_center += alpha*(self.filter.state[:2]-self.display_center)
        self.tail.append(tuple(self.display_center))
        plots = {}
        if diagnostics:
            shifted = np.roll(spectrum, (spectrum.shape[0]//2, spectrum.shape[1]//2), axis=(0, 1))
            plots = {'Target crop': self.template.copy(), 'Windowed search': tapered,
                     'Log FFT magnitude': np.log1p(np.abs(shifted)), 'Correlation surface': surface.copy()}
        return TrackingResult(tuple(self.display_center), measurement if accepted else None,
                              tuple(self.filter.state[2:]), self.size, status, psr, appearance,
                              self.misses, (perf_counter()-start)*1000, tuple(self.tail), plots, reason,
                              (origin[0], origin[1], shape[1], shape[0]))
