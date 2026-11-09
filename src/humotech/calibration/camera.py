"""Pinhole camera model in the *treadmill* world frame.

World (treadmill) frame — same convention as OpenSim ground:
    origin : centre of the belt surface
    +X     : forward, toward the front of the treadmill (the way the subject faces)
    +Y     : up (belt surface is the plane Y = 0)
    +Z     : to the subject's right

Camera convention is OpenCV's: ``x_cam = R @ X_world + t``, image u right, v down.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Camera:
    K: np.ndarray                      # (3,3)
    dist: np.ndarray                   # (5,) OpenCV distortion (k1,k2,p1,p2,k3)
    R: np.ndarray                      # (3,3) world -> camera rotation
    t: np.ndarray                      # (3,)  world -> camera translation
    image_size: tuple[int, int]        # (width, height)
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ basics
    @property
    def center(self) -> np.ndarray:
        """Camera centre in world coordinates."""
        return -self.R.T @ self.t

    @property
    def rvec(self) -> np.ndarray:
        return cv2.Rodrigues(self.R)[0].ravel()

    def project(self, X: np.ndarray) -> np.ndarray:
        """World points (..., 3) -> pixels (..., 2), including lens distortion."""
        X = np.asarray(X, dtype=float)
        shp = X.shape[:-1]
        uv, _ = cv2.projectPoints(X.reshape(-1, 1, 3), self.rvec, self.t.astype(float),
                                  self.K, self.dist)
        return uv.reshape(*shp, 2)

    def to_camera(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X) @ self.R.T + self.t

    def undistort_pixels(self, uv: np.ndarray) -> np.ndarray:
        """Distorted pixels (..., 2) -> normalised, undistorted image coords (..., 2)."""
        uv = np.asarray(uv, dtype=float)
        shp = uv.shape[:-1]
        n = cv2.undistortPoints(uv.reshape(-1, 1, 2), self.K, self.dist)
        return n.reshape(*shp, 2)

    def rays(self, uv: np.ndarray) -> np.ndarray:
        """Unit ray directions in world frame for pixels (..., 2)."""
        n = self.undistort_pixels(uv)
        d_cam = np.concatenate([n, np.ones(n.shape[:-1] + (1,))], axis=-1)
        d = d_cam @ self.R  # == (R.T @ d_cam.T).T
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def pixel_to_plane_y(self, uv: np.ndarray, y: float | np.ndarray = 0.0) -> np.ndarray:
        """Intersect pixel rays with the horizontal plane Y = y (e.g. belt, or a keypoint's
        height above the belt). Returns world points (..., 3)."""
        d = self.rays(uv)
        C = self.center
        s = (np.asarray(y) - C[1]) / d[..., 1]
        return C + s[..., None] * d

    def pixel_to_plane_z(self, uv: np.ndarray, z: float | np.ndarray = 0.0) -> np.ndarray:
        """Intersect pixel rays with the vertical sagittal plane Z = z."""
        d = self.rays(uv)
        C = self.center
        s = (np.asarray(z) - C[2]) / d[..., 2]
        return C + s[..., None] * d

    # --------------------------------------------------------------------- I/O
    def to_dict(self) -> dict:
        return {
            "K": self.K.tolist(), "dist": self.dist.tolist(),
            "R": self.R.tolist(), "t": self.t.tolist(),
            "image_size": list(self.image_size), "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Camera":
        return cls(np.array(d["K"], float), np.array(d.get("dist", [0] * 5), float),
                   np.array(d["R"], float), np.array(d["t"], float),
                   tuple(d["image_size"]), d.get("meta", {}))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Camera":
        d = json.loads(Path(path).read_text())
        return cls.from_dict(d["camera"] if "camera" in d else d)


def look_at(eye, target, up=(0, 1, 0)) -> tuple[np.ndarray, np.ndarray]:
    """R, t for a camera at ``eye`` looking at ``target`` (world Y up, OpenCV camera)."""
    eye, target, up = map(lambda a: np.asarray(a, float), (eye, target, up))
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(z, up)  # camera x (right) ; camera y points down
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])
    return R, -R @ eye
