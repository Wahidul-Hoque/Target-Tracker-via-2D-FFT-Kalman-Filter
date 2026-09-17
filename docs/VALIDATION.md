# Validation record

Verified 2026-09-09: Python 3.12.14, NumPy 2.3.5, Linux x86_64. Development-environment results are not hardware-independent guarantees.

## Automated checks

`python -m pytest -q`: **19 passed**.

Coverage: complex/rectangular FFT agreement with an independent NumPy oracle; inverse reconstruction; invalid radix-2 sizes; signed/wrapped translations; perfect/blank confidence; fractional shifts; padded border crops and singleton Hann windows; Kalman velocity, prediction, covariance and outlier rejection; synthetic occlusion/recovery; CSV export; prolonged loss; actual MP4 encoding/decoding and EOF via ImageIO FFmpeg.

NumPy FFT/linalg calls are test references only. The application does not call them.

## Controlled demonstration

240 source frames; frame 0 initializes a 40×40 textured target. Motion is 48 px/s horizontally and 10.5 px/s vertically. The target is absent on indices 90–107. No ground-truth coordinates are supplied to the tracker after initialization.

- 239 processed frames; 221 accepted measurements and 18 prediction-only frames.
- All hidden frames reported OCCLUDED; reacquisition at index 108, the first visible frame.
- Mean center error **0.118 px**, maximum **0.442 px**, including hidden frames.
- Median core tracking **2.40 ms**, 95th percentile **2.91 ms** in one run.

Timing excludes decoding, GUI rendering, plotting and playback pacing. Error uses continuous synthetic centers; rendered targets are integer-rounded. Clean constant-velocity motion is favorable to this model and does not establish real-world accuracy.

## Custom FFT timings

| Patch | Median custom 2D FFT |
|---|---:|
| 64×64 | 0.26 ms |
| 128×128 | 1.50 ms |
| 256×256 | 4.69 ms |
| 512×512 | 20.24 ms |

Fifteen timed transforms after warm-up per size; timings vary. Full tracking uses multiple transforms. Large windows can exceed a 30 FPS budget. Run `python benchmark.py` on your own machine.

## Desktop checks

Launched the actual Tk application on a virtual X display. Verified construction, demo initialization, frame stepping, all three pages, 1050×760 minimum resize, reverse-direction ROI dragging, tracking after reselection, play/pause, restart and shutdown. No Tk callback exceptions in the final smoke run.

`studio.png`, `dsp_lab.png`, and `analytics.png` show the actual application. Visual inspection led to compact controls that prevent sidebar metrics from clipping. Virtual-display font rasterization differs from normal desktop rendering.

## Remaining validation

No user-recorded footage was attached. Real-world accuracy, partial occlusion, similar-object ambiguity and variable-FPS timing remain untested. Native Windows/macOS launch was not available. Video support depends on the FFmpeg decoder and input codec. Rotation/scale handling and global reacquisition are outside the implementation scope.
