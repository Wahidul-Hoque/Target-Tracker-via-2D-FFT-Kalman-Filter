"""Aspect-correct canvas, native-coordinate ROI selection and overlays."""
import tkinter as tk
from PIL import Image, ImageTk
from .theme import BG, MUTED, ACCENT, GREEN, RED, BLUE


class VideoCanvas(tk.Canvas):
    def __init__(self, parent, on_roi):
        super().__init__(parent, bg=BG, highlightthickness=0, cursor='arrow')
        self.on_roi = on_roi
        self.frame = self.result = self.photo = None
        self.selecting = False
        self.start = None
        self.transform = (1., 0., 0.)
        self.bind('<Configure>', lambda e: self.render())
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', self._release)

    def show(self, frame, result=None):
        self.frame, self.result = frame, result
        self.render()

    def render(self):
        self.delete('all')
        cw, ch = self.winfo_width(), self.winfo_height()
        if self.frame is None:
            self.create_text(cw/2, ch/2-25, text='Follow the signal.', fill=ACCENT, font=('Helvetica', 26, 'bold'))
            self.create_text(cw/2, ch/2+20, text='Open a video or start the built-in demo', fill=MUTED, font=('Helvetica', 12))
            return
        h, w = self.frame.shape[:2]
        scale = min(max(cw, 2)/w, max(ch, 2)/h)
        nw, nh = max(1, int(w*scale)), max(1, int(h*scale))
        xo, yo = (cw-nw)/2, (ch-nh)/2
        # Use independent exact display scales to avoid integer resize drift.
        self.transform = (nw/w, nh/h, xo, yo)
        self.photo = ImageTk.PhotoImage(Image.fromarray(self.frame).resize((nw, nh), Image.Resampling.BILINEAR))
        self.create_image(xo, yo, image=self.photo, anchor='nw')
        if self.result:
            r = self.result
            search_box = getattr(r, 'search_box', ())  # crop actually searched this frame
            if search_box:
                x, y, w, h = search_box
                self.create_rectangle(*self.to_canvas((x, y)), *self.to_canvas((x+w, y+h)), outline=MUTED, width=1, dash=(4, 4))
            points = [c for p in r.trajectory for c in self.to_canvas(p)]
            if len(points) >= 4:
                self.create_line(*points, fill=BLUE, width=2)
            if r.measurement:
                self.box(r.measurement, r.bbox_size, GREEN, 1)
            self.box(r.center, r.bbox_size, RED, 2)
            px, py = self.to_canvas(r.center)
            reason = getattr(r, 'reason', '')  # why a measurement was rejected, or 'reacquired'
            self.create_text(px, py-r.bbox_size[1]*self.transform[1]/2-14,
                             text=f'{r.status}  {reason}' if reason else r.status, fill=RED, font=('Courier', 10, 'bold'))
        self.create_text(xo+14, yo+14, text='SIGNAL13 / LIVE VIEW', fill=ACCENT, anchor='nw', font=('Courier', 10))

    def to_canvas(self, p):
        sx, sy, xo, yo = self.transform
        return p[0]*sx+xo, p[1]*sy+yo

    def to_image(self, x, y):
        sx, sy, xo, yo = self.transform
        h, w = self.frame.shape[:2]
        return max(0, min(w, (x-xo)/sx)), max(0, min(h, (y-yo)/sy))

    def box(self, center, size, color, width):
        x, y = center
        w, h = size
        self.create_rectangle(*self.to_canvas((x-w/2, y-h/2)), *self.to_canvas((x+w/2, y+h/2)), outline=color, width=width)

    def arm(self):
        self.selecting = True
        self.start = None
        self.configure(cursor='crosshair')

    def cancel(self):
        self.selecting = False
        self.start = None
        self.configure(cursor='arrow')
        self.delete('selection')

    def _press(self, event):
        if self.selecting and self.frame is not None:
            self.start = self.to_image(event.x, event.y)

    def _drag(self, event):
        if self.start is None:
            return
        self.delete('selection')
        end = self.to_image(event.x, event.y)
        self.create_rectangle(*self.to_canvas(self.start), *self.to_canvas(end), outline=ACCENT, width=2, dash=(5, 3), tags='selection')

    def _release(self, event):
        if self.start is None:
            return
        a, b = self.start, self.to_image(event.x, event.y)
        self.cancel()
        x, y = round(min(a[0], b[0])), round(min(a[1], b[1]))
        w, h = round(max(a[0], b[0]))-x, round(max(a[1], b[1]))-y
        self.on_roi((x, y, w, h))
