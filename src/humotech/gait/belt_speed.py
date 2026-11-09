"""Treadmill belt speed from the stance foot.

While a foot is flat on the belt it moves backwards with the belt, so its AP velocity in
the treadmill frame equals -v_belt. Two estimators:

``belt_speed_from_2d`` : uses only 2D foot keypoints + calibration. Each foot pixel is
    back-projected onto the horizontal plane Y = h (h = that keypoint's height above the
    belt during flat-foot stance, e.g. heel ~ 2-4 cm). Using the right plane height matters:
    projecting onto Y=0 inflates speed by C_y / (C_y - h) (C_y = camera height), i.e. ~7 %
    for an ankle keypoint with the camera at 1 m.
``belt_speed_from_3d`` : uses 3D foot trajectories (refined keypoints or OpenSim markers).

Both take the median AP velocity over the *middle* part of each stance phase
(default 20-70 % of stance, i.e. flat-foot, avoiding heel rocker / push-off).
"""
from __future__ import annotations

import numpy as np

from ..calibration.camera import Camera
from ..keypoints import FOOT, IDX
from ..pose2d.filtering import butter_lowpass
from .events import GaitEvents, _interp_nan

DEFAULT_KP_HEIGHT = {"heel": 0.03, "toe": 0.02, "toe2": 0.02, "ankle": 0.08}


def _stance_windows(ev: GaitEvents, side: str, lo: float, hi: float) -> list[tuple[int, int]]:
    w = []
    for h in ev.hs[side]:
        nxt = ev.to[side][ev.to[side] > h]
        if len(nxt):
            d = nxt[0] - h
            a, b = int(np.ceil(h + lo * d)), int(np.floor(h + hi * d))
            if b > a:
                w.append((a, b))
    return w


def stance_velocity(traj: dict[str, dict[str, np.ndarray]], ev: GaitEvents, fps: float,
                    window=(0.2, 0.7), cutoff_hz: float = 8.0) -> dict:
    """traj: side -> {point_name: (T,3)}. Returns per-stance median AP velocity samples."""
    samples = []
    per_side = {}
    for side, pts in traj.items():
        vs = []
        for name, X in pts.items():
            x = butter_lowpass(_interp_nan(X[:, 0]), fps, cutoff_hz)
            vx = np.gradient(x) * fps
            for a, b in _stance_windows(ev, side, *window):
                seg = vx[a:b + 1]
                seg = seg[np.isfinite(seg)]
                if len(seg):
                    vs.append(-np.median(seg))
        per_side[side] = np.array(vs)
        samples.extend(vs)
    samples = np.array(samples)
    return {
        "belt_speed": float(np.median(samples)) if len(samples) else np.nan,
        "iqr": (float(np.percentile(samples, 25)), float(np.percentile(samples, 75))) if len(samples) else None,
        "n_samples": int(len(samples)),
        "per_side": {k: float(np.median(v)) if len(v) else np.nan for k, v in per_side.items()},
    }


def foot_plane_trajectories(uv: np.ndarray, cam: Camera, heights: dict | None = None,
                            points=("heel", "toe", "toe2", "ankle"), conf: np.ndarray | None = None,
                            conf_thr: float = 0.3) -> dict[str, dict[str, np.ndarray]]:
    """Back-project 2D foot keypoints (T, 26, 2) onto horizontal planes at their stance heights."""
    heights = {**DEFAULT_KP_HEIGHT, **(heights or {})}
    out = {}
    for side, d in FOOT.items():
        out[side] = {}
        for p in points:
            j = IDX[d[p]]
            X = cam.pixel_to_plane_y(uv[:, j], heights[p])
            if conf is not None:
                X[conf[:, j] < conf_thr] = np.nan
            if np.isfinite(X).any():
                out[side][p] = X
    return out


def belt_speed_from_2d(uv: np.ndarray, cam: Camera, ev: GaitEvents, fps: float,
                       heights: dict | None = None, conf: np.ndarray | None = None,
                       points=("heel", "toe", "toe2"), window=(0.2, 0.7)) -> dict:
    traj = foot_plane_trajectories(uv, cam, heights, points, conf)
    res = stance_velocity(traj, ev, fps, window)
    res["method"] = "2d_plane_backprojection"
    return res


def belt_speed_from_3d(X: np.ndarray, ev: GaitEvents, fps: float,
                       points=("heel", "toe", "toe2"), window=(0.2, 0.7)) -> dict:
    traj = {s: {p: X[:, IDX[FOOT[s][p]]] for p in points} for s in FOOT}
    res = stance_velocity(traj, ev, fps, window)
    res["method"] = "3d_stance_foot"
    return res
