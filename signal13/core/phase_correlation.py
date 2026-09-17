"""Normalized cross-power spectrum, wraparound, subpixel peak and PSR."""
import numpy as np
from .fft_engine import fft_2d, ifft_2d


def correlate_spectrum(template_spectrum, search):
    spectrum = fft_2d(search)
    cross = spectrum * template_spectrum.conj()
    magnitude = np.abs(cross)
    normalized = np.divide(cross, magnitude, out=np.zeros_like(cross), where=magnitude > 1e-12)
    return ifft_2d(normalized).real, spectrum


def compute_phase_correlation(template, search):
    if template.shape != search.shape:
        raise ValueError('Template and search must have the same padded shape')
    return correlate_spectrum(fft_2d(template), search)[0]


def unwrap_shift(row, col, shape):
    return tuple(float(p - n if p > n // 2 else p) for p, n in zip((row, col), shape))


def refine_subpixel(surface, row, col):
    offsets = []
    for a, b, c in ((surface[(row-1) % surface.shape[0], col], surface[row, col], surface[(row+1) % surface.shape[0], col]),
                    (surface[row, (col-1) % surface.shape[1]], surface[row, col], surface[row, (col+1) % surface.shape[1]])):
        denominator = a - 2*b + c
        offsets.append(float(np.clip(.5*(a-c)/denominator, -.5, .5)) if denominator < -1e-12 else 0.)
    return tuple(offsets)


def compute_psr(surface, row, col, sidelobe_radius=3):
    rows = (np.arange(-sidelobe_radius, sidelobe_radius+1)+row) % surface.shape[0]
    cols = (np.arange(-sidelobe_radius, sidelobe_radius+1)+col) % surface.shape[1]
    mask = np.ones(surface.shape, dtype=bool)
    mask[np.ix_(rows, cols)] = False
    side = surface[mask]
    if not side.size:
        return 0.
    # A perfect impulse has zero sidelobe variance: it is HIGH confidence.
    return float((surface[row, col]-side.mean()) / max(float(side.std()), 1e-9))


def locate_peak(surface, max_shift=None):
    """max_shift=(rows, cols) ignores peaks that would put the target outside the search crop."""
    if max_shift is None:
        row, col = np.unravel_index(np.argmax(surface), surface.shape)
    else:
        dy = np.abs((np.arange(surface.shape[0]) + surface.shape[0]//2) % surface.shape[0] - surface.shape[0]//2)
        dx = np.abs((np.arange(surface.shape[1]) + surface.shape[1]//2) % surface.shape[1] - surface.shape[1]//2)
        allowed = (dy[:, None] <= max_shift[0]) & (dx[None, :] <= max_shift[1])
        row, col = np.unravel_index(np.argmax(np.where(allowed, surface, -np.inf)), surface.shape)
    dy, dx = unwrap_shift(row, col, surface.shape)
    sy, sx = refine_subpixel(surface, row, col)
    return (dy+sy, dx+sx), compute_psr(surface, row, col)


def locate_displacement(template, search):
    surface = compute_phase_correlation(template, search)
    shift, psr = locate_peak(surface)
    return shift, psr, surface
