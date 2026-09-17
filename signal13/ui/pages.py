"""Separate Studio, DSP Lab and Analytics page components."""
import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from .theme import BG, PANEL, CARD, TEXT, MUTED, ACCENT, GREEN, RED, BLUE
from .video_canvas import VideoCanvas


class StudioPage(ttk.Frame):
    def __init__(self, parent, on_roi, callbacks):
        super().__init__(parent, padding=(0, 18, 0, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text='Tracking Studio', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 14))
        ttk.Label(self, text='01 / LOCALIZE + PREDICT', style='Muted.TLabel').grid(row=0, column=1, sticky='e')
        self.video = VideoCanvas(self, on_roi)
        self.video.grid(row=1, column=0, sticky='nsew', padx=(0, 18))
        sidebar = ttk.Frame(self, style='Card.TFrame', padding=18, width=260)
        sidebar.grid(row=1, column=1, sticky='ns')
        self.buttons = {}
        controls = ttk.Frame(sidebar, style='Card.TFrame')
        controls.pack(fill='x')
        controls.columnconfigure((0, 1), weight=1)
        for i, (key, label) in enumerate([('open', 'Open video'), ('demo', 'Demo'), ('roi', 'Select target'), ('reset', 'Restart'), ('play', 'Play'), ('step', 'Step frame')]):
            button = ttk.Button(controls, text=label, width=11, command=callbacks[key], style='Accent.TButton' if key == 'demo' else 'TButton')
            button.grid(row=i//2, column=i%2, sticky='ew', padx=(0, 5) if i%2 == 0 else (5, 0), pady=(0, 7))
            self.buttons[key] = button
        self.metrics = {}
        for key, label in [('status', 'TRACKER STATE'), ('psr', 'PEAK-TO-SIDELOBE RATIO'), ('position', 'POSITION / PIXELS'), ('speed', 'SPEED / PX PER SECOND'), ('latency', 'DSP PROCESSING')]:
            ttk.Label(sidebar, text=label, style='Card.TLabel', foreground=MUTED, font=('Helvetica', 8)).pack(anchor='w', pady=(8, 0))
            value = ttk.Label(sidebar, text='-', style='Metric.TLabel')
            value.pack(anchor='w')
            self.metrics[key] = value
        legend = ttk.Frame(self)
        legend.grid(row=2, column=0, sticky='ew', pady=12)
        for color, label in [(GREEN, 'FFT measurement'), (RED, 'Kalman output'), (BLUE, 'Trajectory'), (MUTED, 'Search window (dashed)')]:
            ttk.Label(legend, text='■  '+label, foreground=color).pack(side='left', padx=(0, 24))
        self.frame_label = ttk.Label(self, text='No source loaded', style='Muted.TLabel')
        self.frame_label.grid(row=2, column=1, sticky='e')


class DSPPage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(0, 18, 0, 0))
        ttk.Label(self, text='DSP Lab', style='Title.TLabel').pack(anchor='w')
        ttk.Label(self, text='Inspect the actual arrays driving your tracker. Plots refresh at most 5 times per second.', style='Muted.TLabel').pack(anchor='w', pady=(4, 0))
        # Plots can be several frames older than the video view, so say which frame they show.
        self.caption = ttk.Label(self, text='', foreground=ACCENT)
        self.caption.pack(anchor='w', pady=(2, 12))
        self.figure = Figure(figsize=(9, 5), dpi=100, facecolor=BG)
        self.figure.subplots_adjust(left=.06, right=.97, bottom=.07, top=.93, hspace=.32, wspace=.18)
        self.artists = {}
        for i, title in enumerate(['Target crop', 'Windowed search', 'Log FFT magnitude', 'Correlation surface']):
            ax = self.figure.add_subplot(2, 2, i+1)
            ax.set_facecolor(PANEL)
            ax.set_title(title, color=TEXT, fontsize=11, loc='left', pad=9)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color(CARD)
            if title == 'Correlation surface':
                ax.set_title('Correlation surface / centered peak', color=TEXT, fontsize=11, loc='left', pad=9)
                self.peak_marker = ax.plot([], [], '+', color=ACCENT, markersize=12, markeredgewidth=1.3)[0]
            self.artists[title] = ax.imshow(np.zeros((16, 16)), cmap='gray' if i < 2 else 'magma', origin='upper')
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        footer = ttk.Frame(self)
        footer.pack(side='bottom', before=self.canvas.get_tk_widget(), fill='x')
        ttk.Label(footer, text='FFT(search) x conjugate(FFT(template)) -> normalize magnitude -> inverse FFT -> peak -> Kalman update', foreground=ACCENT).pack(anchor='w', pady=(10, 5))
        ttk.Label(footer, text='Correlation display is centered; detection uses wrapped coordinates. PSR is a score, not a probability. Low appearance agreement rejects misleading peaks.', style='Muted.TLabel', wraplength=1000).pack(anchor='w')

    def refresh(self, diagnostics, frame=None):
        self.caption.configure(text=f'Showing source frame {frame}' if frame else 'Paused snapshot of the last searched crop')
        for name, array in diagnostics.items():
            if name == 'Correlation surface':
                array = np.roll(array, (array.shape[0]//2, array.shape[1]//2), axis=(0, 1))
                row, col = np.unravel_index(np.argmax(array), array.shape)
                self.peak_marker.set_data([col+.5] if array.max() > 0 else [], [row+.5] if array.max() > 0 else [])
            artist = self.artists[name]
            artist.set_data(array)
            artist.set_extent((0, array.shape[1], array.shape[0], 0))
            artist.axes.set_xlim(0, array.shape[1])
            artist.axes.set_ylim(array.shape[0], 0)
            lo, hi = float(array.min()), float(array.max())
            artist.set_clim(lo, max(hi, lo+1e-9))
        self.canvas.draw_idle()

    def clear(self):
        self.refresh({key: np.zeros((16, 16)) for key in self.artists})
        self.caption.configure(text='')


class AnalyticsPage(ttk.Frame):
    def __init__(self, parent, export):
        super().__init__(parent, padding=(0, 18, 0, 0))
        header = ttk.Frame(self)
        header.pack(fill='x')
        ttk.Label(header, text='Session Analytics', style='Title.TLabel').pack(side='left')
        ttk.Button(header, text='Export session CSV', command=export).pack(side='right')
        self.summary = ttk.Label(self, text='Select a target to start recording.', style='Muted.TLabel')
        self.summary.pack(anchor='w', pady=12)
        self.figure = Figure(figsize=(9, 5), facecolor=BG)
        self.figure.subplots_adjust(left=.08, right=.97, bottom=.13, top=.91, hspace=.48)
        self.axes = [self.figure.add_subplot(2, 1, i+1) for i in range(2)]
        self.lines = []
        for ax, title, color in zip(self.axes, ['Tracking confidence / PSR', 'Core processing time / ms'], [ACCENT, BLUE]):
            ax.set_facecolor(PANEL)
            ax.set_title(title, color=TEXT, loc='left', fontsize=11)
            ax.tick_params(colors=MUTED, labelsize=9)
            ax.grid(alpha=.12, color=MUTED)
            for spine in ax.spines.values():
                spine.set_color(CARD)
            self.lines.append(ax.plot([], [], color=color, linewidth=1.6)[0])
        self.axes[-1].set_xlabel('Source frame', color=MUTED)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        ttk.Label(self, text='Plots show the latest 600 tracked frames. CSV includes every recorded frame in this session. A new target starts a new session.', style='Muted.TLabel').pack(side='bottom', before=self.canvas.get_tk_widget(), anchor='w', pady=8)

    def refresh(self, rows, total, accepted):
        self.summary.configure(text=f'{total:,} frames recorded   |   {accepted:,} accepted measurements   |   {total-accepted:,} prediction-only frames')
        x = [r['frame'] for r in rows]
        for line, ax, key in zip(self.lines, self.axes, ['psr', 'processing_ms']):
            line.set_data(x, [r[key] for r in rows])
            ax.relim()
            ax.autoscale_view()
        self.canvas.draw_idle()
