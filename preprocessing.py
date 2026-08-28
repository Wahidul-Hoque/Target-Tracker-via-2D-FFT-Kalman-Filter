import numpy as np

def extract_target_patches(frame1, frame2, target_bbox, search_bbox):
    """
    Extracts the target patch T(x,y) from Frame 1 and candidate search window S(x,y) from Frame 2.
    bbox format: (x, y, width, height) where x,y is the top-left corner.
    Returns: T, S as numpy arrays.
    """
    x_t, y_t, w_t, h_t = [int(v) for v in target_bbox]
    T = frame1[y_t:y_t+h_t, x_t:x_t+w_t]
    
    x_s, y_s, w_s, h_s = [int(v) for v in search_bbox]
    S = frame2[y_s:y_s+h_s, x_s:x_s+w_s]
    
    return T, S

def generate_2d_hann_window(M, N):
    """
    Generates a 2D separable Hann window matrix W(x,y) of size M x N.
    """
    n_M = np.arange(M)
    n_N = np.arange(N)
    
    # Avoid division by zero if M or N is 1
    w_h_M = 0.5 - 0.5 * np.cos(2 * np.pi * n_M / (M - 1)) if M > 1 else np.array([1.0])
    w_h_N = 0.5 - 0.5 * np.cos(2 * np.pi * n_N / (N - 1)) if N > 1 else np.array([1.0])
    
    # 2D window is the outer product of the 1D windows
    W = np.outer(w_h_M, w_h_N)
    return W

def apply_tapering(T, S, W):
    """
    Applies the 2D Hann window (tapering) to the target and search patches.
    Multiplies T and S element-wise by W(x,y).
    """
    T_tapered = T * W
    S_tapered = S * W
    
    return T_tapered, S_tapered

