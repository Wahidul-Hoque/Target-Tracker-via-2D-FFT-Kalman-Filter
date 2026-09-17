"""Reproducible core-only benchmark; excludes decoding, plotting and GUI."""
import platform
from time import perf_counter
import numpy as np
from signal13.core.fft_engine import fft_2d
from signal13.core.tracker import TargetTracker
from signal13.io.sources import DemoSource


def main():
    print(f'Python {platform.python_version()} / NumPy {np.__version__} / {platform.machine()}')
    for n in (64,128,256,512):
        patch=np.random.default_rng(13).normal(size=(n,n))
        fft_2d(patch)
        times=[]
        for _ in range(15):
            start=perf_counter();fft_2d(patch);times.append((perf_counter()-start)*1000)
        print(f'{n}x{n} custom FFT: median {np.median(times):.2f} ms')
    source,tracker=DemoSource(),TargetTracker()
    tracker.initialize(source.next_frame(),source.initial_bbox)
    errors=[];times=[];accepted=0
    for i in range(1,240):
        r=tracker.process(source.next_frame(),1/source.fps)
        errors.append(float(np.sqrt(np.sum((np.asarray(r.center)-source.truth(i))**2))))
        times.append(r.processing_ms)
        accepted+=r.measurement is not None
    print(f'Demo: {accepted}/239 measurements accepted; 18 intended hidden frames')
    print(f'Position error: mean {np.mean(errors):.3f} px, max {max(errors):.3f} px')
    print(f'Core frame time: median {np.median(times):.2f} ms, p95 {np.percentile(times,95):.2f} ms')

if __name__=='__main__':main()
