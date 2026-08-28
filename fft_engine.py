import numpy as np

def fft_1d(x):
    """
    1D Cooley-Tukey Radix-2 FFT.
    x: 1D complex numpy array of length N (N must be a power of 2).
    """
    x = np.asarray(x, dtype=complex)
    N = x.shape[0]
    
    if N <= 1:
        return x
    if N % 2 != 0:
        # If not a power of two, could pad it, but strictly assuming radix-2 lengths
        raise ValueError("Size of x must be a power of 2 for Radix-2 FFT")
    
    even = fft_1d(x[0::2])
    odd = fft_1d(x[1::2])
    
    factor = np.exp(-2j * np.pi * np.arange(N // 2) / N)
    
    return np.concatenate([even + factor * odd, even - factor * odd])

def fft_2d(matrix):
    """
    2D FFT via Row-Column Separability.
    matrix: 2D complex numpy array of size M x N (M, N must be powers of 2).
    """
    matrix = np.asarray(matrix, dtype=complex)
    M, N = matrix.shape
    
    # 1. Apply 1D FFT across every row of the image matrix
    row_fft = np.zeros_like(matrix, dtype=complex)
    for i in range(M):
        row_fft[i, :] = fft_1d(matrix[i, :])
        
    # 2. Apply 1D FFT down every column
    # (Operating down the columns is conceptually similar to transposing and applying to rows)
    col_fft = np.zeros_like(row_fft, dtype=complex)
    for j in range(N):
        col_fft[:, j] = fft_1d(row_fft[:, j])
        
    return col_fft

def ifft_2d(matrix):
    """
    Inverse 2D FFT (IFFT) using the identity:
    F^{-1}{X} = (F{X*})* / (M * N)
    """
    matrix = np.asarray(matrix, dtype=complex)
    M, N = matrix.shape
    
    # Conjugate the input matrix
    conj_matrix = np.conj(matrix)
    
    # Take the 2D FFT of the conjugated matrix
    fft_conj = fft_2d(conj_matrix)
    
    # Conjugate the result and scale by 1 / (M * N)
    return np.conj(fft_conj) / (M * N)

