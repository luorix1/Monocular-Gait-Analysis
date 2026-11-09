"""High-level gait analysis helpers (2D-only path and 3D path)."""
from __future__ import annotations

import numpy as np

from ..calibration.camera import Camera
from ..keypoints import FOOT, IDX
from .belt_speed import DEFAULT_KP_HEIGHT, belt_speed_from_2d, belt_speed_from_3d
from .events import GaitEvents, detect_events_zeni
from .spatiotemporal import stride_table, summarize


def foot_tracks_from_2d(uv: np.ndarray, cam: Camera, heights: dict | None = None):
    """Approximate 3D heel/toe/pelvis tracks from 2D + calibration (no 3D lifting):
    feet are back-projected to horizontal planes at their stance heights, the pelvis to
    the treadmill mid-sagittal plane (Z = 0). Good enough for Zeni events and belt speed;
    swing-phase foot positions are biased (the foot is above its assumed plane)."""
    h = {**DEFAULT_KP_HEIGHT, **(heights or {})}
    heel = {s: cam.pixel_to_plane_y(uv[:, IDX[FOOT[s]["heel"]]], h["heel"]) for s in FOOT}
    toe = {s: cam.pixel_to_plane_y(uv[:, IDX[FOOT[s]["toe"]]], h["toe"]) for s in FOOT}
    pelvis = cam.pixel_to_plane_z(uv[:, IDX["Hip"]], 0.0)
    return heel, toe, pelvis


def analyze_2d(uv: np.ndarray, cam: Camera, fps: float, conf: np.ndarray | None = None,
               heights: dict | None = None) -> dict:
    heel, toe, pelvis = foot_tracks_from_2d(uv, cam, heights)
    ev = detect_events_zeni(heel, toe, pelvis, fps)
    bs = belt_speed_from_2d(uv, cam, ev, fps, heights, conf)
    df = stride_table(ev, heel, bs["belt_speed"])
    return {"events": ev, "belt_speed": bs, "strides": df, "summary": summarize(df, bs["belt_speed"])}


def analyze_3d(X: np.ndarray, fps: float, belt_speed: float | None = None) -> dict:
    """X: (T, 26, 3) keypoints/markers in the treadmill frame (Halpe-26 order)."""
    heel = {s: X[:, IDX[FOOT[s]["heel"]]] for s in FOOT}
    toe = {s: X[:, IDX[FOOT[s]["toe"]]] for s in FOOT}
    pelvis = X[:, IDX["Hip"]]
    ev = detect_events_zeni(heel, toe, pelvis, fps)
    bs = belt_speed_from_3d(X, ev, fps)
    v = belt_speed if belt_speed is not None else bs["belt_speed"]
    df = stride_table(ev, heel, v)
    return {"events": ev, "belt_speed": bs, "belt_speed_used": v, "strides": df,
            "summary": summarize(df, v)}


def compare_events(ev: GaitEvents, gt: dict, fps: float, tol_frames: float = 5) -> dict:
    """Match detected events to ground truth; returns mean/max abs error in ms + miss counts."""
    out = {}
    for kind in ("hs", "to"):
        errs, missed = [], 0
        for s in ("L", "R"):
            det = np.asarray(getattr(ev, kind)[s])
            for g in gt[kind][s]:
                if len(det) == 0:
                    missed += 1
                    continue
                d = det[np.argmin(np.abs(det - g))] - g
                if abs(d) <= tol_frames:
                    errs.append(d)
                else:
                    missed += 1
        errs = np.array(errs)
        out[kind] = {"mean_ms": float(1000 * errs.mean() / fps) if len(errs) else np.nan,
                     "mae_ms": float(1000 * np.abs(errs).mean() / fps) if len(errs) else np.nan,
                     "max_ms": float(1000 * np.abs(errs).max() / fps) if len(errs) else np.nan,
                     "matched": int(len(errs)), "missed": missed}
    return out
