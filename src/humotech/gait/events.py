"""Gait event detection on a treadmill from kinematics (treadmill frame, +X forward).

Default: Zeni et al. (2008), "Two simple methods for determining gait events during
treadmill and overground walking using kinematic data", Gait & Posture 27:710-714.
  heel strike (HS) = local maxima of  heel_x - pelvis_x
  toe off     (TO) = local minima of  toe_x  - pelvis_x
On a treadmill the pelvis is ~stationary, so this is essentially foot AP excursion.

Alternative ('velocity'): foot AP velocity relative to the belt — HS when the heel's
forward velocity drops through ~ -v_belt; TO when the toe's velocity rises away from it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks

from ..pose2d.filtering import butter_lowpass


@dataclass
class GaitEvents:
    fps: float
    hs: dict[str, np.ndarray] = field(default_factory=dict)   # side -> frame indices (float, sub-frame)
    to: dict[str, np.ndarray] = field(default_factory=dict)
    method: str = "zeni"

    def times(self, kind: str, side: str) -> np.ndarray:
        return getattr(self, kind)[side] / self.fps

    def to_dict(self) -> dict:
        return {"fps": self.fps, "method": self.method,
                "hs": {k: v.tolist() for k, v in self.hs.items()},
                "to": {k: v.tolist() for k, v in self.to.items()}}

    def stance_mask(self, side: str, n: int) -> np.ndarray:
        """Boolean (n,) True between each HS and the following TO of that side."""
        m = np.zeros(n, bool)
        for h in self.hs[side]:
            nxt = self.to[side][self.to[side] > h]
            if len(nxt):
                m[int(np.ceil(h)):int(np.floor(nxt[0])) + 1] = True
        return m


def dominant_period(x: np.ndarray, fps: float, min_s: float = 0.6, max_s: float = 2.5) -> float:
    """Stride period (s) from the autocorrelation of a periodic signal."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    x = x - x.mean()
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac /= ac[0] + 1e-12
    lo, hi = int(min_s * fps), min(int(max_s * fps), len(ac) - 1)
    if hi <= lo:
        return np.nan
    k = lo + int(np.argmax(ac[lo:hi]))
    if 0 < k < len(ac) - 1:  # parabolic refinement
        a, b, c = ac[k - 1], ac[k], ac[k + 1]
        k = k + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
    return k / fps


def _subframe_peaks(sig: np.ndarray, distance: int, prominence: float) -> np.ndarray:
    pk, _ = find_peaks(sig, distance=distance, prominence=prominence)
    out = []
    for k in pk:
        if 0 < k < len(sig) - 1:
            a, b, c = sig[k - 1], sig[k], sig[k + 1]
            out.append(k + 0.5 * (a - c) / (a - 2 * b + c + 1e-12))
        else:
            out.append(float(k))
    return np.array(out)


def detect_events_zeni(heel: dict[str, np.ndarray], toe: dict[str, np.ndarray], pelvis: np.ndarray,
                       fps: float, cutoff_hz: float = 6.0) -> GaitEvents:
    """heel/toe: side -> (T,3) positions; pelvis: (T,3). Treadmill frame (+X forward)."""
    ev = GaitEvents(fps=fps, method="zeni")
    for side in heel:
        h = heel[side][:, 0] - pelvis[:, 0]
        t = toe[side][:, 0] - pelvis[:, 0]
        h = butter_lowpass(_interp_nan(h), fps, cutoff_hz)
        t = butter_lowpass(_interp_nan(t), fps, cutoff_hz)
        T = dominant_period(h, fps)
        dist = max(1, int(0.6 * T * fps)) if np.isfinite(T) else int(0.5 * fps)
        prom_h = 0.25 * (np.nanpercentile(h, 95) - np.nanpercentile(h, 5))
        prom_t = 0.25 * (np.nanpercentile(t, 95) - np.nanpercentile(t, 5))
        ev.hs[side] = _subframe_peaks(h, dist, prom_h)
        ev.to[side] = _subframe_peaks(-t, dist, prom_t)
    return ev


def detect_events_velocity(heel: dict[str, np.ndarray], toe: dict[str, np.ndarray], fps: float,
                           belt_speed: float, cutoff_hz: float = 6.0, frac: float = 0.5) -> GaitEvents:
    """Velocity-threshold events: the foot is in stance while its AP velocity ~ -belt_speed.
    HS: heel AP velocity crosses down through (1-frac)*(-v)...; TO: toe velocity crosses up."""
    ev = GaitEvents(fps=fps, method="velocity")
    for side in heel:
        vh = np.gradient(butter_lowpass(_interp_nan(heel[side][:, 0]), fps, cutoff_hz)) * fps
        vt = np.gradient(butter_lowpass(_interp_nan(toe[side][:, 0]), fps, cutoff_hz)) * fps
        thr = -frac * belt_speed
        hs = np.flatnonzero((vh[:-1] > thr) & (vh[1:] <= thr))
        to = np.flatnonzero((vt[:-1] < thr) & (vt[1:] >= thr))
        ev.hs[side] = hs + (thr - vh[hs]) / (vh[hs + 1] - vh[hs])
        ev.to[side] = to + (thr - vt[to]) / (vt[to + 1] - vt[to])
    return ev


def _interp_nan(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, float).copy()
    m = np.isfinite(x)
    if m.all() or m.sum() < 2:
        return x
    x[~m] = np.interp(np.flatnonzero(~m), np.flatnonzero(m), x[m])
    return x
