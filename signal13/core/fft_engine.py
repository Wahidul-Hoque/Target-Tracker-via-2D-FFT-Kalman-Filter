"""Optimized custom iterative radix-2 Cooley-Tukey FFT.

No numpy.fft or external DSP FFT calls are used.

Optimizations versus the original implementation:
- complex64 working precision instead of complex128
- complex64 cached twiddle factors
- int32 bit-reversal tables
- one butterfly temporary per radix-2 stage instead of several temporaries
- in-place conjugation/scaling in the inverse transform where possible
- optional one-time FFT-shape reporting so you can see 128x128 vs 256x256
"""

from functools import lru_cache
import numpy as np


# ============================================================
# MANUALLY ADJUSTABLE DEBUG SETTING
# ============================================================

# Set this to True if you want the terminal to report which
# FFT sizes are actually being used, for example:
#
#   [FFT] 2D shape = 256 x 256
#
# Each different shape is printed only once.
FFT_DEBUG_SHAPES = False


# Tracking/phase-correlation does not need double precision.
_COMPLEX_DTYPE = np.complex64
_REAL_DTYPE = np.float32

_seen_2d_shapes = set()


def next_power_of_two(n):
    if n < 1:
        raise ValueError('Length must be positive')
    return 1 << (int(n) - 1).bit_length()


@lru_cache(maxsize=32)
def _plan(n):
    """Cache bit-reversal indexes and complex64 twiddle factors."""
    if n < 1 or n & (n - 1):
        raise ValueError('FFT axes must have positive power-of-two lengths')

    # int32 is sufficient for the search sizes used by this tracker
    # and halves index-table memory compared with int64.
    indexes = np.arange(n, dtype=np.int32)
    reverse = np.zeros(n, dtype=np.int32)

    for _ in range(n.bit_length() - 1):
        reverse = (reverse << 1) | (indexes & 1)
        indexes >>= 1

    twiddles = []

    for k in range(1, n.bit_length()):
        m = 1 << k
        half = m >> 1

        # Build twiddles directly as complex64 rather than creating a
        # complex128 np.exp result and carrying double precision forward.
        angles = (
            np.float32(-2.0 * np.pi / m)
            * np.arange(half, dtype=_REAL_DTYPE)
        )

        twiddle = np.empty(half, dtype=_COMPLEX_DTYPE)
        twiddle.real = np.cos(angles)
        twiddle.imag = np.sin(angles)

        twiddles.append(twiddle)

    return reverse, tuple(twiddles)


def _last_axis_fft(values):
    """FFT along the last axis using vectorized radix-2 butterflies."""
    values = np.asarray(values)

    n = values.shape[-1]
    reverse, twiddles = _plan(n)

    # Advanced indexing performs the bit-reversal permutation and creates
    # the writable output array. Keep the whole transform in complex64.
    out = np.asarray(values, dtype=_COMPLEX_DTYPE)[..., reverse]

    for k, twiddle in enumerate(twiddles, start=1):
        m = 1 << k
        half = m >> 1

        blocks = out.reshape(
            *out.shape[:-1],
            n // m,
            m
        )

        even = blocks[..., :half]
        odd = blocks[..., half:]

        # Only ONE full butterfly temporary is needed for this stage.
        # Original implementation copied "even", then created another
        # array for odd*twiddle, then created add/subtract temporaries.
        temp = np.empty_like(odd)

        np.multiply(
            odd,
            twiddle,
            out=temp
        )

        # Do subtraction first because it still needs the original even.
        np.subtract(
            even,
            temp,
            out=odd
        )

        np.add(
            even,
            temp,
            out=even
        )

    return out


def fft_1d(x):
    x = np.asarray(x)

    if x.ndim != 1:
        raise ValueError('Expected a one-dimensional array')

    return _last_axis_fft(x)


def fft_2d(matrix):
    matrix = np.asarray(matrix)

    if matrix.ndim != 2:
        raise ValueError('Expected a two-dimensional array')

    if FFT_DEBUG_SHAPES:
        shape = tuple(int(v) for v in matrix.shape)

        if shape not in _seen_2d_shapes:
            _seen_2d_shapes.add(shape)
            print(
                f'[FFT] 2D shape = '
                f'{shape[0]} x {shape[1]}'
            )

    # First transform rows, transpose, transform the new rows
    # (original columns), then transpose back.
    #
    # _last_axis_fft creates a fresh writable result during its
    # bit-reversal permutation, so an explicit contiguous transpose
    # copy is unnecessary here.
    return _last_axis_fft(
        _last_axis_fft(matrix).T
    ).T


def ifft_2d(matrix):
    matrix = np.asarray(matrix)

    if matrix.ndim != 2:
        raise ValueError('Expected a two-dimensional array')

    # IFFT(x) = conj(FFT(conj(x))) / N
    #
    # Keep complex64 and perform the final conjugation + scaling in place
    # to avoid extra full-size result arrays.
    conjugated = np.conjugate(
        np.asarray(
            matrix,
            dtype=_COMPLEX_DTYPE
        )
    )

    out = fft_2d(conjugated)

    np.conjugate(
        out,
        out=out
    )

    out *= _REAL_DTYPE(
        1.0 / matrix.size
    )

    return out
