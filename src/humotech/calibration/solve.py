"""Solve the camera from clicked landmarks with known treadmill-frame coordinates.

Minimum input: the 4 corners of the belt (known length & width) -> a plane homography.
From that we recover

* the focal length (if no intrinsics file is given), assuming square pixels, zero skew,
  principal point at the image centre and negligible distortion  (Zhang 2000 constraints),
* the camera pose (R, t) in the treadmill frame (planar PnP, IPPE), refined by
  non-linear least squares.

Extra landmarks (e.g. top of the handrail at a known height, a second marked line on
the belt) are used in the refinement and make the solution much better conditioned —
any point whose (X, Y, Z) in the treadmill frame you can measure with a tape helps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

from .camera import Camera

BELT_CORNERS = ["belt_front_left", "belt_front_right", "belt_back_right", "belt_back_left"]


def belt_corner_world(length: float, width: float) -> dict[str, np.ndarray]:
    """World coordinates of the 4 belt-surface corners (front = direction subject faces)."""
    L, W = length / 2, width / 2
    return {
        "belt_front_left": np.array([+L, 0.0, -W]),
        "belt_front_right": np.array([+L, 0.0, +W]),
        "belt_back_right": np.array([-L, 0.0, +W]),
        "belt_back_left": np.array([-L, 0.0, -W]),
    }


@dataclass
class Landmark:
    name: str
    world: np.ndarray   # (3,) metres, treadmill frame
    pixel: np.ndarray   # (2,) pixels


def focal_from_homography(H: np.ndarray, cx: float, cy: float) -> float:
    """Focal length (px) from a plane->image homography, principal point known.

    With H' = Kc^-1 H = diag(f, f, 1) [r1 r2 t], orthonormality of r1, r2 gives two
    equations linear in w = 1/f^2; solved in least squares.
    """
    Kc_inv = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], float)
    Hp = Kc_inv @ H
    h1, h2 = Hp[:, 0], Hp[:, 1]
    a = np.array([h1[0] * h2[0] + h1[1] * h2[1],
                  h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    w = -(a @ b) / (a @ a)
    if not np.isfinite(w) or w <= 0:
        raise ValueError("Could not estimate focal length from the belt corners (the belt plane "
                         "may be nearly fronto-parallel). Provide intrinsics from a checkerboard.")
    return float(1.0 / np.sqrt(w))


def solve_camera(landmarks: list[Landmark], image_size: tuple[int, int],
                 K: np.ndarray | None = None, dist: np.ndarray | None = None,
                 refine_focal: bool | None = None) -> tuple[Camera, dict]:
    """Calibrate from landmarks. Returns (camera, report)."""
    W_img, H_img = image_size
    Xw = np.array([lm.world for lm in landmarks], float)
    uv = np.array([lm.pixel for lm in landmarks], float)
    if len(landmarks) < 4:
        raise ValueError("Need at least 4 landmarks (the 4 belt corners).")

    known_K = K is not None
    dist = np.zeros(5) if dist is None else np.asarray(dist, float).ravel()
    if refine_focal is None:
        refine_focal = not known_K
    cx, cy = (W_img - 1) / 2, (H_img - 1) / 2

    on_plane = np.abs(Xw[:, 1]) < 1e-9
    if not known_K:
        if on_plane.sum() < 4:
            raise ValueError("Need >= 4 landmarks on the belt plane (Y=0) to estimate focal length.")
        Hm, _ = cv2.findHomography(Xw[on_plane][:, [0, 2]], uv[on_plane], 0)
        f = focal_from_homography(Hm, cx, cy)
        K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], float)
    K = np.asarray(K, float)

    # Initial pose
    flag = cv2.SOLVEPNP_IPPE if (np.all(on_plane) and len(Xw) >= 4) else cv2.SOLVEPNP_ITERATIVE
    if flag == cv2.SOLVEPNP_ITERATIVE and len(Xw) < 6:
        # use only planar points for the initial guess
        ok, rvec, tvec = cv2.solvePnP(Xw[on_plane], uv[on_plane], K, dist, flags=cv2.SOLVEPNP_IPPE)
    else:
        ok, rvec, tvec = cv2.solvePnP(Xw, uv, K, dist, flags=flag)
    if not ok:
        raise RuntimeError("solvePnP failed")
    rvec, tvec = rvec.ravel(), tvec.ravel()

    # Non-linear refinement of pose (+ focal length)
    def unpack(p):
        rv, tv = p[:3], p[3:6]
        KK = K.copy()
        if refine_focal:
            KK[0, 0] = KK[1, 1] = p[6]
        return rv, tv, KK

    def resid(p):
        rv, tv, KK = unpack(p)
        proj, _ = cv2.projectPoints(Xw.reshape(-1, 1, 3), rv, tv, KK, dist)
        return (proj.reshape(-1, 2) - uv).ravel()

    p0 = np.r_[rvec, tvec, [K[0, 0]] if refine_focal else []]
    sol = least_squares(resid, p0, method="lm" if len(p0) <= 2 * len(Xw) else "trf")
    rv, tv, K = unpack(sol.x)
    R = cv2.Rodrigues(rv)[0]
    cam = Camera(K=K, dist=dist, R=R, t=tv, image_size=(W_img, H_img))

    err = np.linalg.norm(resid(sol.x).reshape(-1, 2), axis=1)
    C = cam.center
    report = {
        "reprojection_error_px": {lm.name: float(e) for lm, e in zip(landmarks, err)},
        "rms_px": float(np.sqrt(np.mean(err ** 2))),
        "focal_px": float(K[0, 0]),
        "focal_estimated": not known_K,
        "camera_center_m": C.tolist(),
        "camera_height_m": float(C[1]),
        "n_landmarks": len(landmarks),
    }
    if not known_K and len(landmarks) <= 4:
        report["warning"] = ("Focal length estimated from only 4 coplanar points: ok for a "
                             "rough calibration, but add an off-plane landmark (e.g. handrail "
                             "height) or a checkerboard intrinsics file for best accuracy.")
    cam.meta = {"report": report}
    return cam, report


# ----------------------------------------------------------------------- files
def save_calibration(path: str | Path, cam: Camera, landmarks: list[Landmark], report: dict,
                     extra: dict | None = None) -> None:
    d = {
        "camera": cam.to_dict(),
        "landmarks": [{"name": lm.name, "world": lm.world.tolist(), "pixel": lm.pixel.tolist()}
                      for lm in landmarks],
        "report": report,
        "world_frame": "origin=belt centre; +X forward (subject faces); +Y up; +Z subject's right",
    }
    if extra:
        d.update(extra)
    Path(path).write_text(json.dumps(d, indent=2))


def load_landmarks(path: str | Path) -> tuple[list[Landmark], dict]:
    d = json.loads(Path(path).read_text())
    lms = [Landmark(x["name"], np.array(x["world"], float), np.array(x["pixel"], float))
           for x in d["landmarks"]]
    return lms, d


def load_intrinsics(path: str | Path) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    d = json.loads(Path(path).read_text())
    return np.array(d["K"], float), np.array(d["dist"], float).ravel(), tuple(d["image_size"])


def calibrate_intrinsics_checkerboard(frames, pattern=(9, 6), square=0.025):
    """Standard OpenCV checkerboard calibration. ``frames`` is an iterable of BGR images.
    ``pattern`` = inner corners (cols, rows). Returns (K, dist, image_size, rms)."""
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square
    objpts, imgpts, size = [], [], None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
    for img in frames:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        ok, corners = cv2.findChessboardCorners(gray, pattern, None)
        if ok:
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
            objpts.append(objp)
            imgpts.append(corners)
    if len(objpts) < 8:
        raise RuntimeError(f"Only {len(objpts)} usable checkerboard views; need >= 8.")
    rms, K, dist, _, _ = cv2.calibrateCamera(objpts, imgpts, size, None, None)
    return K, dist.ravel(), size, rms
