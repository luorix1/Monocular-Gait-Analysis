"""2D keypoint clean-up: left/right swap correction, gap filling, low-pass filtering."""
from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import butter, filtfilt

from ..io.data import Keypoints2D
from ..keypoints import IDX, LR_PAIRS

LEG_PAIRS = [p for p in LR_PAIRS if p[0] in
             ("LHip", "LKnee", "LAnkle", "LBigToe", "LSmallToe", "LHeel")]


def fix_left_right_swaps(kp: np.ndarray, pairs=LEG_PAIRS, conf_thr: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    """Side views often swap the near/far leg labels for a few frames. For each frame decide
    whether swapping all L/R leg labels makes the trajectory more continuous w.r.t. the
    previous (already corrected) frame. Returns (corrected kp, bool mask of swapped frames)."""
    kp = kp.copy()
    li = np.array([IDX[a] for a, _ in pairs])
    ri = np.array([IDX[b] for _, b in pairs])
    swapped = np.zeros(len(kp), bool)
    prev = None
    for f in range(len(kp)):
        cur = kp[f]
        ok = (cur[li, 2] > conf_thr) & (cur[ri, 2] > conf_thr)
        if prev is not None and ok.sum() >= 2:
            pl, pr = prev[li, :2], prev[ri, :2]
            cl, cr = cur[li, :2], cur[ri, :2]
            valid = ok & np.isfinite(pl).all(1) & np.isfinite(pr).all(1)
            if valid.sum() >= 2:
                keep = np.linalg.norm(cl - pl, axis=1)[valid].sum() + np.linalg.norm(cr - pr, axis=1)[valid].sum()
                swap = np.linalg.norm(cr - pl, axis=1)[valid].sum() + np.linalg.norm(cl - pr, axis=1)[valid].sum()
                if swap < 0.7 * keep:
                    tmp = cur[li].copy()
                    cur[li] = cur[ri]
                    cur[ri] = tmp
                    swapped[f] = True
        kp[f] = cur
        if ok.sum() >= 2:
            prev = cur.copy()
    return kp, swapped


def fill_gaps(x: np.ndarray, valid: np.ndarray, max_gap: int) -> np.ndarray:
    """Cubic-spline fill of gaps up to ``max_gap`` samples in a 1D signal."""
    x = x.copy()
    idx = np.flatnonzero(valid)
    if len(idx) < 4:
        return x
    cs = CubicSpline(idx, x[idx])
    inval = np.flatnonzero(~valid)
    if len(inval) == 0:
        return x
    # group runs
    runs = np.split(inval, np.flatnonzero(np.diff(inval) > 1) + 1)
    for r in runs:
        if len(r) <= max_gap and r[0] > idx[0] and r[-1] < idx[-1]:
            x[r] = cs(r)
    return x


def butter_lowpass(x: np.ndarray, fps: float, cutoff: float, order: int = 4, axis: int = 0) -> np.ndarray:
    """Zero-lag Butterworth low-pass along ``axis``; NaN segments are left untouched."""
    b, a = butter(order // 2 if order > 1 else 1, cutoff / (fps / 2))
    x = np.asarray(x, float)
    if np.isfinite(x).all():
        return filtfilt(b, a, x, axis=axis, padlen=min(3 * max(len(a), len(b)), x.shape[axis] - 1))
    out = x.copy()
    xm = np.moveaxis(out, axis, 0)
    flat = xm.reshape(xm.shape[0], -1)
    for j in range(flat.shape[1]):
        s = flat[:, j]
        fin = np.isfinite(s)
        runs = np.split(np.flatnonzero(fin), np.flatnonzero(np.diff(np.flatnonzero(fin)) > 1) + 1)
        for r in runs:
            if len(r) > 3 * max(len(a), len(b)):
                s[r] = filtfilt(b, a, s[r])
    return np.moveaxis(flat.reshape(xm.shape), 0, axis)


def clean_keypoints(k2d: Keypoints2D, conf_thr: float = 0.3, max_gap_s: float = 0.15,
                    cutoff_hz: float = 8.0, fix_swaps: bool = True) -> Keypoints2D:
    kp = k2d.kp.copy()
    meta = dict(k2d.meta)
    if fix_swaps:
        kp, sw = fix_left_right_swaps(kp, conf_thr=conf_thr)
        meta["lr_swapped_frames"] = int(sw.sum())
    max_gap = max(1, int(round(max_gap_s * k2d.fps)))
    for j in range(kp.shape[1]):
        valid = (kp[:, j, 2] > conf_thr) & np.isfinite(kp[:, j, :2]).all(1)
        for c in range(2):
            kp[:, j, c] = fill_gaps(kp[:, j, c], valid, max_gap)
        filled = ~valid & np.isfinite(kp[:, j, :2]).all(1)
        kp[filled, j, 2] = conf_thr  # filled samples get a modest confidence
        kp[~valid & ~filled, j, :2] = np.nan
        kp[~valid & ~filled, j, 2] = 0
    if cutoff_hz:
        kp[..., :2] = butter_lowpass(kp[..., :2], k2d.fps, cutoff_hz)
    meta.update(clean={"conf_thr": conf_thr, "max_gap_s": max_gap_s, "cutoff_hz": cutoff_hz})
    return Keypoints2D(kp, k2d.fps, k2d.image_size, k2d.names, meta)
