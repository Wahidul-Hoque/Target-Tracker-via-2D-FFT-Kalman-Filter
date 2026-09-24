"""Normalized cross-power spectrum, wraparound, subpixel peak and PSR.

Optimized to reduce full-frame temporary allocations while preserving
the original phase-correlation behaviour.
"""

import numpy as np

from .fft_engine import fft_2d, ifft_2d


def correlate_spectrum(template_spectrum, search):
    spectrum = fft_2d(search)

    # One complex cross-power array is still required because `spectrum`
    # is returned for diagnostics.
    cross = spectrum * template_spectrum.conj()

    magnitude = np.abs(cross)

    normalized = np.divide(
        cross,
        magnitude,
        out=np.zeros_like(cross),
        where=magnitude > 1e-12
    )

    return ifft_2d(normalized).real, spectrum


def compute_phase_correlation(template, search):
    if template.shape != search.shape:
        raise ValueError(
            'Template and search must have the same padded shape'
        )

    return correlate_spectrum(
        fft_2d(template),
        search
    )[0]


def unwrap_shift(row, col, shape):
    return tuple(
        float(
            p - n
            if p > n // 2
            else p
        )
        for p, n in zip(
            (row, col),
            shape
        )
    )


def refine_subpixel(surface, row, col):
    offsets = []

    samples = (
        (
            surface[
                (row - 1) % surface.shape[0],
                col
            ],
            surface[row, col],
            surface[
                (row + 1) % surface.shape[0],
                col
            ],
        ),
        (
            surface[
                row,
                (col - 1) % surface.shape[1]
            ],
            surface[row, col],
            surface[
                row,
                (col + 1) % surface.shape[1]
            ],
        ),
    )

    for a, b, c in samples:
        denominator = a - 2 * b + c

        offsets.append(
            float(
                np.clip(
                    0.5 * (a - c) / denominator,
                    -0.5,
                    0.5
                )
            )
            if denominator < -1e-12
            else 0.0
        )

    return tuple(offsets)


def compute_psr(
    surface,
    row,
    col,
    sidelobe_radius=3
):
    """Compute PSR without allocating a full boolean mask + side array."""
    height, width = surface.shape

    rows = (
        np.arange(
            -sidelobe_radius,
            sidelobe_radius + 1,
            dtype=np.int32
        )
        + row
    ) % height

    cols = (
        np.arange(
            -sidelobe_radius,
            sidelobe_radius + 1,
            dtype=np.int32
        )
        + col
    ) % width

    # Only this tiny exclusion patch is copied (normally 7x7),
    # instead of allocating a full HxW boolean mask and then another
    # full sidelobe array.
    excluded = surface[
        np.ix_(rows, cols)
    ]

    count = (
        surface.size
        - excluded.size
    )

    if count <= 0:
        return 0.0

    # Accumulate statistics in float64 for stable PSR values even though
    # the correlation surface itself is float32.
    total_sum = np.sum(
        surface,
        dtype=np.float64
    )

    total_sq = np.einsum(
        'ij,ij->',
        surface,
        surface,
        dtype=np.float64
    )

    excluded_sum = np.sum(
        excluded,
        dtype=np.float64
    )

    excluded_sq = np.einsum(
        'ij,ij->',
        excluded,
        excluded,
        dtype=np.float64
    )

    side_sum = (
        total_sum
        - excluded_sum
    )

    side_sq = (
        total_sq
        - excluded_sq
    )

    mean = (
        side_sum
        / count
    )

    variance = max(
        side_sq / count
        - mean * mean,
        0.0
    )

    std = float(
        np.sqrt(variance)
    )

    # A perfect impulse has zero sidelobe variance:
    # it represents very high confidence.
    return float(
        (
            float(surface[row, col])
            - mean
        )
        / max(
            std,
            1e-9
        )
    )


def _axis_slices(length, max_shift):
    """Return wraparound slices corresponding to allowed FFT shifts."""
    max_shift = int(
        max(
            0,
            min(
                int(max_shift),
                length // 2
            )
        )
    )

    # The complete axis is allowed.
    if max_shift >= length // 2:
        return (slice(0, length),)

    # Only zero displacement.
    if max_shift == 0:
        return (slice(0, 1),)

    # FFT displacement order:
    #
    # 0, +1, +2, ... , -2, -1
    #
    # Therefore the allowed displacement region lives at the
    # beginning and end of the array.
    return (
        slice(
            0,
            max_shift + 1
        ),
        slice(
            length - max_shift,
            length
        ),
    )


def _restricted_peak(
    surface,
    max_shift
):
    """Find the maximum allowed peak without a full HxW allowed mask."""
    row_slices = _axis_slices(
        surface.shape[0],
        max_shift[0]
    )

    col_slices = _axis_slices(
        surface.shape[1],
        max_shift[1]
    )

    best_value = -np.inf
    best_row = 0
    best_col = 0

    # At most four non-copying rectangular views are inspected.
    for row_slice in row_slices:
        for col_slice in col_slices:
            block = surface[
                row_slice,
                col_slice
            ]

            flat_index = int(
                np.argmax(block)
            )

            local_row, local_col = (
                np.unravel_index(
                    flat_index,
                    block.shape
                )
            )

            value = float(
                block[
                    local_row,
                    local_col
                ]
            )

            if value > best_value:
                best_value = value

                best_row = (
                    row_slice.start
                    + local_row
                )

                best_col = (
                    col_slice.start
                    + local_col
                )

    return best_row, best_col


def locate_peak(surface, max_shift=None):
    """Locate correlation peak and return displacement + PSR."""
    if max_shift is None:
        row, col = np.unravel_index(
            np.argmax(surface),
            surface.shape
        )

    else:
        # Original code created full-size dy, dx, allowed and np.where
        # arrays every frame. This version searches at most four valid
        # wraparound views and avoids those large temporary masks.
        row, col = _restricted_peak(
            surface,
            max_shift
        )

    dy, dx = unwrap_shift(
        row,
        col,
        surface.shape
    )

    sy, sx = refine_subpixel(
        surface,
        row,
        col
    )

    return (
        dy + sy,
        dx + sx
    ), compute_psr(
        surface,
        row,
        col
    )


def locate_displacement(template, search):
    surface = compute_phase_correlation(
        template,
        search
    )

    shift, psr = locate_peak(
        surface
    )

    return shift, psr, surface
