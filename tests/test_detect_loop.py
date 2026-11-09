"""Exercise the video -> 2D keypoint loop (I/O, subject selection, score handling) with a fake
model, since the real RTMPose/YOLO weights need a network download."""
import cv2
import numpy as np

from humotech.pose2d import detect


def _write_video(path, n=20, size=(320, 240), fps=30):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for _ in range(n):
        vw.write(np.zeros((size[1], size[0], 3), np.uint8))
    vw.release()


def test_detect_loop_with_fake_rtmlib(tmp_path, monkeypatch, session):
    vid = tmp_path / "v.avi"
    _write_video(vid)
    uv = session.k2d.uv[:20] / 6.0          # fits in 320x240

    class Fake:
        i = 0
        def __call__(self, frame):
            k = uv[Fake.i]
            Fake.i += 1
            small = 0.3 * (k - k.mean(0)) + 20  # a second, smaller "person" in the corner
            return np.stack([k, small]), np.stack([np.full(26, 5.0), np.full(26, 5.0)])

    monkeypatch.setattr(detect, "_rtmlib_model", lambda mode, device: Fake())
    k2d = detect.detect_video(vid, backend="rtmlib", progress=False)
    assert k2d.kp.shape == (20, 26, 3)
    assert np.allclose(k2d.uv, uv)              # the large subject was selected every frame
    assert (k2d.conf <= 1).all() and (k2d.conf > 0).all()
    assert k2d.fps == 30 and k2d.image_size == (320, 240)
