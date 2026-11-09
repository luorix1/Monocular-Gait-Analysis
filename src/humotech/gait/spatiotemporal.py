"""Spatiotemporal gait parameters on a treadmill.

Spatial parameters are computed in *belt coordinates*: a point fixed on the belt has
treadmill-frame position x(t) = x0 - v t, so the belt coordinate u = x + v t is constant for
a planted foot. A footprint at heel strike therefore sits at u = x_HS + v t_HS, and

    stride length = v * (t_HS2 - t_HS1) + (x_HS2 - x_HS1)
    step length   = v * (t_HS,ipsi - t_HS,contra) + (x_HS,ipsi - x_HS,contra)

which equals the equivalent over-ground stride/step length (the x-terms correct for the
subject drifting forward/backward on the belt).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import GaitEvents

OTHER = {"L": "R", "R": "L"}


def _interp(arr: np.ndarray, f: float) -> np.ndarray:
    """Linear interpolation of (T, D) array at fractional frame f."""
    i = int(np.floor(f))
    i = min(max(i, 0), len(arr) - 2)
    a = f - i
    return (1 - a) * arr[i] + a * arr[i + 1]


def stride_table(ev: GaitEvents, heel: dict[str, np.ndarray], belt_speed: float) -> pd.DataFrame:
    fps = ev.fps
    rows = []
    for s in ("L", "R"):
        c = OTHER[s]
        hs, to = np.sort(ev.hs[s]), np.sort(ev.to[s])
        hs_c, to_c = np.sort(ev.hs[c]), np.sort(ev.to[c])
        for h1, h2 in zip(hs[:-1], hs[1:]):
            T = (h2 - h1) / fps
            r = {"side": s, "hs_frame": h1, "t_hs": h1 / fps, "stride_time": T,
                 "stride_frequency": 1 / T}
            to_in = to[(to > h1) & (to < h2)]
            if len(to_in) == 1:
                r["stance_time"] = (to_in[0] - h1) / fps
                r["swing_time"] = (h2 - to_in[0]) / fps
                r["stance_pct"] = 100 * r["stance_time"] / T
                cto = to_c[(to_c > h1) & (to_c < to_in[0])]
                chs = hs_c[(hs_c > h1) & (hs_c < to_in[0])]
                if len(cto) and len(chs):
                    r["initial_double_support"] = (cto[0] - h1) / fps
                    r["terminal_double_support"] = (to_in[0] - chs[-1]) / fps
                    r["double_support_pct"] = 100 * (r["initial_double_support"]
                                                     + r["terminal_double_support"]) / T
            x1, x2 = _interp(heel[s], h1), _interp(heel[s], h2)
            r["stride_length"] = belt_speed * T + (x2[0] - x1[0])
            # step ending at h2 (ipsilateral HS) started at the previous contralateral HS
            prev_c = hs_c[(hs_c > h1) & (hs_c < h2)]
            if len(prev_c):
                hc = prev_c[-1]
                xc = _interp(heel[c], hc)
                r["step_time"] = (h2 - hc) / fps
                r["step_length"] = belt_speed * r["step_time"] + (x2[0] - xc[0])
                r["step_width"] = abs(x2[2] - xc[2])
            rows.append(r)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, belt_speed: float) -> dict:
    out = {"belt_speed_m_s": belt_speed, "n_strides": {s: int((df.side == s).sum()) for s in ("L", "R")}}
    cols = [c for c in ["stride_time", "stride_frequency", "stride_length", "step_time", "step_length",
                        "step_width", "stance_time", "swing_time", "stance_pct", "double_support_pct"]
            if c in df]
    for c in cols:
        out[c] = {
            "mean": float(df[c].mean()), "sd": float(df[c].std()),
            "L": float(df.loc[df.side == "L", c].mean()), "R": float(df.loc[df.side == "R", c].mean()),
        }
        if out[c]["mean"]:
            out[c]["cv_pct"] = float(100 * out[c]["sd"] / abs(out[c]["mean"]))
        l, r = out[c]["L"], out[c]["R"]
        if np.isfinite(l) and np.isfinite(r) and (l + r):
            out[c]["symmetry_index_pct"] = float(200 * abs(l - r) / (l + r))
    if "stride_time" in out:
        out["cadence_steps_per_min"] = 120.0 / out["stride_time"]["mean"]
    return out
