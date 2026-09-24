"""Translation tracker with local tracking and indefinite global re-acquisition."""

from collections import deque
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .fft_engine import fft_2d, next_power_of_two
from .kalman import KalmanFilter
from .phase_correlation import correlate_spectrum, locate_peak
from .preprocessing import crop_center, generate_2d_hann_window, grayscale


@dataclass(frozen=True)
class TrackerConfig:
    # Normal TRACKING thresholds.
    psr_threshold: float = 10.0
    appearance_threshold: float = 0.35
    search_factor: float = 3.0

    # Global SEARCHING / re-acquisition settings.
    global_search_factor: float = 3.0
    strong_appearance: float = 0.50
    strong_psr_factor: float = 1.5
    global_scan_max_tiles_per_frame: int = 4
    global_scan_target_frames: int = 24

    # General settings.
    max_search_side: int = 512
    smoothing: float = 1.0
    acceleration_noise: float = 800.0
    template_learning_rate: float = 0.1


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
        self.locked = False
        self.filter = None
        self.display_center = None
        self.tail = deque(maxlen=60)
        self.misses = 0
        self._scan_grid_key = None
        self._scan_grid = np.empty((0, 2), dtype=float)
        self._scan_index = 0

    # =========================================================
    # TEMPLATE SETUP
    # =========================================================

    def _validate_template(self, target):
        target = np.asarray(target, dtype=np.float32)
        if target.ndim != 2:
            raise ValueError('Target template must be grayscale.')

        h, w = target.shape
        if min(w, h) < 8:
            raise ValueError('Select a target at least 8 × 8 pixels.')

        centered = target - target.mean()
        if float(np.sum(centered * centered)) / target.size < 4.0:
            raise ValueError(
                'This target has too little texture. Include visible edges or a pattern.'
            )
        return target

    def _configure_shapes(self, w, h):
        self.size = (int(w), int(h))

        self.shape = tuple(
            next_power_of_two(int(np.ceil(n * self.config.search_factor)))
            for n in (h, w)
        )
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

        self.window = generate_2d_hann_window(*self.shape)
        self.offset = self._offset(self.shape)

    def _set_reference_template(self, target):
        target = np.asarray(target, dtype=np.float32).copy()
        centered = target - target.mean()
        self.reference_template = target
        self.reference_centered = centered
        self.reference_energy = float(np.sum(centered * centered))
        self._reference_spectra = {}

    def _set_working_template(self, target):
        target = np.asarray(target, dtype=np.float32).copy()
        centered = target - target.mean()
        self.template = target
        self.template_centered = centered
        self.template_energy = float(np.sum(centered * centered))
        self._spectra = {}
        self.template_spectrum = self._spectrum(self.shape, reference=False)

    def _prepare_template(self, target):
        target = self._validate_template(target)
        h, w = target.shape
        self._configure_shapes(w, h)
        self._set_reference_template(target)
        self._set_working_template(target)

        self._scan_grid_key = None
        self._scan_grid = np.empty((0, 2), dtype=float)
        self._scan_index = 0
        self.misses = 0
        self.tail = deque(maxlen=60)
        self.ready = True

    def _offset(self, shape):
        w, h = self.size
        return (
            (shape[1] - w) // 2,
            (shape[0] - h) // 2,
        )

    def _spectrum(self, shape, reference=False):
        if reference:
            cache = self._reference_spectra
            centered = self.reference_centered
        else:
            cache = self._spectra
            centered = self.template_centered

        if shape not in cache:
            w, h = self.size
            ox, oy = self._offset(shape)
            padded = np.zeros(shape, dtype=np.float32)
            padded[oy:oy + h, ox:ox + w] = centered
            cache[shape] = fft_2d(
                padded * generate_2d_hann_window(*shape)
            )
        return cache[shape]

    # =========================================================
    # INITIALIZATION MODES
    # =========================================================

    def initialize(self, frame, bbox):
        """Manual video-ROI mode: target is already located in this frame."""
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

        target = image[y:y + h, x:x + w].copy()
        self._prepare_template(target)
        self._acquire_at((x + w / 2, y + h / 2), first_lock=True)

    def initialize_template(self, target_image):
        """Reference-image mode: know the object appearance, but not its video location."""
        target = grayscale(target_image)
        self._prepare_template(target)

        self.filter = None
        self.display_center = None
        self.locked = False
        self.misses = 0

    # =========================================================
    # GLOBAL GRID
    # =========================================================

    def _global_scan_centers(self, image_shape, shape):
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

            # Overlap enough that a fully visible target can be contained
            # in at least one tile, even near tile boundaries.
            max_step = max(float(crop_size - target_size), 1.0)
            count = max(
                2,
                int(np.ceil((last - first) / max_step)) + 1,
            )
            return np.linspace(first, last, count, dtype=float)

        xs = axis_centres(frame_w, crop_w, target_w)
        ys = axis_centres(frame_h, crop_h, target_h)

        self._scan_grid = np.array(
            [(x, y) for y in ys for x in xs],
            dtype=float,
        )
        self._scan_grid_key = key
        self._scan_index = 0
        return self._scan_grid

    def _next_global_scan_batch(self, image_shape, shape):
        grid = self._global_scan_centers(image_shape, shape)
        total = len(grid)

        if total == 0:
            return np.empty((0, 2), dtype=float)

        target_frames = max(1, int(self.config.global_scan_target_frames))
        desired = max(1, int(np.ceil(total / target_frames)))
        batch_size = min(
            desired,
            max(1, int(self.config.global_scan_max_tiles_per_frame)),
        )

        indices = (np.arange(batch_size) + self._scan_index) % total
        self._scan_index = (self._scan_index + batch_size) % total
        return grid[indices]

    # =========================================================
    # SEARCH / MATCH
    # =========================================================

    def _evaluate_search(self, image, center, shape, reference=False):
        search, origin = crop_center(image, center, shape)
        tapered = (
            search - search.mean()
        ) * generate_2d_hann_window(*shape)

        surface, spectrum = correlate_spectrum(
            self._spectrum(shape, reference=reference),
            tapered,
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

        if reference:
            template_centered = self.reference_centered
            template_energy = self.reference_energy
            template_for_diagnostics = self.reference_template
        else:
            template_centered = self.template_centered
            template_energy = self.template_energy
            template_for_diagnostics = self.template

        denominator = float(
            np.sqrt(np.sum(patch * patch) * template_energy)
        )
        appearance = (
            float(np.sum(patch * template_centered) / denominator)
            if denominator > 1e-9
            else 0.0
        )

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
            'template': template_for_diagnostics,
        }

    @staticmethod
    def _candidate_score(candidate, cfg):
        return (
            candidate['psr'] / max(cfg.psr_threshold, 1e-9)
            + max(candidate['appearance'], 0.0)
        )

    def _acquire_at(self, measurement, first_lock=False):
        if self.filter is None:
            self.filter = KalmanFilter(
                measurement[0],
                measurement[1],
                acceleration_noise=self.config.acceleration_noise,
            )
        elif first_lock:
            self.filter.reacquire(measurement)
        else:
            self.filter.reacquire(measurement)

        self.display_center = self.filter.state[:2].copy()
        self.tail.clear()
        self.tail.append(tuple(self.display_center))
        self.locked = True
        self.misses = 0
        self._scan_index = 0

    # =========================================================
    # MAIN LOOP
    # =========================================================

    def process(self, frame, dt, diagnostics=False):
        if not self.ready:
            raise RuntimeError('Select a target first')

        start = perf_counter()
        cfg = self.config
        image = grayscale(frame)
        strong_psr = cfg.psr_threshold * cfg.strong_psr_factor

        accepted = False
        chosen = None
        reason = ''
        from_global = False

        # -----------------------------------------------------
        # TRACKING: fast local search around Kalman prediction.
        # -----------------------------------------------------
        if self.locked and self.filter is not None:
            predicted = self.filter.predict(dt)
            chosen = self._evaluate_search(
                image,
                predicted,
                self.shape,
                reference=False,
            )

            if not chosen['inside']:
                reason = 'outside image'
            elif chosen['psr'] < cfg.psr_threshold:
                reason = (
                    f'psr {chosen["psr"]:.1f} < {cfg.psr_threshold:.1f}'
                )
            elif chosen['appearance'] < cfg.appearance_threshold:
                reason = (
                    f'appearance {chosen["appearance"]:.2f} '
                    f'< {cfg.appearance_threshold:.2f}'
                )
            else:
                weight = np.clip(
                    (chosen['appearance'] - cfg.appearance_threshold)
                    / (0.8 - cfg.appearance_threshold),
                    0.1,
                    1.0,
                )

                accepted = self.filter.update(
                    chosen['measurement'],
                    r=(self.filter.measurement_noise / weight),
                )

                strong = (
                    chosen['psr'] >= strong_psr
                    and chosen['appearance'] >= cfg.strong_appearance
                )

                if not accepted and strong:
                    self.filter.reacquire(chosen['measurement'])
                    accepted = True
                    reason = 'reacquired locally'
                elif not accepted:
                    reason = 'kalman gate'

            if accepted:
                self.locked = True
                self.misses = 0
            else:
                # Immediately leave local tracking. There is no LOST timeout;
                # the next frame begins indefinite global SEARCHING.
                self.filter.stop()
                self.locked = False
                self.misses = 1
                self._scan_index = 0
                reason = f'{reason}; switching to global search' if reason else 'switching to global search'

        # -----------------------------------------------------
        # SEARCHING: global tiled search, indefinitely.
        # Always compare against the original fixed reference template.
        # -----------------------------------------------------
        else:
            from_global = True
            batch = self._next_global_scan_batch(
                image.shape,
                self.global_shape,
            )

            candidates = [
                self._evaluate_search(
                    image,
                    center,
                    self.global_shape,
                    reference=True,
                )
                for center in batch
            ]

            if candidates:
                chosen = max(
                    candidates,
                    key=lambda c: self._candidate_score(c, cfg),
                )

                trusted = [
                    candidate
                    for candidate in candidates
                    if (
                        candidate['inside']
                        and candidate['psr'] >= strong_psr
                        and candidate['appearance'] >= cfg.strong_appearance
                    )
                ]

                if trusted:
                    chosen = max(
                        trusted,
                        key=lambda c: self._candidate_score(c, cfg),
                    )
                    self._acquire_at(chosen['measurement'])
                    accepted = True
                    reason = 'acquired (global scan)'
                else:
                    self.locked = False
                    self.misses += 1
                    reason = 'global search continuing'
            else:
                self.locked = False
                self.misses += 1
                reason = 'global search grid empty'

        # Adapt only after a trustworthy LOCAL tracking update.
        # The original reference template never changes and is used for
        # every future global re-acquisition.
        if (
            accepted
            and not from_global
            and chosen is not None
            and chosen['psr'] >= strong_psr
            and chosen['appearance'] >= cfg.strong_appearance
            and cfg.template_learning_rate > 0
        ):
            lr = cfg.template_learning_rate
            self._set_working_template(
                (1 - lr) * self.template + lr * chosen['raw_patch']
            )

        status = 'TRACKING' if self.locked and accepted else 'SEARCHING'

        # For a successful local update, preserve the current Kalman output.
        # For global acquisition, _acquire_at already reset the Kalman state.
        if self.filter is not None:
            if self.display_center is None:
                self.display_center = self.filter.state[:2].copy()
            else:
                alpha = cfg.smoothing
                self.display_center += alpha * (
                    self.filter.state[:2] - self.display_center
                )

            if status == 'TRACKING':
                self.tail.append(tuple(self.display_center))

            center_out = tuple(self.display_center)
            velocity_out = tuple(self.filter.state[2:])
        else:
            center_out = (0.0, 0.0)
            velocity_out = (0.0, 0.0)

        plots = {}
        if diagnostics and chosen is not None:
            spectrum = chosen['spectrum']
            shifted = np.roll(
                spectrum,
                (spectrum.shape[0] // 2, spectrum.shape[1] // 2),
                axis=(0, 1),
            )
            plots = {
                'Target crop': chosen['template'].copy(),
                'Windowed search': chosen['tapered'],
                'Log FFT magnitude': np.log1p(np.abs(shifted)),
                'Correlation surface': chosen['surface'].copy(),
            }

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
            center_out,
            measurement,
            velocity_out,
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
