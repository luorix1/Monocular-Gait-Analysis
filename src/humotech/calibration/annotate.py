"""Minimal OpenCV click tool for marking calibration landmarks on a video frame
(Tracker-style). Will be replaced/augmented by the GUI later.

Controls: left-click = place point · u = undo · s = skip landmark (optional ones) ·
          Enter/Space = accept when all placed · q/Esc = abort
A magnified inset follows the cursor for sub-pixel-ish precision.
"""
from __future__ import annotations

import cv2
import numpy as np


def read_frame(video_path: str, frame_idx: int = 0) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise IOError(f"Could not read frame {frame_idx} from {video_path}")
    return frame


def click_landmarks(image: np.ndarray, names: list[str], optional: set[str] | None = None,
                    window: str = "Humotech Gait Analysis: belt calibration", max_display: int = 1600
                    ) -> dict[str, np.ndarray]:
    optional = optional or set()
    h, w = image.shape[:2]
    scale = min(1.0, max_display / max(h, w))
    disp_base = cv2.resize(image, (int(w * scale), int(h * scale))) if scale < 1 else image.copy()
    pts: dict[str, np.ndarray] = {}
    order: list[str] = []
    cursor = [0, 0]
    i = [0]

    def on_mouse(ev, x, y, flags, param):
        cursor[0], cursor[1] = x, y
        if ev == cv2.EVENT_LBUTTONDOWN and i[0] < len(names):
            pts[names[i[0]]] = np.array([x / scale, y / scale])
            order.append(names[i[0]])
            i[0] += 1

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    while True:
        disp = disp_base.copy()
        for n, p in pts.items():
            q = tuple(int(v) for v in p * scale)
            cv2.drawMarker(disp, q, (0, 255, 0), cv2.MARKER_CROSS, 16, 2)
            cv2.putText(disp, n, (q[0] + 6, q[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        msg = (f"Click: {names[i[0]]}" + (" (optional, 's' to skip)" if names[i[0]] in optional else "")
               if i[0] < len(names) else "All placed - Enter to accept, u to undo")
        cv2.rectangle(disp, (0, 0), (disp.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(disp, msg, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        # magnifier
        cx, cy = int(cursor[0] / scale), int(cursor[1] / scale)
        r, z = 25, 6
        x0, y0 = max(cx - r, 0), max(cy - r, 0)
        crop = image[y0:min(cy + r, h), x0:min(cx + r, w)]
        if crop.size:
            mag = cv2.resize(crop, (crop.shape[1] * z, crop.shape[0] * z), interpolation=cv2.INTER_NEAREST)
            mh, mw = mag.shape[:2]
            cv2.line(mag, (mw // 2, 0), (mw // 2, mh), (0, 0, 255), 1)
            cv2.line(mag, (0, mh // 2), (mw, mh // 2), (0, 0, 255), 1)
            if mh < disp.shape[0] - 40 and mw < disp.shape[1]:
                disp[40:40 + mh, disp.shape[1] - mw:] = mag
        cv2.imshow(window, disp)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord("q"), 27):
            cv2.destroyWindow(window)
            raise KeyboardInterrupt("Calibration aborted")
        if k == ord("u") and order:
            last = order.pop()
            pts.pop(last)
            i[0] = names.index(last)
        if k == ord("s") and i[0] < len(names) and names[i[0]] in optional:
            i[0] += 1
        if k in (13, 32) and i[0] >= len(names):
            break
    cv2.destroyWindow(window)
    return pts
