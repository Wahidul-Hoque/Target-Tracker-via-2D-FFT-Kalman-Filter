import numpy as np
import fft_engine

"""
In spatial template matching, sliding a template pixel-by-pixel across a search window requires O(M^2 N^2) operations
Utilizing 2D FFT, we can compute the cross-correlation in O(N^2 log N)
2D hann Window: non-periodic edge boundaries from image cropped arbitrarily, introduce severe spectral leakage. This smooths the edges of the image and reduces spectral leakage prior to FFT.
Sub pixel precision: The peak of the correlation surface is not guaranteed to be at an integer pixel location. We can fit a parabola to the peak and its neighbors to estimate the sub-pixel location of the peak.
"""
def compute_phase_correlation(T_tapered, S_tapered, eps=1e-12):
    """
    Computes normalized cross-power spectrum R and correlation surface r.
    Theory Guide Section 3.1 & 3.3
    """
    # 1. 2D FFT both windowed patches
    F_T = fft_engine.fft_2d(T_tapered)
    F_S = fft_engine.fft_2d(S_tapered)
    
    # 2. Cross-power spectrum R = (F_S * conj(F_T)) / (|F_S * conj(F_T)| + eps)
    cross_power = F_S * np.conj(F_T)
    R = cross_power / (np.abs(cross_power) + eps)
    
    # 3. Inverse 2D FFT to get correlation surface r
    r = fft_engine.ifft_2d(R)
    r_real = np.real(r)
    
    return r_real

def unwrap_shift(peak_row, peak_col, shape):
    """
    Remaps DFT wraparound indices to spatial displacements (dy, dx).
    Theory Guide Section 3.4
    """
    M, N = shape
    
    if peak_row > M // 2:
        dy = peak_row - M
    else:
        dy = peak_row
        
    if peak_col > N // 2:
        dx = peak_col - N
    else:
        dx = peak_col
        
    return dy, dx

def refine_subpixel(r, peak_row, peak_col):
    """
    Fits 1D parabolas around integer peak to estimate sub-pixel displacement.
    Theory Guide Section 5.1
    """
    M, N = r.shape
    
    # Sub-pixel shift along row axis (y)
    r_prev_y = r[(peak_row - 1) % M, peak_col]
    r_curr_y = r[peak_row, peak_col]
    r_next_y = r[(peak_row + 1) % M, peak_col]
    denom_y = (r_prev_y - 2 * r_curr_y + r_next_y)
    delta_y = 0.5 * (r_prev_y - r_next_y) / denom_y if abs(denom_y) > 1e-9 else 0.0

    # Sub-pixel shift along col axis (x)
    r_prev_x = r[peak_row, (peak_col - 1) % N]
    r_curr_x = r[peak_row, peak_col]
    r_next_x = r[peak_row, (peak_col + 1) % N]
    denom_x = (r_prev_x - 2 * r_curr_x + r_next_x)
    delta_x = 0.5 * (r_prev_x - r_next_x) / denom_x if abs(denom_x) > 1e-9 else 0.0

    return delta_y, delta_x

def compute_psr(r, peak_row, peak_col, sidelobe_radius=2):
    """
    Computes Peak-to-Sidelobe Ratio (PSR) for confidence scoring.
    Theory Guide Section 5.2
    """
    M, N = r.shape
    peak_val = r[peak_row, peak_col]
    
    # Create mask excluding peak neighborhood
    mask = np.ones((M, N), dtype=bool)
    for r_idx in range(peak_row - sidelobe_radius, peak_row + sidelobe_radius + 1):
        for c_idx in range(peak_col - sidelobe_radius, peak_col + sidelobe_radius + 1):
            mask[r_idx % M, c_idx % N] = False
            
    sidelobe = r[mask]
    mean_sidelobe = np.mean(sidelobe)
    std_sidelobe = np.std(sidelobe)
    
    if std_sidelobe < 1e-9:
        return 0.0
        
    psr = (peak_val - mean_sidelobe) / std_sidelobe
    return float(psr)

def locate_displacement(T_tapered, S_tapered):
    """
    Full phase correlation pipeline yielding displacement (dy, dx) and confidence (PSR).
    """
    r = compute_phase_correlation(T_tapered, S_tapered)
    
    # Integer peak
    peak_row, peak_col = np.unravel_index(np.argmax(r), r.shape)
    
    # Wraparound conversion
    dy_int, dx_int = unwrap_shift(peak_row, peak_col, r.shape)
    
    # Sub-pixel refinement
    delta_y, delta_x = refine_subpixel(r, peak_row, peak_col)
    
    dy = dy_int + delta_y
    dx = dx_int + delta_x
    
    psr = compute_psr(r, peak_row, peak_col)
    
    return (dy, dx), psr, r