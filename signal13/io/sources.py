"""Lazy video ingestion and a deterministic, asset-free occlusion demo.

Phone videos are often variable-frame-rate. Left alone, FFmpeg resamples them to
a constant rate by repeating frames, and that rate can differ from the fps in the
metadata (a 40 fps-average clip came back at 60 fps with every third frame
repeated). So we ask for output at exactly the reported fps, skip exact repeats,
and report how many output frames each delivered frame covers (frame_step).
"""
import numpy as np

MAX_FORCED_FPS = 240.


def _same_image(a, b):
    """Exact repeat test; a sparse grid rejects different frames cheaply first."""
    return a.shape == b.shape and np.array_equal(a[::16, ::16], b[::16, ::16]) and np.array_equal(a, b)


class VideoSource:
    def __init__(self, path):
        import imageio.v2 as imageio
        probe = imageio.get_reader(path, format='FFMPEG')
        try:
            fps = float(probe.get_meta_data().get('fps', 30))
        finally:
            probe.close()
        if np.isfinite(fps) and 0 < fps <= MAX_FORCED_FPS:
            # Output at exactly the reported rate so that dt = frame_step / fps holds.
            self.reader = imageio.get_reader(path, format='FFMPEG', fps=fps)
        else:
            # Implausible metadata (e.g. "1k tbr"): take stored frames as they are; the
            # worker then warns and assumes a default rate.
            self.reader = imageio.get_reader(path, format='FFMPEG', output_params=['-vsync', 'passthrough'])
        try:
            self.fps = fps if np.isfinite(fps) and fps > 0 else 30.
            self.total = None  # Avoid expensive full-stream frame counting.
            self.index = -1
            self.frame_step = 1      # output frames covered by the last delivered frame
            self.previous = None
            self.name = str(path)
            self.iterator = iter(self.reader)
        except Exception:
            self.reader.close()
            raise

    def next_frame(self):
        step = 0
        while True:
            try:
                frame = next(self.iterator)
            except StopIteration:
                return None
            self.index += 1
            step += 1
            if self.previous is None or not _same_image(frame, self.previous):
                break  # a repeated frame carries no new information, only elapsed time
        self.previous, self.frame_step = frame, step
        if frame.ndim == 2:
            frame = np.repeat(frame[..., None], 3, axis=2)
        return frame[..., :3].astype(np.uint8, copy=False)

    def close(self):
        self.reader.close()


class DemoSource:
    fps = 30.
    frame_step = 1
    total = 240
    name = 'Synthetic motion | brief occlusion'
    initial_bbox = (70, 125, 40, 40)

    def __init__(self):
        self.index = -1
        y, x = np.indices((360, 640))
        base = 17 + ((x//40+y//40) % 2)*3
        self.background = np.stack([base, base+8, base+17], axis=-1).astype(np.uint8)
        rng = np.random.default_rng(13)
        texture = rng.integers(60, 235, (40, 40), dtype=np.uint8)
        self.target = np.stack([texture//2, texture, np.maximum(texture, 160)], axis=-1)
        self.target[[0, -1], :] = [77, 226, 212]
        self.target[:, [0, -1]] = [77, 226, 212]

    def truth(self, index):
        return (90+1.6*index, 145+.35*index)

    def next_frame(self):
        if self.index+1 >= self.total:
            return None
        self.index += 1
        frame = self.background.copy()
        cx, cy = self.truth(self.index)
        x, y = int(round(cx-20)), int(round(cy-20))
        if not 90 <= self.index < 108:
            frame[y:y+40, x:x+40] = self.target
        else:
            frame[105:255, 200:305] = [35, 43, 58]
        return frame

    def close(self):
        pass
