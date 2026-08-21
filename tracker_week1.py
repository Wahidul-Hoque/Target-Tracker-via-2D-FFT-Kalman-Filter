"""
=============================================================================
Target Tracker via 2D FFT & Kalman Filter
CSE 220 — BUET | Week 1 Deliverable: UI Shell & Video Ingestion Engine
=============================================================================
Authors : Wahidul Haque (2305054) & Abu Bakar Siddique (2305059)
Week    : 1 / 7
Purpose : Complete GUI shell with live video playback, control panel,
          real-time metric labels, and DSP diagnostic placeholder strip.
          NO tracking algorithms are implemented yet.

Dependencies:
    pip install customtkinter imageio[ffmpeg] matplotlib pillow
=============================================================================
"""

import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import imageio.v3 as iio
import matplotlib
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageTk

matplotlib.use("TkAgg")


# ─────────────────────────────────────────────────────────────────────────────
# Theme / palette — DSP instrument aesthetic: dark backgrounds, cyan accent,
# amber warnings, tight monospace numerics to evoke an oscilloscope dashboard.
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = {
    "bg_dark":    "#0D1117",   # near-black frame background
    "bg_panel":   "#161B22",   # sidebar / strip background
    "bg_card":    "#21262D",   # metric card surface
    "accent_cyan":"#39D0D8",   # primary accent — tracking active
    "accent_amber":"#F0A500",  # secondary accent — warnings / occlusion
    "accent_red": "#FF5555",   # error / lost state
    "text_primary":"#E6EDF3",  # main readable text
    "text_muted":  "#8B949E",  # de-emphasised labels
    "border":      "#30363D",  # subtle dividers
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Target playback interval in milliseconds (≈30 FPS ceiling).
PLAYBACK_MS = 33


# ─────────────────────────────────────────────────────────────────────────────
# VideoReader — thin wrapper around imageio that yields RGB uint8 frames.
# ─────────────────────────────────────────────────────────────────────────────
class VideoReader:
    """Reads an .mp4 or .avi file frame-by-frame using imageio (no OpenCV)."""

    def __init__(self, path: str):
        self._path = path
        self._props = iio.improps(path, plugin="pyav")
        # Total frame count (may be -1 for some containers — handled gracefully)
        self.total_frames: int = self._props.n_images if self._props.n_images > 0 else 0
        self.fps: float = float(self._props.fps) if hasattr(self._props, "fps") else 30.0
        self._frame_iter = None
        self.current_index: int = 0

    # ------------------------------------------------------------------
    def open(self):
        """Open (or reopen) the frame iterator from the beginning."""
        self._frame_iter = iio.imiter(self._path, plugin="pyav")
        self.current_index = 0

    def next_frame(self) -> np.ndarray | None:
        """Return the next RGB frame as a NumPy uint8 array, or None at EOF."""
        if self._frame_iter is None:
            return None
        try:
            frame = next(self._frame_iter)
            self.current_index += 1
            # imageio may return (H, W) grayscale — promote to RGB
            if frame.ndim == 2:
                frame = np.stack([frame] * 3, axis=-1)
            # Drop alpha channel if present
            if frame.shape[2] == 4:
                frame = frame[:, :, :3]
            return frame
        except StopIteration:
            return None

    def close(self):
        """Release iterator resources."""
        self._frame_iter = None


# ─────────────────────────────────────────────────────────────────────────────
# DSPDiagnosticStrip — four-panel Matplotlib figure embedded in Tkinter.
# ─────────────────────────────────────────────────────────────────────────────
class DSPDiagnosticStrip(ctk.CTkFrame):
    """
    Bottom strip with four placeholder Matplotlib axes:
      1. Target Crop  2. 2D Hann Window  3. 2D FFT Spectrum  4. Correlation Peak
    In Week 1 all panels display placeholder noise / text only.
    """

    PANEL_TITLES = [
        "1. Target Crop",
        "2. 2D Hann Window",
        "3. 2D FFT Spectrum",
        "4. Correlation Peak",
    ]

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=PALETTE["bg_panel"], **kwargs)

        # Section header
        header = ctk.CTkLabel(
            self,
            text="REAL-TIME DSP DIAGNOSTIC STRIP",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=PALETTE["text_muted"],
        )
        header.pack(pady=(6, 2), padx=12, anchor="w")

        # Matplotlib figure — background matches app palette
        self._fig = Figure(
            figsize=(12, 1.85),
            dpi=95,
            facecolor=PALETTE["bg_panel"],
        )
        self._fig.subplots_adjust(left=0.02, right=0.98, top=0.82, bottom=0.05, wspace=0.18)

        self._axes = []
        for i, title in enumerate(self.PANEL_TITLES):
            ax = self._fig.add_subplot(1, 4, i + 1)
            ax.set_facecolor(PALETTE["bg_card"])
            ax.set_title(title, color=PALETTE["text_muted"], fontsize=8, pad=4)
            ax.tick_params(colors=PALETTE["border"], labelsize=6)
            for spine in ax.spines.values():
                spine.set_edgecolor(PALETTE["border"])
            ax.set_xticks([])
            ax.set_yticks([])
            # Placeholder: subtle noise texture
            placeholder = np.random.rand(32, 32) * 0.15
            ax.imshow(placeholder, cmap="plasma", aspect="auto", vmin=0, vmax=1)
            ax.text(
                0.5, 0.5, "–",
                transform=ax.transAxes,
                ha="center", va="center",
                color=PALETTE["text_muted"],
                fontsize=20,
                alpha=0.4,
            )
            self._axes.append(ax)

        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().pack(fill="x", padx=8, pady=(0, 6))
        self._canvas.draw()

    # ------------------------------------------------------------------
    def refresh(self):
        """Redraw all axes (called by tracker each frame in later weeks)."""
        self._canvas.draw_idle()


# ─────────────────────────────────────────────────────────────────────────────
# MetricCard — a labelled value display (Status, Confidence, etc.)
# ─────────────────────────────────────────────────────────────────────────────
class MetricCard(ctk.CTkFrame):
    """A compact card with a muted label on top and a bold value below."""

    def __init__(self, master, label: str, initial_value: str, value_color: str = PALETTE["text_primary"], **kwargs):
        super().__init__(
            master,
            fg_color=PALETTE["bg_card"],
            corner_radius=8,
            border_width=1,
            border_color=PALETTE["border"],
            **kwargs,
        )
        ctk.CTkLabel(
            self,
            text=label.upper(),
            font=ctk.CTkFont(family="Courier New", size=9),
            text_color=PALETTE["text_muted"],
        ).pack(anchor="w", padx=10, pady=(8, 0))

        self._value_label = ctk.CTkLabel(
            self,
            text=initial_value,
            font=ctk.CTkFont(family="Courier New", size=14, weight="bold"),
            text_color=value_color,
        )
        self._value_label.pack(anchor="w", padx=10, pady=(2, 8))

    def set_value(self, text: str, color: str | None = None):
        self._value_label.configure(text=text)
        if color:
            self._value_label.configure(text_color=color)


# ─────────────────────────────────────────────────────────────────────────────
# TrackerApp — main application window
# ─────────────────────────────────────────────────────────────────────────────
class TrackerApp(ctk.CTk):
    """
    Main window composed of three regions matching Figure 1 of the proposal:
      • Main Video Canvas  (center-left)
      • Control & Metrics Sidebar  (right)
      • DSP Diagnostic Strip  (bottom)
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()

        self.title("Target Tracker — 2D FFT & Kalman Filter  |  CSE 220 · BUET")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=PALETTE["bg_dark"])

        # ── State variables ──────────────────────────────────────────
        self._video: VideoReader | None = None
        self._is_playing: bool = False
        self._playback_job = None          # Tkinter `after()` handle
        self._current_photo = None         # Prevent GC of PhotoImage
        self._frame_times: list[float] = []  # Rolling buffer for FPS calc
        self._lock = threading.Lock()

        # ── Build layout ─────────────────────────────────────────────
        self._build_layout()

    # ------------------------------------------------------------------
    def _build_layout(self):
        """Assemble the three-region layout."""

        # ── Outer column split: [video + strip] | [sidebar] ─────────
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # ── 1. Main video canvas ─────────────────────────────────────
        self._video_frame = ctk.CTkFrame(
            self,
            fg_color=PALETTE["bg_panel"],
            corner_radius=10,
            border_width=1,
            border_color=PALETTE["border"],
        )
        self._video_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=(12, 6))

        # Header bar inside video frame
        vf_header = ctk.CTkFrame(self._video_frame, fg_color="transparent")
        vf_header.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            vf_header,
            text="MAIN VIDEO STREAM OVERLAY",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=PALETTE["text_muted"],
        ).pack(side="left")

        # Legend
        legend_frame = ctk.CTkFrame(vf_header, fg_color="transparent")
        legend_frame.pack(side="right")
        for color, desc in [
            ("#44FF88", "FFT Measurement"),
            ("#FF5555", "Kalman Output"),
            ("#5599FF", "Trajectory Tail"),
        ]:
            dot = ctk.CTkLabel(legend_frame, text="■", text_color=color,
                               font=ctk.CTkFont(size=11))
            dot.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(legend_frame, text=desc, text_color=PALETTE["text_muted"],
                         font=ctk.CTkFont(size=10)).pack(side="left", padx=(1, 6))

        # Actual Tk Canvas for frame rendering
        self._canvas = tk.Canvas(
            self._video_frame,
            bg=PALETTE["bg_dark"],
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # "Drop a video" placeholder text
        self._canvas_placeholder = self._canvas.create_text(
            400, 280,
            text="📂  Load a video file to begin",
            fill=PALETTE["text_muted"],
            font=("Courier New", 16),
            anchor="center",
        )

        # ── 2. Sidebar ───────────────────────────────────────────────
        sidebar = ctk.CTkFrame(
            self,
            fg_color=PALETTE["bg_panel"],
            corner_radius=10,
            border_width=1,
            border_color=PALETTE["border"],
            width=240,
        )
        sidebar.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=(12, 6))
        sidebar.grid_propagate(False)

        self._build_sidebar(sidebar)

        # ── 3. DSP Diagnostic Strip (spans full width) ───────────────
        self._dsp_strip = DSPDiagnosticStrip(self)
        self._dsp_strip.grid(row=1, column=0, columnspan=2, sticky="ew",
                             padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    def _build_sidebar(self, parent):
        """Populate the control panel and metrics sidebar."""

        # Title
        ctk.CTkLabel(
            parent,
            text="CONTROL PANEL",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=PALETTE["text_muted"],
        ).pack(pady=(14, 8), padx=14, anchor="w")

        # ── Buttons ───────────────────────────────────────────────────
        btn_cfg = dict(
            corner_radius=6,
            height=36,
            font=ctk.CTkFont(family="Courier New", size=12, weight="bold"),
        )

        ctk.CTkButton(
            parent,
            text="📂  Load Video File",
            command=self._on_load_video,
            fg_color=PALETTE["accent_cyan"],
            hover_color="#2BB8BF",
            text_color=PALETTE["bg_dark"],
            **btn_cfg,
        ).pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkButton(
            parent,
            text="🎯  Select Target (ROI)",
            command=self._on_select_roi,
            fg_color=PALETTE["bg_card"],
            hover_color=PALETTE["border"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text_muted"],
            state="disabled",
            **btn_cfg,
        ).pack(fill="x", padx=14, pady=(0, 6))
        # Keep reference so we can enable later
        self._btn_roi = parent.winfo_children()[-1]

        self._btn_play = ctk.CTkButton(
            parent,
            text="▶  Play",
            command=self._on_play_pause,
            fg_color=PALETTE["bg_card"],
            hover_color=PALETTE["border"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text_muted"],
            state="disabled",
            **btn_cfg,
        )
        self._btn_play.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkButton(
            parent,
            text="↺  Reset Tracker",
            command=self._on_reset,
            fg_color=PALETTE["bg_card"],
            hover_color=PALETTE["border"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text_muted"],
            **btn_cfg,
        ).pack(fill="x", padx=14, pady=(0, 6))
        self._btn_reset = parent.winfo_children()[-1]

        # Divider
        ctk.CTkFrame(parent, height=1, fg_color=PALETTE["border"]).pack(
            fill="x", padx=14, pady=12
        )

        # ── Metrics ───────────────────────────────────────────────────
        ctk.CTkLabel(
            parent,
            text="REAL-TIME METRICS",
            font=ctk.CTkFont(family="Courier New", size=11, weight="bold"),
            text_color=PALETTE["text_muted"],
        ).pack(pady=(0, 8), padx=14, anchor="w")

        self._metric_status = MetricCard(
            parent, "Status", "READY", value_color=PALETTE["accent_cyan"]
        )
        self._metric_status.pack(fill="x", padx=14, pady=(0, 6))

        self._metric_conf = MetricCard(parent, "Confidence", "0.0 %")
        self._metric_conf.pack(fill="x", padx=14, pady=(0, 6))

        self._metric_pos = MetricCard(parent, "Position", "X: –   Y: –")
        self._metric_pos.pack(fill="x", padx=14, pady=(0, 6))

        self._metric_fps = MetricCard(parent, "Frame Rate", "0 FPS")
        self._metric_fps.pack(fill="x", padx=14, pady=(0, 6))

        self._metric_frame = MetricCard(parent, "Frame", "0 / –")
        self._metric_frame.pack(fill="x", padx=14, pady=(0, 6))

        # Spacer
        ctk.CTkFrame(parent, fg_color="transparent").pack(fill="both", expand=True)

        # Footer
        ctk.CTkLabel(
            parent,
            text="Week 1 — UI Shell  |  CSE 220",
            font=ctk.CTkFont(family="Courier New", size=9),
            text_color=PALETTE["border"],
        ).pack(pady=10)

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def _on_load_video(self):
        """Open file dialog, load video, and prepare for playback."""
        path = filedialog.askopenfilename(
            title="Select a video file",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv"), ("All files", "*.*")],
        )
        if not path:
            return

        # Stop any running playback
        self._stop_playback()

        try:
            reader = VideoReader(path)
            reader.open()
        except Exception as exc:
            messagebox.showerror("Video Load Error", f"Could not open video:\n{exc}")
            return

        self._video = reader

        # Update UI state
        total = self._video.total_frames if self._video.total_frames else "?"
        self._metric_frame.set_value(f"0 / {total}")
        self._metric_fps.set_value(f"{self._video.fps:.1f} FPS  (src)")
        self._metric_status.set_value("LOADED", color=PALETTE["accent_amber"])
        self._btn_play.configure(state="normal", text_color=PALETTE["text_primary"])
        self._btn_roi.configure(state="normal", text_color=PALETTE["text_primary"])
        self._btn_reset.configure(text_color=PALETTE["text_primary"])

        # Show first frame as preview
        frame = self._video.next_frame()
        if frame is not None:
            self._render_frame(frame)

    # ------------------------------------------------------------------
    def _on_play_pause(self):
        """Toggle playback state."""
        if self._video is None:
            return
        if self._is_playing:
            self._stop_playback()
            self._btn_play.configure(text="▶  Play")
            self._metric_status.set_value("PAUSED", color=PALETTE["accent_amber"])
        else:
            self._is_playing = True
            self._btn_play.configure(text="⏸  Pause")
            self._metric_status.set_value("PLAYING", color=PALETTE["accent_cyan"])
            self._frame_times.clear()
            self._schedule_next_frame()

    # ------------------------------------------------------------------
    def _on_select_roi(self):
        """Placeholder — ROI selection will be wired in Week 2."""
        messagebox.showinfo(
            "Coming in Week 2",
            "ROI selection (target bounding box) will be implemented\n"
            "in Week 2 once the 2D FFT phase-correlation engine is ready.",
        )

    # ------------------------------------------------------------------
    def _on_reset(self):
        """Stop playback, rewind video, clear metrics."""
        self._stop_playback()
        if self._video is not None:
            self._video.close()
            self._video.open()
            # Show first frame again
            frame = self._video.next_frame()
            if frame is not None:
                self._render_frame(frame)
        self._metric_status.set_value("READY", color=PALETTE["accent_cyan"])
        self._metric_conf.set_value("0.0 %")
        self._metric_pos.set_value("X: –   Y: –")
        self._metric_fps.set_value("0 FPS")
        total = self._video.total_frames if self._video else "?"
        self._metric_frame.set_value(f"0 / {total}")
        self._btn_play.configure(text="▶  Play")

    # ------------------------------------------------------------------
    # Playback loop (Tkinter after() — no blocking, no extra threads)
    # ------------------------------------------------------------------

    def _schedule_next_frame(self):
        """Schedule the next frame render via Tkinter's event loop."""
        if not self._is_playing or self._video is None:
            return
        self._playback_job = self.after(PLAYBACK_MS, self._step_frame)

    def _step_frame(self):
        """Pull one frame from the reader, render it, update metrics."""
        frame = self._video.next_frame()
        if frame is None:
            # EOF — stop and rewind
            self._stop_playback()
            self._metric_status.set_value("ENDED", color=PALETTE["text_muted"])
            self._btn_play.configure(text="▶  Play")
            return

        t_now = time.perf_counter()
        self._frame_times.append(t_now)
        # Keep a 30-frame rolling window for FPS
        if len(self._frame_times) > 30:
            self._frame_times.pop(0)

        self._render_frame(frame)
        self._update_metrics()
        self._schedule_next_frame()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_frame(self, frame: np.ndarray):
        """Convert a NumPy RGB array to a PhotoImage and paint it on the canvas."""
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        h, w = frame.shape[:2]
        # Maintain aspect ratio
        scale = min(cw / w, ch / h)
        nw, nh = int(w * scale), int(h * scale)

        pil_img = Image.fromarray(frame, mode="RGB").resize((nw, nh), Image.BILINEAR)
        photo = ImageTk.PhotoImage(pil_img)

        # Position centered
        x_off = (cw - nw) // 2
        y_off = (ch - nh) // 2

        self._canvas.delete("frame_img")
        self._canvas.itemconfigure(self._canvas_placeholder, state="hidden")
        self._canvas.create_image(x_off, y_off, anchor="nw", image=photo, tags="frame_img")
        self._current_photo = photo  # prevent garbage collection

    def _on_canvas_resize(self, event):
        """Re-render current frame to fill new canvas size."""
        # Nothing to do in Week 1 unless we cache last frame; handled gracefully.
        pass

    # ------------------------------------------------------------------
    def _update_metrics(self):
        """Refresh metric cards from current playback state."""
        if self._video is None:
            return

        # FPS
        if len(self._frame_times) >= 2:
            elapsed = self._frame_times[-1] - self._frame_times[0]
            fps = (len(self._frame_times) - 1) / elapsed if elapsed > 0 else 0
            self._metric_fps.set_value(f"{fps:.1f} FPS")

        # Frame counter
        total = self._video.total_frames if self._video.total_frames else "?"
        self._metric_frame.set_value(f"{self._video.current_index} / {total}")

    # ------------------------------------------------------------------
    def _stop_playback(self):
        """Cancel any scheduled after() callback and mark as stopped."""
        self._is_playing = False
        if self._playback_job is not None:
            self.after_cancel(self._playback_job)
            self._playback_job = None

    # ------------------------------------------------------------------
    def on_close(self):
        """Clean up before the window closes."""
        self._stop_playback()
        if self._video is not None:
            self._video.close()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = TrackerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()