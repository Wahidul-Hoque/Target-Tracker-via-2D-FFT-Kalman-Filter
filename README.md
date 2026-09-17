# Signal13 — Django Motion Workbench

A new browser GUI for your existing FFT + Kalman tracking project. This is a local Python application: Django runs on your computer and the interface opens in your browser.

## Start here (Windows)

Use Python 3.10 or newer. Open a terminal in this extracted folder, where `main.py` is located:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Open **http://127.0.0.1:8000** in Chrome, Edge, or Firefox. Leave the terminal running. Press Ctrl+C in the terminal to stop the application. No database setup, migrations, Node.js, npm, cloud account or frontend build is needed.

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

The equivalent Django command is `python manage.py runserver 127.0.0.1:8000 --noreload`. The virtual environment must be active when using this shorter command. If port 8000 is occupied, use port 8001 and open the matching URL.

## Use the interface

1. Click **Load demo** for the original synthetic example, with its target already selected. Or click **Open video** / drag a video into the preview. Supported extensions: MP4, AVI, MOV, MKV, WebM, M4V, up to 512 MB; decoding support depends on FFmpeg. H.264 MP4 is a convenient choice.
2. For an uploaded video, click **Select target** and drag a tight box around the object. Size restrictions remain those of your original engine: 8–170 source pixels per side, entirely inside the image, with visible texture. Selection correctly accounts for browser resizing and letterboxing. Escape cancels selection.
3. Click **Play** or press Space outside buttons/links. **Pause** finishes any current frame; **Step one frame** advances once. **Restart** reloads the source and starts a fresh session. Uploaded videos require selecting a target again after restart, matching the original application.
4. Inspect the green FFT measurement, pink Kalman output, blue trajectory and dashed search area. Tracker status, PSR, position, speed and core processing time are live values from the original engine.
5. Open **DSP Lab** for target crop, windowed search, log FFT magnitude and correlation surface. Plots refresh at most 5 times/second while this view is open. **Refresh snapshot** inspects the current frame without advancing tracking. The displayed source-frame number identifies the snapshot.
6. Open **Session Analytics** for PSR and processing-time plots, accepted measurements and prediction-only counts. **Export session CSV** pauses playback and downloads every recorded row with the original fields. Charts retain the latest 600 rows, just like the Tkinter GUI.
7. **Close source** releases the decoder, removes the temporary video and clears the log. Export before closing, restarting or selecting a new target if you need to retain the current session.

## Scope: GUI only

Every original file in `signal13/`, including `signal13/ui/worker.py`, remains byte-for-byte unchanged. The original tests, benchmark and engineering notes are also preserved.

- `signal13/core/`: unchanged FFT, preprocessing, phase correlation, Kalman and tracker logic/configuration.
- `signal13/io/`: unchanged video/demo source behavior and disk-backed CSV logger.
- `signal13/ui/worker.py`: unchanged ProcessingEngine, reused directly by Django.
- `signal13/ui/`: original Tkinter interface retained as reference; Django does not import the Tk widgets.
- `main.py`: now launches the Django GUI instead of Tkinter.
- `requirements.txt`: only adds Django 5.2.
- `webconfig/`: new Django settings, routing and WSGI entrypoint.
- `studio/runtime.py`: browser-session isolation, serialization of engine access, display image encoding and cleanup.
- `studio/views.py`: GUI operations: load, select, step, snapshot, restart, close and export.
- `studio/templates/studio/index.html`, `studio/static/studio/`: new HTML, CSS and browser controls.
- `studio/tests.py`: tests for the new adapter, including comparison with the original engine.
- `README_TKINTER_ORIGINAL.md`: your original README, preserved.

The interface converts frame/diagnostic arrays to images solely for display. It passes the original decoded frame to the tracker. It does not recompress tracking input, retune filters, change thresholds, change target reacquisition or use browser timing as the Kalman `dt`. Source FPS and skipped-repeat handling still come from ProcessingEngine.

## Local session behavior

- One server process owns the live trackers. Use the provided launcher (no auto-reload). Do not run this version with multiple WSGI workers: each process would have a separate tracker registry.
- Each browser cookie session gets a separate workspace; tabs in the same browser share it. Use one active tab per workspace. Private windows/separate browser profiles give independent workspaces.
- Requests are serialized per workspace, and the browser waits for a frame before requesting the next. This bounds processing work. Playback targets the source FPS but may be slower due to Python processing, image encoding, network requests and browser rendering. Actual FPS is shown during playback.
- Hidden tabs pause playback. Refreshing the page restores the current workspace in the same running process, paused.
- Up to 8 workspaces can exist. Workspaces expire after 30 minutes without API activity; a minute-based cleanup loop releases decoders, logs and uploaded files. Server shutdown cleans up temporary workspaces too. Workspaces do not persist across server restarts. Download CSV before leaving.
- Unknown video frame totals display “—”, preserving the decoder's choice to avoid expensive full-video counting. The progress line fills for sources with a known total (the demo).
- All styling and JavaScript are local. No CDN, external font, analytics service or external API is required at runtime.
- This is a local desktop GUI replacement, not a publicly hosted multi-user service. The launcher binds only to 127.0.0.1. CSRF protection, signed browser sessions, upload extension/size checks and session isolation are included. Internet deployment would require separate authentication, deployment and process-lifecycle work.

## Checks

```bash
python manage.py check
python manage.py test studio
python -m pip install pytest
python -m pytest tests -q
```

See `docs/DJANGO_VALIDATION.md` for actual results and a pre-existing core-test failure. It has intentionally not been fixed because this change is limited to the GUI.

## Django references

The new GUI uses Django's documented [AJAX CSRF handling](https://docs.djangoproject.com/en/5.2/howto/csrf/) and [chunked file upload handling](https://docs.djangoproject.com/en/5.2/topics/http/file-uploads/).
