# Signal13 — FFT + Kalman Object Tracking Workbench

Signal13 is a local Django-based object tracking application that uses a **custom FFT**, **phase correlation**, **PSR**, **NCC appearance matching**, and a **Kalman filter** to track and re-acquire a selected object.

The project supports both direct target selection from a video and target selection from a separate reference image.

---

## Features

- Custom iterative radix-2 Cooley–Tukey FFT
- No `numpy.fft`, SciPy FFT, pretrained detector, or OpenCV tracker
- FFT phase correlation for translation estimation
- Subpixel peak refinement
- PSR confidence measurement
- NCC appearance similarity
- Constant-velocity Kalman filter
- Local tracking around the predicted target position
- Dynamic overlapping global search grid
- Time-sliced global re-acquisition
- Automatic recovery after occlusion, teleportation, or large displacement
- Indefinite searching when the target is not currently visible
- Reference-image target selection at native pixel resolution
- Fixed reference template + adaptive tracking template
- Live search window, target box, Kalman output, and trajectory
- DSP Lab for inspecting FFT/correlation stages
- Session Analytics for PSR and NCC over time
- CSV session export
- Synthetic demo source

---

## How Tracking Works

Signal13 has two main states:

```text
SEARCHING  ── target found ──>  TRACKING
    ^                            |
    |                            |
    └──── tracking failure ──────┘
```

### TRACKING

When the object is locked:

1. Kalman filter predicts the next position.
2. A local search window is created around that prediction.
3. Phase correlation estimates displacement.
4. PSR checks correlation quality.
5. NCC checks visual similarity.
6. A valid measurement updates the Kalman filter.

### SEARCHING

When the target position is unknown:

1. The whole frame is divided into overlapping tiles.
2. Only a small batch of tiles is checked per frame.
3. The scan continues through the frame repeatedly.
4. Each candidate is checked using PSR and NCC.
5. A strong match resets the Kalman filter at the new position.
6. Tracking resumes immediately.

---

## Target Selection

### Option 1 — Select From Video

Use this when the object is already visible.

1. Open a video.
2. Click **Select target in video**.
3. Draw a tight box around the object.
4. Press **Play**.

### Option 2 — Select From Reference Image

Use this when the object may appear later.

1. Click **Open target image**.
2. Select an image.
3. Click **Select target from image**.
4. Draw a tight box around the object.
5. Open the video.
6. Press **Play**.

The selected image ROI is cropped directly from the original image with **no resizing or enlargement**.

The tracker starts in `SEARCHING`, finds the object when it appears, switches to `TRACKING`, and returns to `SEARCHING` whenever the object is lost.

---

## Matching and Confidence

### Phase Correlation

For search spectrum `S` and template spectrum `T`:

```text
R = (S × conj(T)) / |S × conj(T)|
```

The inverse FFT of `R` produces the correlation surface. Its peak gives the estimated translation.

### PSR — Peak-to-Sidelobe Ratio

PSR measures how clearly the best correlation peak stands above the rest of the surface.

Higher PSR generally means a more reliable translation estimate.

PSR is a confidence score, not a probability.

### NCC — Normalized Cross-Correlation

NCC compares the candidate patch with the target template.

Typical interpretation:

```text
1.00   very strong appearance match
0.00   little similarity
< 0    poor/opposite correlation
```

PSR answers **"Is the correlation peak reliable?"**

NCC answers **"Does this candidate look like the target?"**

Both are used together for re-acquisition.

---

## Kalman Filter

The tracker uses the state:

```text
[x, y, vx, vy]
```

where:

- `x, y` = target center
- `vx, vy` = velocity in pixels/second

The Kalman filter predicts the next local search position and smooths accepted measurements.

After global re-acquisition, the filter is reset to the newly detected target position.

---

## Reference and Working Templates

Signal13 keeps two templates:

- **Reference template:** the original selected target. It never changes and is used for global searching.
- **Working template:** used during local tracking and may slowly adapt after strong matches.

This reduces long-term template drift while still allowing small appearance changes during tracking.

---

## Custom FFT

The FFT engine is implemented in:

```text
signal13/core/fft_engine.py
```

It uses a custom iterative radix-2 Cooley–Tukey FFT.

Final optimizations include:

- `float32` image data
- `complex64` FFT data
- cached FFT plans
- cached twiddle factors
- cached Hann windows
- reduced temporary allocations
- optimized inverse FFT
- optimized PSR/peak-search allocations

Search dimensions are rounded to powers of two.

To print the active FFT sizes, set:

```python
FFT_DEBUG_SHAPES = True
```

Example output:

```text
[FFT] 2D shape = 256 x 256
```

---

## Important Tracker Settings

Main tuning values are in:

```text
signal13/core/tracker.py
```

| Setting | Default | Purpose |
|---|---:|---|
| `psr_threshold` | `10.0` | Local PSR threshold |
| `appearance_threshold` | `0.35` | Local NCC threshold |
| `search_factor` | `3.0` | Local search-window scale |
| `global_search_factor` | `3.0` | Global tile scale |
| `strong_appearance` | `0.50` | Strong NCC needed for re-acquisition |
| `strong_psr_factor` | `1.5` | Strong PSR multiplier |
| `global_scan_max_tiles_per_frame` | `4` | Maximum global tiles checked per frame |
| `global_scan_target_frames` | `24` | Approximate frames used for one global sweep |
| `max_search_side` | `512` | Maximum FFT search dimension |
| `template_learning_rate` | `0.1` | Working-template adaptation rate |

With the defaults, strong global re-acquisition requires approximately:

```text
PSR >= 15
NCC >= 0.50
```

---

## Interface

### Tracking Studio

Shows:

- video
- current tracker state
- target box
- FFT measurement
- Kalman output
- trajectory
- active search window
- PSR
- NCC appearance similarity
- position
- speed
- processing time

### DSP Lab

Displays:

- target crop
- windowed search
- log FFT magnitude
- correlation surface
- detected correlation peak

### Session Analytics

Displays:

- PSR over source frames
- NCC appearance similarity over source frames

The complete session can also be exported as CSV.

---

## CSV Export

The exported session contains:

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

---

## Installation

### Requirements

- Python 3.10+
- Modern browser
- Packages listed in `requirements.txt`

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open:

```text
http://127.0.0.1:8000
```

Stop the server with `Ctrl + C`.

---

## Supported Inputs

### Video

Supported:

```text
MP4, AVI, MOV, MKV, WebM, M4V
```

Maximum size:

```text
512 MB
```

H.264 MP4 is recommended.

### Target Image

Supported:

```text
PNG, JPG, JPEG, BMP, WebP
```

Limits:

```text
Maximum file size: 20 MB
Maximum decoded size: 32 megapixels
Minimum selected ROI: 8 × 8 pixels
```

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
│   ├── io/
│   │   ├── sources.py
│   │   └── session.py
│   └── ui/
│       └── worker.py
│
├── studio/
│   ├── templates/studio/index.html
│   ├── static/studio/app.js
│   ├── static/studio/style.css
│   ├── runtime.py
│   └── views.py
│
├── webconfig/
├── main.py
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Main Modules

| File | Role |
|---|---|
| `fft_engine.py` | Custom forward/inverse FFT |
| `phase_correlation.py` | Correlation, peak detection, PSR |
| `preprocessing.py` | Grayscale, Hann window, crops |
| `kalman.py` | Motion prediction and smoothing |
| `tracker.py` | Tracking, global search, re-acquisition |
| `sources.py` | Video/demo input |
| `session.py` | Session logging and CSV export |
| `worker.py` | Connects source and tracker |
| `runtime.py` | Browser workspace state |
| `views.py` | Django API and uploads |
| `app.js` | Frontend interaction and visualization |
| `index.html` | Main UI |
| `style.css` | UI styling |
| `main.py` | Application launcher |

---

## Performance

The system is CPU-based.

Performance depends mainly on:

- target size
- FFT dimensions
- video resolution
- CPU performance
- number of global tiles processed per frame

Normal tracking is faster because it searches only near the Kalman prediction.

Global searching is intentionally time-sliced so the entire frame is not processed with FFT correlation at once.

---

## Limitations

Signal13 is mainly a translation tracker.

For best results:

- use a tight target crop
- choose an object with visible texture or edges
- keep the target at approximately the same scale as the selected template
- avoid large rotations or extreme blur

Current limitations:

- no explicit scale invariance
- no explicit rotation invariance
- single-target tracking
- no semantic object recognition
- similar-looking distractors may cause ambiguous matches
- global re-acquisition speed depends on CPU performance and grid size

---

## Privacy

Signal13 runs locally on:

```text
127.0.0.1:8000
```

Videos and target images are processed locally by the application.

No cloud API or external tracking service is required.

---

