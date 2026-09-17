"""Iterative radix-2 Cooley–Tukey FFT. No numpy.fft or external DSP calls.

Each stage batches butterflies across all rows using array arithmetic. Only
log2(N) Python iterations are needed per axis. Plans are bounded and cached.
"""
from functools import lru_cache
import numpy as np


def next_power_of_two(n):
    if n < 1:
        raise ValueError('Length must be positive')
    return 1 << (int(n) - 1).bit_length()


@lru_cache(maxsize=16)
def _plan(n):
    if n < 1 or n & (n - 1):
        raise ValueError('FFT axes must have positive power-of-two lengths')
    indexes = np.arange(n, dtype=np.int64)
    reverse = np.zeros(n, dtype=np.int64)
    for _ in range(n.bit_length() - 1):
        reverse = (reverse << 1) | (indexes & 1)
        indexes >>= 1
    twiddles = tuple(np.exp(-2j * np.pi * np.arange(m // 2) / m)
                     for m in (1 << k for k in range(1, n.bit_length())))
    return reverse, twiddles


def _last_axis_fft(values):
    n = values.shape[-1]
    reverse, twiddles = _plan(n)
    out = np.asarray(values, dtype=np.complex128)[..., reverse].copy()
    for k, twiddle in enumerate(twiddles, start=1):
        m = 1 << k
        blocks = out.reshape(*out.shape[:-1], n // m, m)
        even = blocks[..., :m // 2].copy()
        odd = blocks[..., m // 2:] * twiddle
        blocks[..., :m // 2] = even + odd
        blocks[..., m // 2:] = even - odd
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
    return _last_axis_fft(_last_axis_fft(matrix).T).T


def ifft_2d(matrix):
    matrix = np.asarray(matrix)
    return fft_2d(matrix.conj()).conj() / matrix.size
