"""2D pose estimation backends -> Halpe-26 keypoints for the treadmill walker.

Backends
--------
``rtmlib`` (default) : RTMPose "BodyWithFeet" (Halpe-26, has heels & toes) via ONNX Runtime.
                       Runs on CPU (Mac/Linux) or CUDA (``device='cuda'``, needs onnxruntime-gpu).
``yolo``             : Ultralytics YOLO-pose (COCO-17). No foot keypoints -> heel/toe are
                       missing, which degrades gait events and belt-speed estimates.
                       Useful mainly as a detector or quick sanity check.

Only one person is expected; when several are detected we keep the one whose box best
continues the previous frame's (initially: the largest box).
"""
from __future__ import annotations

import numpy as np
from tqdm import tqdm

from ..io.data import Keypoints2D, iter_frames, video_info
from ..keypoints import NUM_KP, coco17_to_halpe26


class _Tracker:
    """Pick one person per frame: largest at start, then max IoU with previous box."""

    def __init__(self):
        self.prev = None

    @staticmethod
    def _box(kp, conf, thr=0.2):
        m = conf > thr
        if m.sum() < 3:
            return None
        p = kp[m]
        return np.r_[p.min(0), p.max(0)]

    @staticmethod
    def _iou(a, b):
        x0, y0 = np.maximum(a[:2], b[:2])
        x1, y1 = np.minimum(a[2:], b[2:])
        inter = max(0, x1 - x0) * max(0, y1 - y0)
        area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
        return inter / (area(a) + area(b) - inter + 1e-9)

    def select(self, kps: np.ndarray, confs: np.ndarray) -> int | None:
        boxes = [self._box(k, c) for k, c in zip(kps, confs)]
        cand = [(i, b) for i, b in enumerate(boxes) if b is not None]
        if not cand:
            return None
        if self.prev is None:
            i, b = max(cand, key=lambda ib: (ib[1][2] - ib[1][0]) * (ib[1][3] - ib[1][1]))
        else:
            i, b = max(cand, key=lambda ib: self._iou(ib[1], self.prev))
        self.prev = b
        return i


def _rtmlib_model(mode: str, device: str):
    try:
        from rtmlib import BodyWithFeet
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install rtmlib onnxruntime  (or onnxruntime-gpu on Ubuntu)") from e
    return BodyWithFeet(mode=mode, backend="onnxruntime", device=device, to_openpose=False)


def _yolo_model(weights: str, device: str):
    try:
        from ultralytics import YOLO
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install ultralytics") from e
    model = YOLO(weights)

    def run(frame):
        r = model.predict(frame, verbose=False, device=device)[0]
        if r.keypoints is None or len(r.keypoints) == 0:
            return np.zeros((0, 17, 2)), np.zeros((0, 17))
        d = r.keypoints.data.cpu().numpy()
        return d[..., :2], d[..., 2]
    return run


def detect_video(video, backend: str = "rtmlib", device: str = "cpu", mode: str = "balanced",
                 yolo_weights: str = "yolo11m-pose.pt", start: int = 0, stop: int | None = None,
                 progress: bool = True) -> Keypoints2D:
    info = video_info(video)
    if backend == "rtmlib":
        model = _rtmlib_model(mode, device)
    elif backend == "yolo":
        model = _yolo_model(yolo_weights, device)
    else:
        raise ValueError(f"unknown backend {backend}")

    n = (stop or info["n_frames"]) - start
    out = []
    tracker = _Tracker()
    for _, frame in tqdm(iter_frames(video, start, stop), total=n, disable=not progress,
                         desc=f"2D pose ({backend})"):
        kps, scores = model(frame)
        kps, scores = np.asarray(kps, float), np.asarray(scores, float)
        if kps.ndim == 2:
            kps, scores = kps[None], scores[None]
        sel = tracker.select(kps, scores) if len(kps) else None
        nk = 26 if backend == "rtmlib" else 17
        if sel is None:
            k = np.full((nk, 3), np.nan)
            k[:, 2] = 0
        else:
            k = np.c_[kps[sel], scores[sel]]
        out.append(k)
    kp = np.stack(out)
    if backend == "yolo":
        kp = coco17_to_halpe26(kp)
    # rtmlib returns raw SimCC scores (can exceed 1); squash to [0,1] for weighting
    if backend == "rtmlib":
        kp[..., 2] = np.clip(kp[..., 2] / 10.0 if np.nanmax(kp[..., 2]) > 1.5 else kp[..., 2], 0, 1)
    assert kp.shape[1] == NUM_KP
    return Keypoints2D(kp=kp, fps=info["fps"], image_size=(info["width"], info["height"]),
                       meta={"backend": backend, "mode": mode, "video": str(video), "start": start})
