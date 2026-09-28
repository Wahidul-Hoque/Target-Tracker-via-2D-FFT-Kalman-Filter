# FALCON — Signal 13
### Fast Adaptive Localization via Correlation & Kalman-filter Observation Network

> A CPU-based, browser-served object tracker that **locks on, stays on and tracks the object** — no pretrained models, no GPU, no black boxes.

---

## What Is FALCON?

A falcon locks onto fast-moving prey mid-flight and re-acquires it the instant it reappears from behind an obstacle.  
That is exactly what this system does.

**FALCON** is a local, browser-based object tracker built from scratch.  
You select a target — from the video itself, or from a separate reference image.  
FALCON tracks it using a **custom 2D FFT phase correlation engine**, validates every match with **PSR + NCC sanity checks**, and keeps a **Kalman filter** predicting where to look next.

When the target disappears, FALCON doesn't give up. It quietly switches to a **time-sliced global grid search** and keeps scanning until the object is found again.

---

## The Acronym, Letter by Letter

| Letter | Stands For | What It Does |
|--------|-----------|--------------|
| **F** | Fast | Searches only a small local region, not the whole frame |
| **A** | Adaptive | Working template slowly updates to small appearance changes |
| **L** | Localization | Finds where the target is, frame to frame |
| **C** | Correlation | Custom FFT phase correlation estimates the displacement |
| **O** | Observation | PSR + NCC act as dual sanity checks on every match |
| **N** | Network | Full pipeline: Django app, DSP modules, live analytics |

---

## Key Features

- **Custom iterative radix-2 Cooley–Tukey FFT** — zero `numpy.fft`, zero SciPy, zero OpenCV tracker
- **2D phase correlation** for sub-pixel displacement estimation
- **PSR** (Peak-to-Sidelobe Ratio) confidence scoring
- **NCC** (Normalized Cross-Correlation) appearance validation
- **Constant-velocity Kalman filter** for motion prediction and smoothing
- **Two-state design**: `TRACKING` ↔ `SEARCHING` — clean, honest, no hidden states
- **Time-sliced global grid search** — CPU-safe re-acquisition without frame drops
- **Fixed reference template** anchors re-acquisition back to the true target
- **Dual template system** — reference (fixed) + working (slowly adaptive)
- **Reference-image target selection** — select a target that hasn't appeared yet
- **Live DSP visualization** — search window, FFT magnitude, correlation surface, peak
- **Session Analytics** — PSR and NCC plotted over every frame
- **CSV export** — full session data for offline analysis
- **100% local** — runs on `127.0.0.1:8000`, no cloud, no API keys

---

## How It Works

FALCON operates in exactly two states:

```
SEARCHING ── strong PSR + NCC match ──► TRACKING
    ▲                                       │
    └──────────── local match fails ◄───────┘
```

### While TRACKING

Every frame:
1. Kalman filter **predicts** the next target center
2. A local search window is extracted around that prediction
3. **Custom 2D FFT** computes the cross-power spectrum
4. Inverse FFT yields the correlation surface → peak = estimated displacement
5. **Sub-pixel parabolic refinement** sharpens the location
6. **PSR** checks: is the peak sharp and distinctive?
7. **NCC** checks: does this region actually look like the target?
8. Pass → Kalman **update**. Fail → switch to `SEARCHING`

### While SEARCHING

1. The frame is divided into overlapping grid tiles
2. Only a **few tiles per frame** are checked (default: 4) — keeps CPU load stable
3. Each tile is matched against the **fixed reference template** (no drift)
4. A tile passing strong PSR ≥ 15 and NCC ≥ 0.50 triggers re-acquisition
5. Kalman filter resets to the new position → back to `TRACKING`

> The tracker stays in `SEARCHING` indefinitely. There is no final failure — useful when the target appears from a reference image and may not show up until much later in the video.

---

## Project Structure

```
Signal13/
│
├── signal13/                  # Core tracking engine
│   ├── core/
│   │   ├── fft_engine.py      # Custom iterative radix-2 FFT
│   │   ├── phase_correlation.py  # Cross-power spectrum, peak, PSR
│   │   ├── preprocessing.py   # Grayscale, mean-subtraction, Hann window
│   │   ├── kalman.py          # Constant-velocity Kalman filter
│   │   └── tracker.py         # TRACKING / SEARCHING state machine
│   ├── io/
│   │   ├── sources.py         # Video input & synthetic demo source
│   │   └── session.py         # Session logging, CSV export
│   └── ui/
│       └── worker.py          # Connects source → tracker
│
├── studio/                    # Django app (UI layer)
│   ├── templates/studio/index.html
│   ├── static/studio/app.js
│   ├── static/studio/style.css
│   ├── runtime.py             # Browser workspace state
│   └── views.py               # Django API, file uploads
│
├── webconfig/                 # Django project settings
├── main.py                    # One-command launcher
├── requirements.txt
├── FALCON.pdf                 # Project presentation slides
└── README.md
```

---

## Getting Started

### Requirements

- Python **3.10+**
- Any modern browser
- Dependencies in `requirements.txt`

### Install & Run — Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Install & Run — Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.  
Stop the server with `Ctrl + C`.

---

## Target Selection

### From the Video

Best when the object is already on screen at the start.

1. Open a video file
2. Click **Select target in video**
3. Draw a tight bounding box around the object
4. Press **Play**

### From a Reference Image

Best when the object may appear later in the video.

1. Click **Open target image** → select an image file
2. Click **Select target from image**
3. Draw a tight bounding box around the object
4. Open the video and press **Play**

The tracker starts in `SEARCHING`, finds the object when it appears, locks on, and automatically re-acquires if it disappears.  
The ROI is taken at native resolution — **no resizing, no interpolation artifacts**.

---

## Supported Formats

| Input | Formats | Limits |
|-------|---------|--------|
| Video | `MP4`, `AVI`, `MOV`, `MKV`, `WebM`, `M4V` | 512 MB max · H.264 MP4 recommended |
| Reference image | `PNG`, `JPG`, `JPEG`, `BMP`, `WebP` | 20 MB · 32 MP decoded · ROI ≥ 8×8 px |

---

## Tracker Settings

Main tuning knobs live in `signal13/core/tracker.py`:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `psr_threshold` | `10.0` | Minimum PSR to accept a local match |
| `appearance_threshold` | `0.35` | Minimum NCC to accept a local match |
| `search_factor` | `3.0` | Local search window scale multiplier |
| `global_search_factor` | `3.0` | Global tile size scale multiplier |
| `strong_appearance` | `0.50` | NCC required for global re-acquisition |
| `strong_psr_factor` | `1.5` | PSR multiplier for global re-acquisition |
| `global_scan_max_tiles_per_frame` | `4` | Tiles checked per frame during search |
| `global_scan_target_frames` | `24` | Frames budgeted for one full global sweep |
| `max_search_side` | `512` | Maximum FFT search dimension (px) |
| `template_learning_rate` | `0.1` | Working-template adaptation speed |

Default global re-acquisition requires: **PSR ≥ 15** and **NCC ≥ 0.50**

---

## FFT Engine Details

Located in `signal13/core/fft_engine.py`. Key optimizations:

- `float32` pixel data / `complex64` FFT data
- Cached FFT plans, twiddle factors, and Hann windows
- Reduced temporary allocations
- Optimized inverse FFT path
- Search dimensions rounded to powers of two


---

## Interface Panels

### Tracking Studio
Live video overlay showing: tracker state · target box · Kalman prediction · trajectory · active search window · PSR · NCC · position · speed · processing time (ms)

### DSP Lab
Frame-by-frame signal inspection: target crop → windowed search → log FFT magnitude → correlation surface → detected peak

### Session Analytics
PSR and NCC plotted over every source frame. Full session exportable as CSV.

**CSV columns:** `frame · time_s · status · x · y · vx · vy · measurement_x · measurement_y · psr · appearance · misses · processing_ms · reason`

---

## Limitations

FALCON is a **translation tracker** — honest about what it does and doesn't do:

- No scale invariance — a target at a very different size than the template will weaken matching
- No rotation invariance — large rotations can break PSR/NCC
- Single-target only — tracks one selected identity at a time
- No semantic understanding — matches pixels, not concepts
- Similar-looking distractors can cause wrong re-acquisition
- Global search has latency — a very briefly visible target may be missed
- CPU-bound — the custom FFT is educational and transparent, but slower than optimized library or GPU FFTs

**Best results:** tight crop · object with clear texture or edges · consistent scale · minimal rotation or extreme blur

---

## Privacy

Everything runs locally on your machine at `127.0.0.1:8000`.  
No video, image, or tracking data ever leaves your computer.  
No cloud API. No telemetry. No accounts.

---

## Authors

**Abu Bakar Siddique** (2305059) · **Wahidul Hoque** (2305054)  
Signal 13 — September 2026

---
