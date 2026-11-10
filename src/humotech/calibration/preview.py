"""Calibration preview image: belt grid, 1 m posts at the corners and the treadmill axes,
projected with the solved camera onto the calibration frame."""
from __future__ import annotations

import numpy as np

from .camera import Camera


def draw_calibration_preview(frame: np.ndarray, cam: Camera, belt_length: float, belt_width: float) -> np.ndarray:
    """Return a copy of ``frame`` (BGR) with a 0.1 m belt grid (orange), 1 m vertical posts at the
    belt corners (green) and the X (red) / Y (green) / Z (blue) axes drawn on it."""
    import cv2

    L, W = belt_length, belt_width
    img = frame.copy()
    th = max(1, round(max(img.shape[:2]) / 1200))
    for x in np.arange(-L / 2, L / 2 + 1e-6, 0.1):
        p = cam.project(np.array([[x, 0, -W / 2], [x, 0, W / 2]])).astype(int)
        cv2.line(img, tuple(p[0]), tuple(p[1]), (0, 200, 255), th)
    for sx in (-1, 1):
        for sz in (-1, 1):
            p = cam.project(np.array([[sx * L / 2, 0, sz * W / 2], [sx * L / 2, 1.0, sz * W / 2]])).astype(int)
            cv2.line(img, tuple(p[0]), tuple(p[1]), (0, 255, 0), 2 * th)
    o = cam.project(np.array([[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0], [0, 0, 0.3]])).astype(int)
    for k, c in zip(range(1, 4), [(0, 0, 255), (0, 255, 0), (255, 0, 0)]):
        cv2.arrowedLine(img, tuple(o[0]), tuple(o[k]), c, 2 * th)
    return img
