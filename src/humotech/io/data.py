"""Small containers + file formats (npz for keypoints, TRC/MOT for OpenSim)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from ..keypoints import HALPE26


# ------------------------------------------------------------------ keypoints
@dataclass
class Keypoints2D:
    kp: np.ndarray                 # (T, K, 3) u, v, confidence
    fps: float
    image_size: tuple[int, int]
    names: list[str] = field(default_factory=lambda: list(HALPE26))
    meta: dict = field(default_factory=dict)

    @property
    def uv(self) -> np.ndarray:
        return self.kp[..., :2]

    @property
    def conf(self) -> np.ndarray:
        return self.kp[..., 2]

    @property
    def t(self) -> np.ndarray:
        return np.arange(len(self.kp)) / self.fps

    def save(self, path):
        np.savez_compressed(path, kp=self.kp, fps=self.fps, image_size=np.array(self.image_size),
                            names=np.array(self.names), meta=np.array(self.meta, dtype=object))

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=True)
        return cls(d["kp"], float(d["fps"]), tuple(int(x) for x in d["image_size"]),
                   [str(n) for n in d["names"]], d["meta"].item() if "meta" in d else {})


@dataclass
class Keypoints3D:
    X: np.ndarray                  # (T, K, 3) metres, treadmill frame
    conf: np.ndarray               # (T, K)
    fps: float
    names: list[str] = field(default_factory=lambda: list(HALPE26))
    meta: dict = field(default_factory=dict)

    @property
    def t(self) -> np.ndarray:
        return np.arange(len(self.X)) / self.fps

    def save(self, path):
        np.savez_compressed(path, X=self.X, conf=self.conf, fps=self.fps, names=np.array(self.names),
                            meta=np.array(self.meta, dtype=object))

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=True)
        return cls(d["X"], d["conf"], float(d["fps"]), [str(n) for n in d["names"]],
                   d["meta"].item() if "meta" in d else {})


# ---------------------------------------------------------------------- video
def video_info(path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video {path}")
    info = {
        "fps": cap.get(cv2.CAP_PROP_FPS) or 30.0,
        "n_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return info


def iter_frames(path, start: int = 0, stop: int | None = None, step: int = 1):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    i = start
    while stop is None or i < stop:
        ok, frame = cap.read()
        if not ok:
            break
        if (i - start) % step == 0:
            yield i, frame
        i += 1
    cap.release()


# ------------------------------------------------------------------ OpenSim IO
def write_trc(path, X: np.ndarray, names: list[str], fps: float, units: str = "m",
              t0: float = 0.0) -> None:
    """Write markers (T, M, 3) to an OpenSim .trc file. NaNs are written as blanks."""
    T, M, _ = X.shape
    p = Path(path)
    header = [
        f"PathFileType\t4\t(X/Y/Z)\t{p.name}",
        "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
        f"{fps:g}\t{fps:g}\t{T}\t{M}\t{units}\t{fps:g}\t1\t{T}",
        "Frame#\tTime\t" + "\t\t\t".join(names) + "\t\t",
        "\t\t" + "\t".join(f"X{i+1}\tY{i+1}\tZ{i+1}" for i in range(M)),
        "",
        "",
    ]
    lines = []
    for f in range(T):
        vals = "\t".join("" if not np.isfinite(v) else f"{v:.6f}" for v in X[f].ravel())
        lines.append(f"{f+1}\t{t0 + f / fps:.6f}\t{vals}")
    p.write_text("\n".join(header) + "\n".join(lines) + "\n")


def read_trc(path) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Returns (X (T,M,3), marker names, time)."""
    lines = Path(path).read_text().splitlines()
    names = [n for n in lines[3].split("\t")[2:] if n.strip()]
    rows = [ln.split("\t") for ln in lines[5:] if ln.strip()]
    ncol = 2 + 3 * len(names)
    data = np.array([[float(v) if v.strip() else np.nan for v in (r + [""] * ncol)[:ncol]]
                     for r in rows])
    t = data[:, 1]
    X = data[:, 2:2 + 3 * len(names)].reshape(len(data), len(names), 3)
    return X, names, t


def read_mot(path) -> pd.DataFrame:
    """Read an OpenSim .mot/.sto (header ends with 'endheader')."""
    lines = Path(path).read_text().splitlines()
    n = next(i for i, l in enumerate(lines) if l.strip().lower() == "endheader")
    df = pd.read_csv(path, sep=r"\s+", skiprows=n + 1)
    return df


def write_mot(path, df: pd.DataFrame, name: str = "coordinates", in_degrees: bool = True) -> None:
    hdr = [name, "version=1", f"nRows={len(df)}", f"nColumns={df.shape[1]}",
           f"inDegrees={'yes' if in_degrees else 'no'}", "endheader"]
    Path(path).write_text("\n".join(hdr) + "\n" + df.to_csv(sep="\t", index=False, float_format="%.6f"))
