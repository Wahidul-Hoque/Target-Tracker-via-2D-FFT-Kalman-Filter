# Signal13 — Target Tracking Studio

A modular Python desktop application for **Target Tracker via 2D FFT & Kalman Filter**, CSE 220, BUET.

Project team: Wahidul Haque (2305054), Abu Bakar Siddique (2305059).

## Start here

Requires Python 3.10+ and a desktop display. Extract the ZIP, open a terminal in this folder, then:

```bash
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install and launch:

```bash
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, use `.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.venv\Scripts\python.exe main.py` directly. Python's Windows installer normally includes Tkinter. Linux distributions may require their `python3-tk` package; macOS installations need a Python distribution with Tk support. Check with `python -m tkinter`.

## First demonstration

1. Click **Demo**. The starting target is selected automatically.
2. Click **Play**, or press **Space**. The textured square moves; it disappears for 18 frames and then returns. The red box predicts its path during the disappearance.
3. Open **DSP Lab** to see real crop, windowed search, FFT magnitude, and correlation arrays. Space works on every page.
4. Open **Session Analytics** to inspect PSR and core processing time. Export the full session as CSV before restarting or selecting a new target.

For your own footage: **Open video → Select target → drag a tight, textured ROI → Play**. Each target side must be 8–170 source-image pixels with default settings. Letterboxing and reverse-direction dragging are supported. Escape cancels selection. **Step frame** is available while paused. **Restart** rewinds and clears tracking; a real video needs its ROI selected again. The demo reselects its known target automatically.

## Pages

- **Tracking Studio:** video, green accepted FFT measurement, red Kalman output, blue trajectory, PSR, position, speed, source/actual playback rate, core latency, and playback controls.
- **DSP Lab:** persistent Matplotlib plots of the actual numerical pipeline, throttled to 5 Hz when visible. A paused snapshot does not change tracking state.
- **Session Analytics:** the latest 600 tracked frames in charts; full-session CSV is streamed to temporary disk storage, avoiding an ever-growing Python list.

PSR is a peak-to-sidelobe score, **not a confidence percentage**. `OCCLUDED` means no accepted measurement, which may also mean blur, appearance change, or tracking failure. It is not a semantic occlusion detector. `LOST` means prediction has exceeded the configured missing-frame budget. Reselect the target if it leaves the local search region.

## Code map

| File | Responsibility |
|---|---|
| `main.py` | Small application entry point |
| `signal13/core/fft_engine.py` | Handwritten iterative radix-2 FFT/IFFT and cached plans |
| `signal13/core/preprocessing.py` | Luminance, Hann windows, padded crops |
| `signal13/core/phase_correlation.py` | Cross-power normalization, wraparound, PSR, subpixel refinement |
| `signal13/core/kalman.py` | Constant-velocity prediction, measurement gating, Joseph covariance update |
| `signal13/core/tracker.py` | Target initialization, search, acceptance logic, trajectory, configuration |
| `signal13/io/sources.py` | Lazy video decoder and deterministic demo |
| `signal13/io/session.py` | Disk-backed CSV and bounded plot history |
| `signal13/ui/worker.py` | Worker-owned source and processing operations |
| `signal13/ui/app.py` | Main-thread controller, playback scheduling and task completion |
| `signal13/ui/pages.py` | Studio, DSP and Analytics view classes |
| `signal13/ui/video_canvas.py` | Rendering, image-coordinate selection, overlays |
| `signal13/ui/theme.py` | Colors, typography and widget styling |
| `tests/test_core.py` | Numerical and integration regression checks |
| `benchmark.py` | Repeatable core timing and synthetic accuracy measurement |
| `docs/ENGINEERING.md` | Equations, choices, limitations and migration notes |
| `docs/VALIDATION.md` | Verification results and their scope |

## Efficiency and course constraints

Production code calls no `numpy.fft`, SciPy, OpenCV or pretrained tracker. NumPy provides arrays, complex-number arithmetic, reductions and basic matrix multiplication. FFT stages, window generation, normalized phase correlation, the Kalman equations and the 2×2 innovation inverse are implemented explicitly. As in your original code, native NumPy complex arithmetic is used rather than a custom complex-number class.

The FFT batches butterflies across rows; the only FFT-stage Python loop has logarithmic length. FFT plans, windows and the fixed target spectrum are cached. Search crops are power-of-two sized and capped at 512×512. Video is decoded one frame at a time. One background worker performs decoding and DSP; all Tk/Matplotlib updates stay on the main thread. There is at most one in-flight task, with no unbounded frame queue. Slow hardware plays more slowly instead of silently skipping tracking frames.

The GUI uses standard **tkinter/ttk**, matching the proposal and removing the original shell's CustomTkinter dependency. ImageIO uses its FFmpeg backend, fixing the original mismatch between PyAV code and the listed installation dependencies.

## Tests and tuning

```bash
python -m pip install pytest
python -m pytest -q
python benchmark.py
```

Tune the `TrackerConfig` defaults in `core/tracker.py`. Higher PSR/appearance thresholds reject more uncertain matches. Larger search factors increase motion coverage and cost. Do not remove the search-size cap casually. `smoothing=1.0` uses the Kalman output directly; lower values enable extra display-only IIR smoothing at the cost of lag. Filter noise parameters are in `core/kalman.py`. Source timestamps currently use nominal FPS: variable-frame-rate footage is an approximation.

## Scope

This is a translation-only, fixed-template tracker, with local reacquisition and a constant-velocity motion model. It does not yet support scale/rotation changes, multiple targets, live cameras, video export or global object re-identification. Robustness on real footage is **not established by the synthetic demo**. Start with short clips, a distinct textured target, modest inter-frame movement and limited shape change. Identical-looking distractors, severe blur, prolonged occlusion and camera motion can cause failure.

This package is a reorganized implementation based on your uploaded progression. Your original attachments remain separate; use this folder as the new project root.
