"""CPU-only 3D initialisation from 2D keypoints + calibration (no neural lifter).

Each keypoint is back-projected onto a vertical sagittal plane Z = z_j chosen from body
geometry (left limbs at -w, right limbs at +w, midline at 0, in the treadmill frame where
+Z is the subject's right). For a roughly side-on camera this is already a decent 3D
skeleton; the treadmill-constrained refinement (``refine.py``) then fixes bone lengths,
depth and foot contact. On Ubuntu, GVHMR/WHAM provide a better initial pose.
"""
from __future__ import annotations

import numpy as np

from ..calibration.camera import Camera
from ..io.data import Keypoints2D, Keypoints3D
from ..keypoints import HALPE26

# lateral offsets (m) as a fraction of body height
_LAT = {
    "Hip": 0.052, "Knee": 0.050, "Ankle": 0.040, "Heel": 0.040, "BigToe": 0.030, "SmallToe": 0.055,
    "Shoulder": 0.105, "Elbow": 0.12, "Wrist": 0.12, "Eye": 0.018, "Ear": 0.043,
}


def lateral_offsets(height: float = 1.75) -> np.ndarray:
    z = np.zeros(len(HALPE26))
    for i, n in enumerate(HALPE26):
        side, base = n[0], n[1:]
        if side in "LR" and base in _LAT:
            z[i] = (-1 if side == "L" else 1) * _LAT[base] * height
    return z


def planar_init(k2d: Keypoints2D, cam: Camera, height: float = 1.75) -> Keypoints3D:
    z = lateral_offsets(height)
    X = cam.pixel_to_plane_z(k2d.uv, z[None, :])
    conf = k2d.conf.copy()
    bad = ~np.isfinite(X).all(-1)
    conf[bad] = 0
    return Keypoints3D(X, conf, k2d.fps, list(k2d.names), meta={"lifter": "planar", "height": height})


def place_root_relative(rel_cam: np.ndarray, k2d: Keypoints2D, cam: Camera,
                        root_name: str = "Hip") -> Keypoints3D:
    """Place root-relative joints from a neural lifter into the treadmill frame.

    rel_cam : (T, 26, 3) joints relative to the pelvis, expressed in the *camera* frame
              (OpenCV axes), e.g. SMPL joints from GVHMR/WHAM "incam" output minus pelvis.
    The global rotation comes from the calibrated camera (R^T); the root position is the
    back-projection of the 2D pelvis onto the treadmill mid-sagittal plane (Z = 0).
    Monocular depth/scale is then corrected by the refinement step.
    """
    ri = HALPE26.index(root_name)
    rel_w = rel_cam @ cam.R  # camera -> world rotation (R^T applied to row vectors)
    root = cam.pixel_to_plane_z(k2d.uv[:, ri], 0.0)
    X = root[:, None, :] + rel_w
    return Keypoints3D(X, k2d.conf.copy(), k2d.fps, list(k2d.names), meta={"lifter": "root_relative"})
