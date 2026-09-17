# Engineering notes

## Coordinate contract

Bounding boxes use `(x, y, width, height)` in source pixels. Array addressing is `[row, column] = [y, x]`. Kalman state is `[x, y, vx, vy]`; velocity is pixels/second. The correlation function returns `(dy, dx)`. Video timestamps start at frame index 0; UI frame numbering starts at 1.

The target is mean-subtracted and embedded at a known offset in a power-of-two search-sized zero array. Both reference and search use the same search-sized Hann window. The target spectrum is computed once per selection. A search is cropped around the Kalman prediction with explicit padding at image borders. The candidate location is derived from the crop's *actual integer origin*, the target's padded offset and the recovered shift. It is not added blindly to the previous position; doing that causes cumulative coordinate drift.

## Manual FFT

For each axis, bit-reversal puts inputs in butterfly order. At stage width m:

```
u = even block
v = exp(-2j*pi*k/m) * odd block
first half = u + v
second half = u - v
```

All rows are batched using NumPy views and elementwise operations. A second pass on the transpose gives the 2D FFT by separability. `IFFT(X) = conjugate(FFT(conjugate(X))) / X.size`. No library FFT is used in the application. Tests use NumPy FFT as an independent oracle.

Cached plans have a bounded LRU size. The transform does not mutate callers' inputs. Shape validation rejects zero and non-power-of-two axes. For a rectangular H×W patch, work is O(HW(log H + log W)), storage O(HW).

## Phase correlation and acceptance

`R = S_fft * conjugate(T_fft) / abs(S_fft * conjugate(T_fft))`, with zero-magnitude bins set to zero. The real inverse transform is the correlation surface. Coordinates beyond half an axis are interpreted as negative circular shifts. A three-point concave parabola refines each peak axis by at most half a pixel.

PSR = (peak − sidelobe mean) / sidelobe standard deviation. A wrapped 7×7 peak neighborhood is excluded. A tiny variance floor makes a perfect impulse high confidence while a blank zero surface stays zero confidence. PSR is unbounded and uncalibrated, so displaying it as a percentage would be misleading.

A candidate is accepted only if it lies entirely inside the image, passes PSR, matches the original target appearance by zero-mean normalized correlation, and passes the Kalman innovation gate. Appearance matching costs O(target pixels), not a sliding search. It reduces confident matches to unrelated background edges. It cannot distinguish identical targets.

The fixed template avoids contamination during occlusion. It also limits tolerance to rotations, deformation and long-term appearance changes. Windowing a shifted object does not preserve exact translation equivalence near search edges; keep motion modest relative to search size. The circular correlation's half-window ambiguity remains a mathematical limitation.

## Kalman model

```
F = [[1,0,dt,0], [0,1,0,dt], [0,0,1,0], [0,0,0,1]]
G = [[dt^2/2,0], [0,dt^2/2], [dt,0], [0,dt]]
Q = acceleration_noise^2 * G * G.T
H = [[1,0,0,0], [0,1,0,0]]
R = measurement_noise * I2
```

Prediction: `x = F*x`, `P = F*P*F.T + Q`.

Innovation: `e = z-H*x`, `S = H*P*H.T+R`. The inverse of S is explicitly computed using its 2×2 determinant. Reject when `e.T*inverse(S)*e > 100` (a deliberately permissive engineering threshold, not a calibrated guarantee).

Update: `K = P*H.T*inverse(S)`, `x = x+K*e`. Joseph form updates covariance: `(I-KH)*P*(I-KH).T + K*R*K.T`, followed by symmetrization.

Rejected measurements skip the update. After 30 missed frames, the state stops extrapolating indefinitely and reports LOST; local detection attempts continue at that location. The budget is in frames, so elapsed duration depends on source FPS. Prediction is unconstrained at image boundaries; the red predicted box can leave the visible image. This represents uncertainty rather than clamping the motion model to a false observation.

## Threads, playback and lifecycle

The controller schedules serial worker jobs and polls futures with Tk `after`. Source and tracker mutation only occurs through that worker. Mutating controls are disabled during a job. A pause stops scheduling but lets one in-flight frame commit. Decoding is lazy and readers close on source replacement and app exit. A replacement source is opened successfully before the old source is discarded. Invalid ROI selection similarly preserves the preceding tracker.

The GUI cadence follows nominal source FPS; model `dt` follows the source timeline, not how quickly a computer completes a task. No frames are intentionally dropped. Constant-FPS files are recommended; actual variable timestamps are a future improvement.

Analytics retains only 600 rows in RAM while CSV uses a temporary file. Restart and reselection begin a new session; export first to retain it. Window close waits for the current decoder/processing task, so a stalled decoder could delay shutdown. There is no forced thread cancellation.

## What changed from the uploaded progression

- Recursive per-row/per-column FFT → batched iterative FFT with cached twiddles and bit-reversal.
- Playback-only ROI placeholder → drag selection with exact display/source coordinate conversion.
- Placeholder noise diagnostics → real arrays, persistent image artists, visible-page-only refresh.
- No estimator → complete position/velocity Kalman filter and confidence-gated updates.
- One large window class → dedicated engine, source, session, canvas, theme and page modules.
- Hard-coded 33 ms scheduling → source-FPS pacing and measured display cadence.
- PyAV ingestion / FFmpeg install mismatch → ImageIO FFmpeg consistently.
- Unbounded future work is avoided by one task in flight and capped search geometry.

## Practical next evaluation

Use your own clips with hand-labeled target centers to measure center error, false accepts and recovery time. Include clutter, partial occlusion, blur, target rotation and a similar-looking distractor. Compare the same clips with the Kalman measurement update disabled to show the estimator's role. Do not infer drone/edge-hardware suitability from timing on this development environment. Rotation/scale tracking and adaptive templates are separate extensions, not implemented claims.
