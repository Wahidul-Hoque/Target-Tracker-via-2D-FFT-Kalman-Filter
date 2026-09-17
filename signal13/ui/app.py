"""Tk controller. A single in-flight future keeps processing serial and bounded.

All widgets, Matplotlib and ImageTk objects live on the main thread. Video I/O
and DSP live on one worker. Pause lets the current frame finish; mutating source
controls are disabled until it does. Timing uses source FPS, never GUI jitter.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .theme import apply_theme, ACCENT, AMBER, MUTED
from .pages import StudioPage, DSPPage, AnalyticsPage
from .worker import ProcessingEngine
from ..io.session import SessionLog


class TrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Signal13 | FFT + Kalman Tracking Studio')
        self.geometry('1280x850')
        self.minsize(1050, 760)
        apply_theme(self)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='signal13-dsp')
        self.engine = ProcessingEngine()
        self.future = self.pending = None
        self.playing = self.loaded = self.ready = self.ended = self.closing = False
        self.path = None
        self.fps = 30.
        self.total = None
        self.last_plots = 0.
        self.deadline = 0.
        self.last_index = 0
        self.result = None
        self.frame_times = deque(maxlen=30)
        self.log = SessionLog()
        shell = ttk.Frame(self, padding=24)
        shell.pack(fill='both', expand=True)
        top = ttk.Frame(shell)
        top.pack(fill='x', pady=(0, 18))
        ttk.Label(top, text='S / 13', foreground=ACCENT, font=('Courier', 23, 'bold')).pack(side='left')
        ttk.Label(top, text='  SIGNAL13     /     FOURIER MOTION WORKBENCH', style='Muted.TLabel').pack(side='left')
        ttk.Label(top, text='CSE 220  /  BUET', style='Muted.TLabel').pack(side='right')
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill='both', expand=True)
        callbacks = dict(open=self.open_video, demo=lambda: self.load(None), roi=self.select_roi,
                         play=self.toggle_play, step=self.single_step, reset=self.restart)
        self.studio = StudioPage(self.tabs, self.apply_roi, callbacks)
        self.dsp = DSPPage(self.tabs)
        self.analytics = AnalyticsPage(self.tabs, self.export)
        for page, title in [(self.studio, '01   Tracking Studio'), (self.dsp, '02   DSP Lab'), (self.analytics, '03   Session Analytics')]:
            self.tabs.add(page, text=title)
        self.tabs.bind('<<NotebookTabChanged>>', self.refresh_page)
        self.notice = ttk.Label(shell, text='Start with the built-in demo, or load a video and drag a target box.', style='Muted.TLabel')
        self.notice.pack(side='bottom', before=self.tabs, fill='x', pady=(12, 0))
        self.bind('<space>', lambda e: self.toggle_play())
        self.bind('<Escape>', lambda e: self.cancel_selection())
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.update_controls()
        self.after(15, self.poll)

    def submit(self, function, callback, *args):
        if self.future is not None or self.closing:
            return
        self.callback = callback
        self.future = self.pool.submit(function, *args)
        self.update_controls()

    def when_idle(self, action):
        """If a frame is in flight, pause and run action once it finishes. True if deferred."""
        if self.future is None:
            return False
        self.playing = False
        self.pending = action
        self.notice.configure(text='Finishing the current frame...')
        self.update_controls()
        return True

    def update_controls(self):
        # During playback a frame is in flight most of the time; keeping these enabled
        # (clicks are deferred by when_idle) stops them flickering on every frame.
        idle = (self.future is None or self.playing) and self.pending is None
        for key in ('open', 'demo', 'reset', 'roi', 'step'):
            enabled = idle and (key in ('open', 'demo') or self.loaded)
            if key == 'step':
                enabled = self.future is None and self.loaded and not self.playing and not self.ended
            self.studio.buttons[key].configure(state='normal' if enabled else 'disabled')
        self.studio.buttons['play'].configure(text='Pause' if self.playing else 'Play', state='normal' if self.loaded and not self.ended else 'disabled')

    def new_session(self):
        self.log.close()
        self.log = SessionLog()
        self.result = None
        self.frame_times.clear()
        self.dsp.clear()
        self.analytics.refresh([], 0, 0)
        for metric in self.studio.metrics.values():
            metric.configure(text='-')

    def open_video(self):
        if self.when_idle(self.open_video):
            return
        self.playing = False
        self.update_controls()
        path = filedialog.askopenfilename(title='Open a video', filetypes=[('Video', '*.mp4 *.avi *.mov *.mkv *.webm'), ('All files', '*.*')])
        if path:
            self.load(path)

    def load(self, path):
        if self.when_idle(lambda: self.load(path)):
            return
        self.playing = False
        self.studio.video.cancel()
        self.notice.configure(text='Opening source...')
        def complete(data):
            self.path = path
            frame, name, self.fps, self.total, self.ready = data
            self.last_index = 0
            self.loaded, self.ended = True, False
            self.new_session()
            self.studio.video.show(frame)
            self.studio.metrics['status'].configure(text='READY' if self.ready else 'SELECT ROI')
            self.studio.frame_label.configure(text=f'Frame 1 / {self.total or "?"} | {self.fps:g} fps source')
            self.notice.configure(text=(f'{Path(name).name}  |  Press Play to begin.' if self.ready else f'{Path(name).name}  |  Select target, then drag a tight rectangle.'))
            if self.engine.fps_warning:
                messagebox.showwarning('Frame rate', self.engine.fps_warning + ' Tracking speed and Kalman tuning assume this value.')
            self.tabs.select(self.studio)
        self.submit(self.engine.load, complete, path)

    def restart(self):
        if self.loaded:
            self.load(self.path)

    def select_roi(self):
        if not self.loaded or self.when_idle(self.select_roi):
            return
        self.playing = False
        self.tabs.select(self.studio)
        self.studio.video.arm()
        self.notice.configure(text='Drag around a textured target. Keep each side between 8 and 170 pixels. Escape cancels.')
        self.update_controls()

    def cancel_selection(self):
        self.studio.video.cancel()
        self.notice.configure(text='Selection cancelled.')

    def apply_roi(self, bbox):
        def complete(_):
            self.ready = True
            self.new_session()
            self.studio.metrics['status'].configure(text='READY')
            self.studio.video.show(self.studio.video.frame)
            self.studio.video.box((bbox[0]+bbox[2]/2, bbox[1]+bbox[3]/2), bbox[2:], ACCENT, 2)
            self.notice.configure(text='Target initialized. Press Play or Step one frame.')
        self.submit(self.engine.select, complete, bbox)

    def toggle_play(self):
        if not self.loaded or self.ended or self.closing:
            return
        self.studio.video.cancel()
        self.playing = not self.playing
        self.frame_times.clear()
        self.deadline = time.perf_counter()
        self.notice.configure(text='Playing - Space to pause.' if self.playing else 'Paused. Any in-flight frame will finish.')
        self.update_controls()

    def single_step(self):
        if self.loaded and not self.playing and not self.ended and self.future is None:
            self.studio.video.cancel()
            self.request_frame()

    def request_frame(self):
        now = time.perf_counter()
        visible_dsp = self.tabs.index(self.tabs.select()) == 1
        diagnostics = visible_dsp and now-self.last_plots >= .2
        self.deadline = now+1/self.fps
        if diagnostics:
            self.last_plots = now
        self.submit(self.engine.step, self.frame_completed, diagnostics)

    def frame_completed(self, data):
        if data is None:
            self.playing, self.ended = False, True
            self.notice.configure(text='End of video. Export your session or restart the source.')
            return
        frame, self.result, index = data
        if self.playing and index-self.last_index > 1:
            self.deadline += (index-self.last_index-1)/self.fps  # skipped repeats still take screen time
        self.last_index = index
        self.studio.video.show(frame, self.result)
        self.frame_times.append(time.perf_counter())
        self.studio.frame_label.configure(text=f'Frame {index+1} / {self.total or "?"} | {self.fps:g} fps source')
        if self.playing and len(self.frame_times) > 1:
            actual_fps = (len(self.frame_times)-1)/(self.frame_times[-1]-self.frame_times[0])
            self.studio.frame_label.configure(text=f'Frame {index+1} | {actual_fps:.1f} fps actual')
        if self.result:
            r = self.result
            self.log.append(index, index/self.fps, r)
            values = dict(status=r.status, psr=f'{r.psr:.1f}', position=f'{r.center[0]:.1f}, {r.center[1]:.1f}',
                          speed=f'{(r.velocity[0]**2+r.velocity[1]**2)**.5:.1f}', latency=f'{r.processing_ms:.1f} ms')
            for key, value in values.items():
                self.studio.metrics[key].configure(text=value)
            self.studio.metrics['status'].configure(foreground=ACCENT if r.status == 'TRACKING' else AMBER)
            if r.diagnostics:
                self.dsp.refresh(r.diagnostics, index+1)
            if self.tabs.index(self.tabs.select()) == 2 and time.perf_counter()-self.last_plots > .2:
                self.last_plots = time.perf_counter()
                self.analytics.refresh(self.log.rows, self.log.total, self.log.accepted)

    def refresh_page(self, event=None):
        if not hasattr(self, 'analytics'):
            return
        page = self.tabs.index(self.tabs.select())
        if page == 2:
            self.analytics.refresh(self.log.rows, self.log.total, self.log.accepted)
        elif page == 1:
            self.notice.configure(text='DSP arrays refresh during playback. Space plays or pauses; the paused view is a read-only snapshot.')
            # Request a read-only snapshot on the worker without advancing state.
            if self.ready and self.future is None:
                self.submit(self.engine.snapshot, self.dsp.refresh)

    def export(self):
        if not self.log.total:
            messagebox.showinfo('No session', 'Track a target before exporting.')
            return
        self.playing = False
        self.update_controls()
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='signal13_session.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                self.log.export(path)
                self.notice.configure(text=f'Exported {self.log.total:,} frames to {Path(path).name}.')
            except OSError as exc:
                messagebox.showerror('Export failed', str(exc))

    def poll(self):
        if self.future is not None and self.future.done():
            future, callback = self.future, self.callback
            self.future = None
            try:
                data = future.result()
                if not self.closing:
                    callback(data)
            except Exception as exc:
                self.playing = False
                if not self.closing:
                    self.notice.configure(text='Operation failed. Review the error and try again.')
                    messagebox.showerror('Signal13', str(exc))
            self.update_controls()
        if self.pending is not None and self.future is None and not self.closing:
            action, self.pending = self.pending, None
            action()
            self.update_controls()
        if self.closing:
            if self.future is None:
                self.pool.shutdown(wait=False)
                self.engine.close()
                self.log.close()
                self.destroy()
                return
        elif self.playing and self.future is None and time.perf_counter() >= self.deadline:
            self.request_frame()
        self.after(10, self.poll)

    def on_close(self):
        self.playing = False
        self.closing = True
        self.notice.configure(text='Closing after the current operation finishes...')
