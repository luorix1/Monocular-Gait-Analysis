"""Keypoint definitions.

The canonical keypoint set for the whole pipeline is **Halpe-26** (body + feet),
which is what RTMPose "BodyWithFeet" outputs and what the vendored OpenSim
marker set (``opensim/Markers_Halpe26.xml``, from Pose2Sim) expects.
Its first 17 entries are identical to COCO-17, so COCO-only detectors (YOLO-pose)
map in directly; the feet are then simply missing (confidence 0).
"""
from __future__ import annotations

import numpy as np

HALPE26 = [
    "Nose", "LEye", "REye", "LEar", "REar",
    "LShoulder", "RShoulder", "LElbow", "RElbow", "LWrist", "RWrist",
    "LHip", "RHip", "LKnee", "RKnee", "LAnkle", "RAnkle",
    "Head", "Neck", "Hip",
    "LBigToe", "RBigToe", "LSmallToe", "RSmallToe", "LHeel", "RHeel",
]
IDX = {n: i for i, n in enumerate(HALPE26)}
NUM_KP = len(HALPE26)

# Keypoints that also exist as markers on the OpenSim model (eyes/ears do not).
OPENSIM_MARKERS = [n for n in HALPE26 if n not in ("LEye", "REye", "LEar", "REar")]

# Left/right pairs (used for L/R swap correction and symmetric bone lengths).
LR_PAIRS = [
    ("LEye", "REye"), ("LEar", "REar"), ("LShoulder", "RShoulder"),
    ("LElbow", "RElbow"), ("LWrist", "RWrist"), ("LHip", "RHip"),
    ("LKnee", "RKnee"), ("LAnkle", "RAnkle"), ("LBigToe", "RBigToe"),
    ("LSmallToe", "RSmallToe"), ("LHeel", "RHeel"),
]

# Rigid "bones" used to constrain the monocular 3D refinement (constant length).
BONES = [
    ("LHip", "RHip"), ("LShoulder", "RShoulder"),
    ("LShoulder", "LHip"), ("RShoulder", "RHip"),
    ("LHip", "LKnee"), ("LKnee", "LAnkle"),
    ("RHip", "RKnee"), ("RKnee", "RAnkle"),
    ("LAnkle", "LHeel"), ("LAnkle", "LBigToe"), ("LAnkle", "LSmallToe"), ("LHeel", "LBigToe"),
    ("RAnkle", "RHeel"), ("RAnkle", "RBigToe"), ("RAnkle", "RSmallToe"), ("RHeel", "RBigToe"),
    ("LShoulder", "LElbow"), ("LElbow", "LWrist"),
    ("RShoulder", "RElbow"), ("RElbow", "RWrist"),
    ("Neck", "Head"), ("Neck", "Nose"),
]

# Mirror bone pairs that should share a length.
SYMMETRIC_BONES = [
    (("LHip", "LKnee"), ("RHip", "RKnee")),
    (("LKnee", "LAnkle"), ("RKnee", "RAnkle")),
    (("LAnkle", "LHeel"), ("RAnkle", "RHeel")),
    (("LAnkle", "LBigToe"), ("RAnkle", "RBigToe")),
    (("LAnkle", "LSmallToe"), ("RAnkle", "RSmallToe")),
    (("LHeel", "LBigToe"), ("RHeel", "RBigToe")),
    (("LShoulder", "LElbow"), ("RShoulder", "RElbow")),
    (("LElbow", "LWrist"), ("RElbow", "RWrist")),
    (("LShoulder", "LHip"), ("RShoulder", "RHip")),
]

FOOT = {
    "L": {"heel": "LHeel", "toe": "LBigToe", "toe2": "LSmallToe", "ankle": "LAnkle"},
    "R": {"heel": "RHeel", "toe": "RBigToe", "toe2": "RSmallToe", "ankle": "RAnkle"},
}

LEFT = [n for n in HALPE26 if n.startswith("L")]
RIGHT = [n for n in HALPE26 if n.startswith("R")]


def idx(*names: str) -> list[int]:
    return [IDX[n] for n in names]


def coco17_to_halpe26(kp: np.ndarray) -> np.ndarray:
    """(T, 17, C) COCO keypoints -> (T, 26, C) Halpe-26; derived Head/Neck/Hip, feet missing."""
    T, _, C = kp.shape
    out = np.zeros((T, NUM_KP, C), dtype=float)
    out[:, :17] = kp
    def mid(a, b):
        m = 0.5 * (kp[:, a] + kp[:, b])
        if C == 3:  # confidence = min of the two
            m[:, 2] = np.minimum(kp[:, a, 2], kp[:, b, 2])
        return m
    out[:, IDX["Neck"]] = mid(5, 6)
    out[:, IDX["Hip"]] = mid(11, 12)
    out[:, IDX["Head"]] = mid(3, 4)  # ear midpoint as a rough head-top proxy
    return out
