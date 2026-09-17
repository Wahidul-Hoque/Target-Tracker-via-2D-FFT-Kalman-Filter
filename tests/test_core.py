"""NumPy FFT/linalg are test oracles only, never application dependencies."""
import numpy as np
import pytest
from signal13.core.fft_engine import fft_1d, fft_2d, ifft_2d
from signal13.core.phase_correlation import locate_displacement, compute_psr
from signal13.core.preprocessing import crop_center, generate_2d_hann_window
from signal13.core.kalman import KalmanFilter
from signal13.core.tracker import TargetTracker
from signal13.io.sources import DemoSource, VideoSource
from signal13.io.session import SessionLog

@pytest.mark.parametrize('shape', [(1,1), (2,8), (32,64), (128,128)])
def test_fft_reference(shape):
    rng = np.random.default_rng(9)
    x = rng.normal(size=shape)+1j*rng.normal(size=shape)
    np.testing.assert_allclose(fft_2d(x), np.fft.fft2(x), atol=1e-10)
    np.testing.assert_allclose(ifft_2d(fft_2d(x)), x, atol=1e-12)

@pytest.mark.parametrize('n', [0,3,6,12])
def test_invalid_length(n):
    with pytest.raises(ValueError): fft_1d(np.ones(n))

@pytest.mark.parametrize('dy,dx', [(0,0),(7,-11),(-12,18),(0,31)])
def test_shift_sign_and_peak(dy,dx):
    a = np.random.default_rng(10).normal(size=(64,64))
    shift, psr, _ = locate_displacement(a, np.roll(a,(dy,dx),axis=(0,1)))
    np.testing.assert_allclose(shift,[dy,dx],atol=1e-8)
    assert psr > 100

def test_blank_confidence():
    assert compute_psr(np.zeros((32,32)),0,0) == 0

def test_subpixel():
    a = np.random.default_rng(12).normal(size=(64,64))
    fy,fx = np.meshgrid(np.fft.fftfreq(64),np.fft.fftfreq(64),indexing='ij')
    b = np.fft.ifft2(np.fft.fft2(a)*np.exp(-2j*np.pi*(fy*2.25+fx*-3.2))).real
    shift,_,_ = locate_displacement(a,b)
    np.testing.assert_allclose(shift,[2.25,-3.2],atol=.16)

def test_border_and_window():
    patch,origin = crop_center(np.ones((8,8)),(0,0),(8,8))
    assert origin == (-4,-4) and patch.sum() == 16
    np.testing.assert_allclose(generate_2d_hann_window(8,8)[0],0)
    np.testing.assert_array_equal(generate_2d_hann_window(1,1),[[1]])

def test_kalman():
    k=KalmanFilter(0,0)
    for i in range(1,61):
        k.predict(1/30)
        assert k.update((2*i,i))
    np.testing.assert_allclose(k.state[2:],[60,30],atol=.2)
    for _ in range(15): k.predict(1/30)
    np.testing.assert_allclose(k.state[:2],[150,75],atol=.2)
    assert not k.update((1e6,1e6))
    assert np.linalg.eigvalsh(k.covariance).min() >= 0

def test_demo_and_export(tmp_path):
    s,t,log=DemoSource(),TargetTracker(),SessionLog()
    t.initialize(s.next_frame(),s.initial_bbox)
    errors=[]; statuses={}
    for i in range(1,240):
        r=t.process(s.next_frame(),1/30,diagnostics=i==1)
        errors.append(np.linalg.norm(np.asarray(r.center)-s.truth(i)))
        statuses[i]=r.status
        log.append(i,i/30,r)
    assert all(statuses[i]=='OCCLUDED' for i in range(90,108))
    assert statuses[108]==statuses[239]=='TRACKING'
    assert max(errors)<1.
    path=tmp_path/'session.csv'; log.export(path)
    assert len(path.read_text().splitlines())==240
    assert log.total==239 and log.accepted==221
    log.close()
    assert s.next_frame() is None

def test_prolonged_loss():
    s,t=DemoSource(),TargetTracker()
    frame=s.next_frame();t.initialize(frame,s.initial_bbox)
    for _ in range(15):t.process(s.next_frame(),1/30)
    blank=np.zeros_like(frame)
    results=[t.process(blank,1/30) for _ in range(40)]
    assert results[-1].status=='LOST' and results[-1].measurement is None
    np.testing.assert_allclose(results[-1].center,results[-2].center)
    with pytest.raises(ValueError):TargetTracker().initialize(blank,(10,10,40,40))

def test_video_decode(tmp_path):
    import imageio.v2 as imageio
    path=tmp_path/'sample.mp4'
    frames=[np.full((64,96,3),v,dtype=np.uint8) for v in (20,80,140)]
    imageio.mimwrite(path,frames,fps=12,codec='libx264')
    s=VideoSource(str(path))
    assert s.fps==12
    decoded=[s.next_frame() for _ in frames]
    assert s.index==2 and all(f.shape==(64,96,3) for f in decoded)
    assert s.next_frame() is None
    s.close()
