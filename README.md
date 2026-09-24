# Signal13 — FFT + Kalman Object Tracking Workbench

Signal13 is a local browser-based object tracking application built with **Python, Django, NumPy, ImageIO, and a custom FFT implementation**. It tracks a user-selected object using **phase correlation**, validates matches using **PSR (Peak-to-Sidelobe Ratio)** and **NCC (Normalized Cross-Correlation)**, and smooths/predicts motion with a **constant-velocity Kalman filter**.

The final system supports two ways to define a target:

1. **Select the object directly from a video frame.**
2. **Upload a reference image, select the target region from that image at its native pixel resolution, and let the system search the video until that object appears.**

If tracking is lost because of occlusion, teleportation, or a large displacement, Signal13 automatically switches from local tracking to an **indefinite time-sliced global search**. When a strong match is found, the tracker re-locks and continues normal tracking.

---

## Key Features

- Custom **iterative radix-2 Cooley–Tukey FFT**
- No `numpy.fft`, SciPy FFT, OpenCV tracker, or pretrained object tracker
- FFT-based **phase correlation** for translation estimation
- **Subpixel peak refinement**
- **PSR** confidence measurement
- **NCC appearance similarity** measurement
- Constant-velocity **Kalman filter**
- Fast local tracking around the predicted target position
- Dynamic overlapping **global search grid**
- Time-sliced global scanning to control CPU cost
- Automatic re-acquisition after occlusion or sudden target displacement
- Global searching continues indefinitely until the target is found
- Upload a separate target/reference image
- Select a target ROI from the reference image with **no resizing**
- Fixed original reference template for robust re-acquisition
- Adaptive working template during reliable local tracking
- Live visualization of the search window, measurement, Kalman output, and trajectory
- DSP Lab showing internal signal-processing stages
- Session Analytics with **PSR over time** and **NCC appearance score over time**
- CSV export of the complete tracking session
- Local Django web interface with no cloud service required
- Synthetic demo source included

---

## Final Tracking State Model

Signal13 uses a simple two-state tracking model:

```text
                 target found
        ┌──────────────────────────┐
        │                          ▼
    SEARCHING                  TRACKING
 global tiled scan       local FFT + Kalman
        ▲                          │
        │                          │
        └──── tracking fails ──────┘
```

### `TRACKING`

When the target is locked:

1. The Kalman filter predicts the next target position.
2. A small local search window is extracted around that prediction.
3. Phase correlation estimates translation.
4. PSR checks whether the correlation peak is reliable.
5. NCC checks whether the candidate still looks like the target.
6. The Kalman filter accepts or rejects the measurement.
7. Strong local matches may slowly update the working template.

### `SEARCHING`

When no reliable target position is available:

1. The frame is divided dynamically into overlapping search tiles.
2. Only a small batch of tiles is processed during each video frame.
3. The scan continues through the entire frame and loops indefinitely.
4. Global candidates are compared against the **original fixed reference template**.
5. A candidate must satisfy strong PSR and appearance requirements.
6. When accepted, the Kalman filter is reset to the newly detected position.
7. The system immediately returns to `TRACKING`.

There is **no fixed 10-second LOST timeout** in the final version. If the target has not appeared yet, Signal13 simply continues searching.

---

## Target Selection Modes

### 1. Select Target Directly From Video

Use this mode when the target is already visible.

1. Open a video.
2. Pause on a frame where the target is visible.
3. Click **Select target in video**.
4. Drag a tight rectangle around the object.
5. Press **Play**.

The selected video crop becomes both the initial reference and working template.

---

### 2. Select Target From a Reference Image

Use this mode when the object may appear later in the video.

1. Click **Open target image**.
2. Choose a PNG, JPG, JPEG, BMP, or WebP image.
3. Click **Select target from image**.
4. Drag a tight rectangle around the desired object.
5. Open a video.
6. Press **Play**.

The selected ROI is cropped from the original uploaded image at its **native pixel resolution**. Signal13 does not enlarge or resize the selected target crop.

The video begins in `SEARCHING`. The tracker does not need to know the object's initial position. When the object is detected anywhere in the video, Signal13 creates/resets the Kalman state at that location and switches to `TRACKING`.

If the object later disappears or becomes occluded, the system returns to global `SEARCHING` and keeps scanning until the object is found again.

---

## Why Two Templates Are Used

Signal13 maintains two templates internally:

### Fixed Reference Template

The original selected target crop is never modified.

It is used during global re-acquisition so that long-term tracking drift does not permanently change what the system is searching for.

### Adaptive Working Template

During strong, trusted **local** tracking updates, the working template may slowly adapt to small appearance changes.

This gives local tracking some flexibility while preserving the original reference image as a stable identity anchor.

---

## Tracking Pipeline

```text
Video Frame
    │
    ▼
Grayscale Conversion
    │
    ├──────────── TRACKING ────────────┐
    │                                  │
    │                           Kalman Prediction
    │                                  │
    │                           Local Search Window
    │                                  │
    └──────────── SEARCHING ───────┐   │
                                   │   │
                           Global Grid Tile
                                   │   │
                                   ▼   ▼
                              Hann Window
                                   │
                                   ▼
                              Custom 2D FFT
                                   │
                                   ▼
                         Normalized Cross-Power
                                   │
                                   ▼
                             Custom Inverse FFT
                                   │
                                   ▼
                          Correlation Surface
                                   │
                                   ▼
                      Peak + Subpixel Refinement
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                        PSR                 NCC
                         └─────────┬─────────┘
                                   ▼
                           Candidate Validation
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
                  Accept                       Reject
                     │                           │
                     ▼                           ▼
             Kalman Update/Reset         Continue Searching
```

---

## Core Signal Processing

### Grayscale Conversion

Frames are converted to luminance using:

```text
Y = 0.299R + 0.587G + 0.114B
```

The tracking core operates on `float32` grayscale data.

### Hann Window

A 2D Hann window is applied before correlation to reduce FFT boundary discontinuities.

Hann windows are cached by shape.

### Phase Correlation

Let:

- `S` = FFT of the search patch
- `T` = FFT of the padded target template

The normalized cross-power spectrum is:

```text
R = (S × conj(T)) / |S × conj(T)|
```

The inverse FFT of `R` produces the correlation surface. The strongest valid peak estimates the target displacement.

### PSR — Peak-to-Sidelobe Ratio

PSR measures how clearly the main correlation peak stands above the rest of the correlation surface.

A high PSR means the detected displacement is much more distinctive than competing peaks.

PSR is a **correlation confidence score**, not a probability.

### NCC — Normalized Cross-Correlation

After phase correlation proposes a target position, Signal13 compares the candidate image patch with the stored template using normalized cross-correlation.

Conceptually:

```text
NCC = correlation(candidate, template)
      --------------------------------
      candidate energy × template energy
```

Typical interpretation:

```text
NCC ≈ 1.0    very strong appearance match
NCC ≈ 0.0    little appearance similarity
NCC < 0.0    poor/opposite correlation
```

PSR and NCC complement each other:

- **PSR:** "Is there a strong, unique translation peak?"
- **NCC:** "Does the object at that location actually look like the target?"

Using both reduces false re-acquisition.

### Kalman Filter

The motion model uses the state:

```text
[x, y, vx, vy]
```

where:

- `x, y` = target center in pixels
- `vx, vy` = target velocity in pixels/second

The Kalman filter predicts the next local search position and smooths accepted measurements.

When global search finds the target after a large displacement, the filter is hard-reset to the new position and velocity is reset.

---

## Custom FFT Implementation

The FFT engine is implemented in:

```text
signal13/core/fft_engine.py
```

It uses a custom iterative radix-2 Cooley–Tukey algorithm rather than `numpy.fft`.

The final optimized FFT includes:

- `complex64` working precision instead of `complex128`
- `float32` real data
- cached FFT plans
- cached complex64 twiddle factors
- `int32` bit-reversal tables
- vectorized butterfly operations
- reduced temporary array allocation
- in-place inverse-transform conjugation/scaling where possible

The 2D FFT is performed by applying the 1D transform across both matrix axes.

Search dimensions are rounded to powers of two for the radix-2 FFT.

For debugging, `FFT_DEBUG_SHAPES` in `fft_engine.py` can be set to `True` to print the actual FFT sizes being used, such as:

```text
[FFT] 2D shape = 256 x 256
```

---

## Local vs Global Search

### Local Search

Local tracking is designed for normal continuous motion.

Default:

```python
search_factor = 3.0
```

The target dimensions are multiplied by this factor and rounded to the next power of two.

### Global Search

Global search uses the same configurable idea:

```python
global_search_factor = 3.0
```

The entire frame is covered by dynamically generated overlapping tiles.

The grid is based on:

- frame resolution
- target dimensions
- global search-window dimensions

It is **not hardcoded to a particular video resolution**.

To avoid processing the full frame with FFT correlation in one step, only a limited number of tiles are evaluated during each frame.

Default:

```python
global_scan_max_tiles_per_frame = 4
global_scan_target_frames = 24
```

The scan wraps around and repeats for as long as necessary.

---

## Default Tracker Configuration

The main tuning values are in:

```text
signal13/core/tracker.py
```

Current defaults:

| Parameter | Default | Purpose |
|---|---:|---|
| `psr_threshold` | `10.0` | Minimum PSR for normal local tracking |
| `appearance_threshold` | `0.35` | Minimum NCC for normal local tracking |
| `search_factor` | `3.0` | Local search-window scale |
| `global_search_factor` | `3.0` | Global search-tile scale |
| `strong_appearance` | `0.50` | Strong NCC requirement for re-acquisition |
| `strong_psr_factor` | `1.5` | Global strong PSR multiplier |
| `global_scan_max_tiles_per_frame` | `4` | Maximum global tiles evaluated per frame |
| `global_scan_target_frames` | `24` | Approximate frames over which a global sweep is distributed |
| `max_search_side` | `512` | Maximum FFT search dimension |
| `template_learning_rate` | `0.1` | Adaptive local-template update rate |
| `acceleration_noise` | `800.0` | Kalman motion-noise parameter |

With the defaults, strong global re-acquisition requires approximately:

```text
PSR >= 15
NCC >= 0.50
```

These values are intentionally configurable for experimentation.

---

## DSP Lab

The **DSP Lab** exposes the internal signal-processing stages used by the tracker:

- Target crop
- Windowed search patch
- Log FFT magnitude
- Correlation surface
- Correlation peak location

This allows the tracking process to be inspected visually instead of behaving like a black box.

---

## Session Analytics

The Session Analytics page displays:

### Tracking Confidence / PSR

Shows the correlation confidence over the latest session frames.

### Appearance Similarity / NCC

Shows how closely each candidate resembles the target over time.

NCC is displayed on its natural range:

```text
-1.0 to +1.0
```

The browser retains the latest **600 rows** for chart display.

The complete session is still written to the session log and can be exported as CSV.

---

## CSV Export

Click **Export session CSV** to save the tracking session.

The exported data contains:

```text
frame
time_s
status
x
y
vx
vy
measurement_x
measurement_y
psr
appearance
misses
processing_ms
reason
```

This makes it possible to perform additional plotting, evaluation, or offline analysis after a run.

---

## Installation

### Requirements

- Python **3.10+**
- Windows, Linux, or macOS
- Modern browser such as Chrome, Edge, or Firefox

Python packages are listed in `requirements.txt`.

### Windows

Open PowerShell or Command Prompt inside the project folder:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Then open:

```text
http://127.0.0.1:8000
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Then open:

```text
http://127.0.0.1:8000
```

Stop the application with:

```text
Ctrl + C
```

No Node.js, npm, cloud service, or database setup is required.

---

## Supported Inputs

### Video

Supported extensions:

```text
MP4
AVI
MOV
MKV
WebM
M4V
```

Maximum upload size:

```text
512 MB
```

H.264 MP4 is recommended for convenient compatibility.

Video decoding is performed lazily with ImageIO/FFmpeg.

### Reference Target Image

Supported formats:

```text
PNG
JPG / JPEG
BMP
WebP
```

Limits:

```text
Maximum file size: 20 MB
Maximum decoded image size: 32 megapixels
Minimum selected target ROI: 8 × 8 pixels
```

The selected reference ROI must remain entirely inside the uploaded image.

---

## How to Use

### Reference-Image Workflow

```text
1. Start Signal13.
2. Click "Open target image".
3. Choose an image containing the object.
4. Click "Select target from image".
5. Draw a tight box around the target.
6. Open the video.
7. Press Play.
8. Observe SEARCHING while the target is absent.
9. When detected, the state changes to TRACKING.
10. If the target disappears, the system automatically returns to SEARCHING.
11. When it reappears, the tracker re-acquires it automatically.
12. Open DSP Lab or Session Analytics when required.
13. Export the session CSV if needed.
```

### Direct Video Workflow

```text
1. Open a video.
2. Click "Select target in video".
3. Draw a tight box around the visible object.
4. Press Play.
5. If the object is lost, Signal13 automatically switches to global searching.
```

---

## Interface Guide

### Tracking Studio

Displays:

- video frame
- target bounding box
- FFT measurement
- Kalman output
- trajectory
- active search window
- current tracker state
- PSR
- NCC appearance similarity
- target position
- target speed
- processing time per frame

### DSP Lab

Displays internal FFT and correlation data for inspection.

### Session Analytics

Displays PSR and NCC appearance trends and provides session CSV export.

---

## Project Structure

```text
Signal13_Django/
│
├── signal13/
│   ├── core/
│   │   ├── fft_engine.py
│   │   ├── preprocessing.py
│   │   ├── phase_correlation.py
│   │   ├── kalman.py
│   │   └── tracker.py
│   │
│   ├── io/
│   │   ├── sources.py
│   │   └── session.py
│   │
│   └── ui/
│       └── worker.py
│
├── studio/
│   ├── templates/
│   │   └── studio/
│   │       └── index.html
│   │
│   ├── static/
│   │   └── studio/
│   │       ├── app.js
│   │       └── style.css
│   │
│   ├── runtime.py
│   └── views.py
│
├── webconfig/
│   ├── settings.py
│   └── urls.py
│
├── main.py
├── requirements.txt
└── README.md
```

### Important Modules

| File | Responsibility |
|---|---|
| `signal13/core/fft_engine.py` | Custom optimized forward/inverse FFT |
| `signal13/core/preprocessing.py` | Grayscale conversion, Hann window, padded crops |
| `signal13/core/phase_correlation.py` | Phase correlation, peak detection, subpixel refinement, PSR |
| `signal13/core/kalman.py` | Constant-velocity Kalman filter |
| `signal13/core/tracker.py` | Local tracking, template management, global search and re-acquisition |
| `signal13/io/sources.py` | Video decoding and synthetic demo source |
| `signal13/io/session.py` | Session logging and CSV export |
| `signal13/ui/worker.py` | Connects video source and tracking engine |
| `studio/runtime.py` | Per-browser workspace state and data conversion |
| `studio/views.py` | Django API endpoints, uploads, target selection and export |
| `studio/templates/studio/index.html` | Browser interface |
| `studio/static/studio/app.js` | Playback, selection, visualization and analytics |
| `studio/static/studio/style.css` | Interface styling |
| `main.py` | Local Django launcher |

---

## Performance Design

The project is designed to keep computational cost bounded without replacing the custom signal-processing implementation.

Important optimizations include:

- `float32` image processing
- `complex64` FFT computation
- cached FFT plans and twiddle factors
- cached Hann windows
- reduced FFT temporary allocations
- reduced PSR/peak-search allocations
- cached template spectra
- local search during normal tracking
- time-sliced global search instead of full-frame FFT scanning every frame
- lazy video decoding
- repeated-frame skipping for video sources when exact duplicates are produced by decoding

Actual FPS depends on:

- CPU performance
- target size
- FFT search dimensions
- video resolution
- number of global tiles processed per frame

The current implementation is primarily **CPU/NumPy based**. GPU acceleration is not required for operation.

---

## Design Rationale

A continuously full-screen FFT search would be computationally expensive.

Signal13 therefore separates the problem into two modes:

**Local tracking** assumes motion is reasonably continuous and searches only near the Kalman prediction.

**Global searching** is activated only when the target position is unknown. The full frame is divided into smaller overlapping tiles, and those tiles are processed over multiple frames.

This gives the system the ability to recover from:

- complete occlusion
- sudden teleportation
- motion outside the local search window
- a target that is absent at the start of the video
- a target that disappears and later reappears at a different location

without forcing every normal tracking frame to perform a full-screen search.

---

## Current Limitations

Signal13 is primarily a **translation tracker**.

For best results:

- select a tight target ROI
- choose a target with visible texture/edges
- keep the reference-image target at approximately the same scale as it appears in the video
- avoid major target rotation
- avoid extremely severe blur

The current phase-correlation approach does **not** explicitly provide scale invariance or rotation invariance.

Therefore, large changes in object size or orientation may reduce PSR/NCC and prevent detection.

Other limitations:

- single target at a time
- no semantic object recognition
- no pretrained detector
- no multi-object identity management
- no GPU acceleration in the current version
- global re-acquisition latency depends on grid size and available CPU performance
- visually identical distractors may produce ambiguous matches

These are intentional scope boundaries of the current signal-processing-based implementation.

---

## Recommended Target Selection

Good target:

```text
tight crop
distinct edges
visible texture
approximately same scale as video object
minimal unnecessary background
```

Poor target:

```text
large empty background
very low texture
heavy blur
large scale difference
large rotation difference
many identical objects
```

A distinctive target produces stronger PSR and NCC values.

---

## Privacy and Runtime Behavior

Signal13 is designed as a **local application**.

The supplied launcher binds Django to:

```text
127.0.0.1:8000
```

Uploaded videos and target images are processed locally by the running application.

Temporary uploaded video files and per-session resources are managed by the local runtime and cleaned when workspaces expire or the server shuts down.

The application does not require an external API or cloud account.

---

## Repository Submission Notes

For a clean GitHub submission, source code and `requirements.txt` should be committed, but local/generated files should not.

Do **not** commit:

```text
.venv/
__pycache__/
*.pyc
IDE-specific temporary files
large test videos unless explicitly required
```

A `.gitignore` is recommended.

---

## Summary

Signal13 combines classical signal processing and motion estimation into an inspectable object-tracking system:

```text
Custom FFT
    +
Phase Correlation
    +
PSR Confidence
    +
NCC Appearance Validation
    +
Kalman Motion Estimation
    +
Dynamic Global Re-acquisition
    +
Reference-Image Search
    =
Signal13
```

The final system can track a visible target, recover from occlusion or sudden displacement, or search indefinitely for an object selected from a separate reference image before that object ever appears in the video.
