"""Translation tracker with global time-sliced re-acquisition."""

from collections import deque
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .fft_engine import fft_2d, next_power_of_two
from .kalman import KalmanFilter
from .phase_correlation import correlate_spectrum, locate_peak
from .preprocessing import (
    crop_center,
    generate_2d_hann_window,
    grayscale,
)


@dataclass(frozen=True)
class TrackerConfig:
    # =========================================================
    # NORMAL TRACKING SETTINGS
    # =========================================================
    psr_threshold: float = 10.0
    appearance_threshold: float = 0.35

    # Normal TRACKING search-window size.
    search_factor: float = 3.0

    # =========================================================
    # GLOBAL RE-ACQUISITION SETTINGS
    # =========================================================
    # Manually adjustable global search-window size.
    global_search_factor: float = 3.0

    # Strong appearance requirement for global re-acquisition.
    strong_appearance: float = 0.50

    # strong_psr = psr_threshold * strong_psr_factor
    strong_psr_factor: float = 1.5

    # Maximum global tiles processed per video frame.
    global_scan_max_tiles_per_frame: int = 4

    # Approximate number of processed frames over which to
    # distribute one complete global sweep.
    global_scan_target_frames: int = 24

    # Real-time duration before OCCLUDED becomes LOST.
    occluded_timeout_seconds: float = 10.0

    # =========================================================
    # GENERAL SETTINGS
    # =========================================================
    max_search_side: int = 512

    smoothing: float = 1.0
    acceleration_noise: float = 800.0

    template_learning_rate: float = 0.1

    # Retained for compatibility with older code/config.
    max_misses: int = 30
    coast_damping: float = 0.0
    coast_search_scale: int = 2


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
    reason: str = ''
    search_box: tuple = ()


class TargetTracker:

    def __init__(self, config=None):
        self.config = config or TrackerConfig()
        self.ready = False

    # =========================================================
    # TEMPLATE
    # =========================================================

    def _set_template(self, target):
        centered = target - target.mean()

        self.template = target
        self.template_centered = centered
        self.template_energy = float(np.sum(centered * centered))

        self._spectra = {}
        self.template_spectrum = self._spectrum(self.shape)

    def _offset(self, shape):
        w, h = self.size
        return (
            (shape[1] - w) // 2,
            (shape[0] - h) // 2,
        )

    def _spectrum(self, shape):
        if shape not in self._spectra:
            w, h = self.size
            ox, oy = self._offset(shape)

            padded = np.zeros(shape, dtype=np.float32)
            padded[oy:oy + h, ox:ox + w] = self.template_centered

            window = generate_2d_hann_window(*shape)
            self._spectra[shape] = fft_2d(padded * window)

        return self._spectra[shape]

    # =========================================================
    # GLOBAL GRID
    # =========================================================

    def _global_scan_centers(self, image_shape, shape):
        """Create a dynamic overlapping grid over the complete frame."""
        key = (
            tuple(image_shape[:2]),
            tuple(shape),
            tuple(self.size),
        )

        if getattr(self, '_scan_grid_key', None) == key:
            return self._scan_grid

        frame_h, frame_w = image_shape[:2]
        target_w, target_h = self.size
        crop_h, crop_w = shape

        def axis_centres(frame_size, crop_size, target_size):
            if crop_size >= frame_size:
                return np.array([frame_size / 2.0], dtype=float)

            first = crop_size / 2.0
            last = frame_size - crop_size / 2.0
            max_step = max(float(crop_size - target_size), 1.0)
            count = max(2, int(np.ceil((last - first) / max_step)) + 1)

            return np.linspace(first, last, count, dtype=float)

        xs = axis_centres(frame_w, crop_w, target_w)
        ys = axis_centres(frame_h, crop_h, target_h)

        self._scan_grid = np.array(
            [(x, y) for y in ys for x in xs],
            dtype=float
        )

        self._scan_grid_key = key
        self._scan_index = 0

        return self._scan_grid

    # =========================================================
    # GLOBAL SCAN BATCH
    # =========================================================

    def _next_global_scan_batch(self, image_shape, shape):
        """Return a small number of grid tiles per video frame."""
        grid = self._global_scan_centers(image_shape, shape)
        total = len(grid)

        if total == 0:
            return np.empty((0, 2), dtype=float)

        target_frames = max(1, int(self.config.global_scan_target_frames))
        desired = max(1, int(np.ceil(total / target_frames)))
        batch_size = min(
            desired,
            max(1, int(self.config.global_scan_max_tiles_per_frame))
        )

        indices = (np.arange(batch_size) + self._scan_index) % total
        self._scan_index = (self._scan_index + batch_size) % total

        return grid[indices]

    # =========================================================
    # SEARCH ONE WINDOW
    # =========================================================

    def _evaluate_search(self, image, center, shape):
        search, origin = crop_center(image, center, shape)

        tapered = (search - search.mean()) * generate_2d_hann_window(*shape)

        surface, spectrum = correlate_spectrum(
            self._spectrum(shape),
            tapered
        )

        w, h = self.size
        ox, oy = self._offset(shape)

        (dy, dx), psr = locate_peak(surface, max_shift=(oy, ox))

        measurement = (
            origin[0] + ox + w / 2 + dx,
            origin[1] + oy + h / 2 + dy,
        )

        mx, my = measurement

        inside = (
            mx - w / 2 >= 0
            and my - h / 2 >= 0
            and mx + w / 2 <= image.shape[1]
            and my + h / 2 <= image.shape[0]
        )

        raw_patch, _ = crop_center(image, measurement, (h, w))
        patch = raw_patch - raw_patch.mean()

        denominator = float(np.sqrt(np.sum(patch * patch) * self.template_energy))

        if denominator > 1e-9:
            appearance = float(np.sum(patch * self.template_centered) / denominator)
        else:
            appearance = 0.0

        return {
            'measurement': measurement,
            'inside': inside,
            'psr': float(psr),
            'appearance': appearance,
            'raw_patch': raw_patch,
            'tapered': tapered,
            'surface': surface,
            'spectrum': spectrum,
            'origin': origin,
            'shape': shape,
        }

    # =========================================================
    # CANDIDATE SCORE
    # =========================================================

    @staticmethod
    def _candidate_score(candidate, cfg):
        psr_score = candidate['psr'] / max(cfg.psr_threshold, 1e-9)
        appearance_score = max(candidate['appearance'], 0.0)
        return psr_score + appearance_score

    # =========================================================
    # INITIALIZATION
    # =========================================================

    def initialize(self, frame, bbox):
        image = grayscale(frame)
        x, y, w, h = (int(round(v)) for v in bbox)

        if (
            min(w, h) < 8
            or x < 0
            or y < 0
            or x + w > image.shape[1]
            or y + h > image.shape[0]
        ):
            raise ValueError(
                'Select a target at least 8 × 8 pixels, entirely inside the image.'
            )

        # Normal tracking window.
        self.shape = tuple(
            next_power_of_two(int(np.ceil(n * self.config.search_factor)))
            for n in (h, w)
        )

        # Independent global search window.
        self.global_shape = tuple(
            next_power_of_two(int(np.ceil(n * self.config.global_search_factor)))
            for n in (h, w)
        )

        if max(self.shape) > self.config.max_search_side:
            raise ValueError('Normal tracking search window is too large.')

        if max(self.global_shape) > self.config.max_search_side:
            raise ValueError(
                'Global search window is too large. Reduce global_search_factor.'
            )

        target = image[y:y + h, x:x + w].copy()
        centered = target - target.mean()

        if float(np.sum(centered * centered)) / target.size < 4.0:
            raise ValueError(
                'This target has too little texture. Include visible edges or a pattern.'
            )

        self.size = (w, h)
        self.window = generate_2d_hann_window(*self.shape)
        self.offset = self._offset(self.shape)

        self._set_template(target)

        self.filter = KalmanFilter(
            x + w / 2,
            y + h / 2,
            acceleration_noise=self.config.acceleration_noise
        )

        self.display_center = self.filter.state[:2].copy()
        self.tail = deque([tuple(self.display_center)], maxlen=60)
        self.last_seen = self.filter.state[:2].copy()
        self.misses = 0

        # Real wall-clock timer for OCCLUDED -> LOST.
        self.occluded_started_at = None
        self._scan_grid_key = None
        self._scan_grid = np.empty((0, 2), dtype=float)
        self._scan_index = 0

        self.ready = True

    # =========================================================
    # MAIN PROCESS
    # =========================================================

    def process(self, frame, dt, diagnostics=False):
        if not self.ready:
            raise RuntimeError('Select a target first')

        start = perf_counter()
        cfg = self.config
        image = grayscale(frame)
        recovering = self.misses > 0
        strong_psr = cfg.psr_threshold * cfg.strong_psr_factor

        accepted = False
        reason = ''
        chosen = None

        # =====================================================
        # NORMAL TRACKING
        # =====================================================

        if not recovering:
            predicted = self.filter.predict(dt)
            chosen = self._evaluate_search(image, predicted, self.shape)

            if not chosen['inside']:
                reason = 'outside image'

            elif chosen['psr'] < cfg.psr_threshold:
                reason = f'psr {chosen["psr"]:.1f} < {cfg.psr_threshold:.1f}'

            elif chosen['appearance'] < cfg.appearance_threshold:
                reason = f'appearance {chosen["appearance"]:.2f} < {cfg.appearance_threshold:.2f}'

            else:
                weight = np.clip(
                    (chosen['appearance'] - cfg.appearance_threshold)
                    / (0.8 - cfg.appearance_threshold),
                    0.1,
                    1.0
                )

                accepted = self.filter.update(
                    chosen['measurement'],
                    r=(self.filter.measurement_noise / weight)
                )

                strong = (
                    chosen['psr'] >= strong_psr
                    and chosen['appearance'] >= cfg.strong_appearance
                )

                if not accepted and strong:
                    self.filter.reacquire(chosen['measurement'])
                    accepted = True
                    reason = 'reacquired'

                elif not accepted:
                    reason = 'kalman gate'

        # =====================================================
        # OCCLUDED / LOST GLOBAL SEARCH
        # =====================================================

        else:
            batch = self._next_global_scan_batch(image.shape, self.global_shape)
            candidates = [
                self._evaluate_search(image, center, self.global_shape)
                for center in batch
            ]

            if candidates:
                chosen = max(candidates, key=lambda c: self._candidate_score(c, cfg))
                trusted = [
                    candidate for candidate in candidates
                    if (
                        candidate['inside']
                        and candidate['psr'] >= strong_psr
                        and candidate['appearance'] >= cfg.strong_appearance
                    )
                ]

                if trusted:
                    chosen = max(trusted, key=lambda c: self._candidate_score(c, cfg))
                    self.filter.reacquire(chosen['measurement'])
                    accepted = True
                    reason = 'reacquired (global scan)'

                else:
                    elapsed = (
                        perf_counter() - self.occluded_started_at
                        if self.occluded_started_at is not None
                        else 0.0
                    )
                    remaining = max(0.0, cfg.occluded_timeout_seconds - elapsed)

                    if elapsed >= cfg.occluded_timeout_seconds:
                        reason = 'lost: global search continuing'
                    else:
                        reason = f'occluded: global search ({remaining:.1f}s before LOST)'

            else:
                reason = 'global search grid empty'

        # =====================================================
        # TEMPLATE UPDATE
        # =====================================================

        if chosen is not None:
            strong = (
                chosen['psr'] >= strong_psr
                and chosen['appearance'] >= cfg.strong_appearance
            )
        else:
            strong = False

        if accepted and strong and cfg.template_learning_rate > 0:
            lr = cfg.template_learning_rate
            self._set_template((1 - lr) * self.template + lr * chosen['raw_patch'])

        # =====================================================
        # STATE TRANSITIONS
        # =====================================================

        if accepted:
            self.last_seen = np.array(chosen['measurement'], dtype=float)
            self.misses = 0
            self.occluded_started_at = None
            self._scan_index = 0

        else:
            if self.misses == 0:
                self.filter.stop()
                self._scan_index = 0
                self.occluded_started_at = perf_counter()

            self.misses += 1

        # =====================================================
        # STATUS
        # =====================================================

        if accepted:
            status = 'TRACKING'
        else:
            elapsed = (
                perf_counter() - self.occluded_started_at
                if self.occluded_started_at is not None
                else 0.0
            )

            if elapsed >= cfg.occluded_timeout_seconds:
                status = 'LOST'
            else:
                status = 'OCCLUDED'

        # =====================================================
        # DISPLAY
        # =====================================================

        alpha = cfg.smoothing
        self.display_center += alpha * (self.filter.state[:2] - self.display_center)
        self.tail.append(tuple(self.display_center))

        # =====================================================
        # DIAGNOSTICS
        # =====================================================

        plots = {}
        if diagnostics and chosen is not None:
            spectrum = chosen['spectrum']
            shifted = np.roll(
                spectrum,
                (spectrum.shape[0] // 2, spectrum.shape[1] // 2),
                axis=(0, 1)
            )

            plots = {
                'Target crop': self.template.copy(),
                'Windowed search': chosen['tapered'],
                'Log FFT magnitude': np.log1p(np.abs(shifted)),
                'Correlation surface': chosen['surface'].copy(),
            }

        # =====================================================
        # OUTPUT VALUES
        # =====================================================

        if chosen is None:
            psr = 0.0
            appearance = 0.0
            measurement = None
            search_box = ()
        else:
            psr = chosen['psr']
            appearance = chosen['appearance']
            measurement = chosen['measurement'] if accepted else None
            origin = chosen['origin']
            used_shape = chosen['shape']
            search_box = (
                origin[0],
                origin[1],
                used_shape[1],
                used_shape[0],
            )

        return TrackingResult(
            tuple(self.display_center),
            measurement,
            tuple(self.filter.state[2:]),
            self.size,
            status,
            psr,
            appearance,
            self.misses,
            (perf_counter() - start) * 1000,
            tuple(self.tail),
            plots,
            reason,
            search_box,
        )
    