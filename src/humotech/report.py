"""Diagnostic plots for a processed session."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .gait.events import GaitEvents  # noqa: E402
from .io.data import read_mot  # noqa: E402
from .keypoints import FOOT, IDX  # noqa: E402

COL = {"L": "#2563eb", "R": "#dc2626"}


def time_normalise(y: np.ndarray, hs: np.ndarray, n: int = 101) -> np.ndarray:
    cycles = []
    for a, b in zip(hs[:-1], hs[1:]):
        t = np.linspace(a, b, n)
        cycles.append(np.interp(t, np.arange(len(y)), y))
    return np.array(cycles)


def make_plots(out_dir, X: np.ndarray, ev: GaitEvents, fps: float, mot_path=None) -> None:
    pdir = Path(out_dir) / "plots"
    pdir.mkdir(exist_ok=True)
    t = np.arange(len(X)) / fps

    # foot AP trajectories + events
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True)
    for ax, s in zip(axes, ("L", "R")):
        rel = lambda n: X[:, IDX[n], 0] - X[:, IDX["Hip"], 0]
        ax.plot(t, rel(FOOT[s]["heel"]), color=COL[s], label="heel - pelvis")
        ax.plot(t, rel(FOOT[s]["toe"]), color=COL[s], ls="--", alpha=0.6, label="toe - pelvis")
        for h in ev.hs[s]:
            ax.axvline(h / fps, color="k", lw=0.8)
        for o in ev.to[s]:
            ax.axvline(o / fps, color="0.5", lw=0.8, ls=":")
        ax.set_ylabel(f"{s} AP (m)")
        ax.legend(loc="upper right", fontsize=8, frameon=False)
    axes[-1].set_xlabel("time (s)   [solid = heel strike, dotted = toe off]")
    fig.tight_layout()
    fig.savefig(pdir / "events.png", dpi=120)
    plt.close(fig)

    # joint angles normalised to the gait cycle
    if mot_path is not None and Path(mot_path).exists():
        df = read_mot(mot_path)
        coords = [("hip_flexion", "Hip flexion"), ("knee_angle", "Knee flexion"), ("ankle_angle", "Ankle dorsiflexion")]
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
        for ax, (c, title) in zip(axes, coords):
            for s, suf in (("L", "_l"), ("R", "_r")):
                if c + suf not in df or len(ev.hs[s]) < 2:
                    continue
                cyc = time_normalise(df[c + suf].to_numpy(), ev.hs[s])
                m, sd = cyc.mean(0), cyc.std(0)
                x = np.linspace(0, 100, cyc.shape[1])
                ax.plot(x, m, color=COL[s], label=s)
                ax.fill_between(x, m - sd, m + sd, color=COL[s], alpha=0.15)
            ax.set_title(title)
            ax.set_xlabel("% gait cycle")
        axes[0].set_ylabel("deg")
        axes[0].legend(frameon=False)
        fig.tight_layout()
        fig.savefig(pdir / "joint_angles.png", dpi=120)
        plt.close(fig)
