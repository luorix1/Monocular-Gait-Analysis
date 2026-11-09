"""Synthetic treadmill walking with exact ground truth.

Used for unit/integration tests and for checking the pipeline on machines without video
or GPU. Feet are planted on the moving belt during stance (AP velocity exactly -v), so
belt-speed, event and stride-length estimators can be checked against known values.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..calibration.camera import Camera, look_at
from ..calibration.solve import Landmark, belt_corner_world
from ..io.data import Keypoints2D, Keypoints3D
from ..keypoints import IDX, NUM_KP


@dataclass
class GaitParams:
    height: float = 1.75
    belt_speed: float = 1.2
    stride_time: float = 1.1
    duty: float = 0.62              # stance fraction
    foot_half_width: float = 0.065  # lateral foot offset from midline (step width = 2x)
    clearance: float = 0.05
    duration: float = 12.0
    fps: float = 60.0
    belt_length: float = 1.6
    belt_width: float = 0.5
    drift_amp: float = 0.03         # slow AP drift of the subject on the belt (m)
    swing_end_vel_frac: float = 0.5 # terminal-swing foot retraction speed as a fraction of belt speed


@dataclass
class SyntheticSession:
    params: GaitParams
    X: np.ndarray                   # (T, 26, 3) ground-truth keypoints, treadmill frame
    cam: Camera
    k2d: Keypoints2D
    landmarks: list[Landmark]
    gt: dict = field(default_factory=dict)

    @property
    def k3d(self) -> Keypoints3D:
        return Keypoints3D(self.X, np.ones(self.X.shape[:2]), self.params.fps, meta={"source": "synthetic_gt"})


def _min_jerk(s):
    return 10 * s ** 3 - 15 * s ** 4 + 6 * s ** 5


def _hermite5(s, p0, p1, d0, d1):
    """Quintic Hermite with end positions p0,p1, end derivatives d0,d1 (w.r.t. s), zero accel."""
    h0 = 1 - 10 * s ** 3 + 15 * s ** 4 - 6 * s ** 5
    h1 = s - 6 * s ** 3 + 8 * s ** 4 - 3 * s ** 5
    h3 = -4 * s ** 3 + 7 * s ** 4 - 3 * s ** 5
    return h0 * p0 + h1 * d0 + (1 - h0) * p1 + h3 * d1


def _two_link(H, A, L1, L2, fwd=np.array([1.0, 0, 0])):
    d = np.linalg.norm(A - H, axis=-1, keepdims=True)
    d = np.minimum(d, 0.999 * (L1 + L2))
    u = (A - H) / np.linalg.norm(A - H, axis=-1, keepdims=True)
    a = (L1 ** 2 - L2 ** 2 + d ** 2) / (2 * d)
    h = np.sqrt(np.maximum(L1 ** 2 - a ** 2, 0))
    p = fwd - (u @ fwd)[:, None] * u
    p /= np.linalg.norm(p, axis=-1, keepdims=True)
    return H + a * u + h * p


def generate_kinematics(p: GaitParams) -> tuple[np.ndarray, dict]:
    Hh = p.height
    L1, L2 = 0.245 * Hh, 0.246 * Hh
    ha = 0.039 * Hh
    T_n = int(round(p.duration * p.fps))
    t = np.arange(T_n) / p.fps
    X = np.zeros((T_n, NUM_KP, 3))
    st = p.duty * p.stride_time
    x_hs = p.belt_speed * st / 2
    drift = p.drift_amp * np.sin(2 * np.pi * t / 7.0)

    max_dx = x_hs + p.drift_amp + 0.02
    y0 = ha + np.sqrt((0.985 * (L1 + L2)) ** 2 - max_dx ** 2)  # near-straight leg at HS
    pelvis = np.stack([drift + 0.01 * np.sin(4 * np.pi * t / p.stride_time),
                       y0 + 0.012 * np.cos(4 * np.pi * t / p.stride_time),
                       0.015 * np.sin(2 * np.pi * t / p.stride_time)], -1)

    gt = {"hs": {}, "to": {}}
    for side, sgn, off in (("R", +1, 0.0), ("L", -1, 0.5)):
        phi = (t / p.stride_time + off) % 1.0
        kk = np.floor(t / p.stride_time + off)
        t_k = (kk - off) * p.stride_time                      # time of this stride's HS
        X_k = x_hs + p.drift_amp * np.sin(2 * np.pi * t_k / 7.0)            # footprint x at HS
        X_k1 = x_hs + p.drift_amp * np.sin(2 * np.pi * (t_k + p.stride_time) / 7.0)
        x_to_k = X_k - p.belt_speed * st
        # stance: planted on the belt (exactly -v); swing: quintic Hermite to the next footprint
        # with velocity -v at both ends (velocity-continuous, like real feet)
        sw_ = np.clip((phi - p.duty) / (1 - p.duty), 0, 1)
        D = (1 - p.duty) * p.stride_time
        ax = np.where(phi < p.duty, X_k - p.belt_speed * (t - t_k),
                      _hermite5(sw_, x_to_k, X_k1, -p.belt_speed * D, -p.swing_end_vel_frac * p.belt_speed * D))
        sw = np.clip((phi - p.duty) / (1 - p.duty), 0, 1)
        ay = ha + np.where(phi < p.duty, 0.0, p.clearance * np.sin(np.pi * sw) ** 2)
        # foot pitch: toe-down at early swing, toe-up just before HS
        pitch = np.where(phi < p.duty, 0.0, -0.35 * np.sin(np.pi * sw) * (1 - sw) + 0.25 * np.sin(np.pi * sw) * sw)
        az = sgn * p.foot_half_width + 0 * t
        A = np.stack([ax, ay, az], -1)
        hip = pelvis + np.array([0, -0.0, sgn * 0.09])
        knee = _two_link(hip, A, L1, L2)
        c, s = np.cos(pitch), np.sin(pitch)

        def foot_pt(dx, dy, dz):
            return A + np.stack([c * dx - s * dy, s * dx + c * dy, np.full_like(c, dz)], -1)
        heel = foot_pt(-0.05, -ha + 0.03, 0.0)     # heel keypoint ~3 cm up the shoe
        big = foot_pt(0.14, -ha + 0.02, -sgn * 0.025)
        small = foot_pt(0.12, -ha + 0.02, sgn * 0.035)
        X[:, IDX[f"{side}Hip"]] = hip
        X[:, IDX[f"{side}Knee"]] = knee
        X[:, IDX[f"{side}Ankle"]] = A
        X[:, IDX[f"{side}Heel"]] = heel
        X[:, IDX[f"{side}BigToe"]] = big
        X[:, IDX[f"{side}SmallToe"]] = small
        # arms swing opposite to the ipsilateral leg
        sh = pelvis + np.array([0, 0.30 * Hh, sgn * 0.19])
        ang = 0.35 * np.sin(2 * np.pi * (t / p.stride_time + off) + np.pi / 2) * -1
        ua, fa = 0.186 * Hh, 0.146 * Hh
        el = sh + ua * np.stack([np.sin(ang), -np.cos(ang), 0 * ang], -1)
        wr = el + fa * np.stack([np.sin(ang + 0.3), -np.cos(ang + 0.3), 0 * ang], -1)
        X[:, IDX[f"{side}Shoulder"]] = sh
        X[:, IDX[f"{side}Elbow"]] = el
        X[:, IDX[f"{side}Wrist"]] = wr
        X[:, IDX[f"{side}Eye"]] = pelvis + np.array([0.09, 0.43 * Hh, sgn * 0.03])
        X[:, IDX[f"{side}Ear"]] = pelvis + np.array([0.0, 0.42 * Hh, sgn * 0.075])
        # ground-truth events (frame indices, fractional)
        k = np.arange(-2, int(p.duration / p.stride_time) + 3)
        hs = (k - off) * p.stride_time * p.fps
        to = (k - off + p.duty) * p.stride_time * p.fps
        gt["hs"][side] = hs[(hs >= 0) & (hs < T_n)]
        gt["to"][side] = to[(to >= 0) & (to < T_n)]
    X[:, IDX["Hip"]] = 0.5 * (X[:, IDX["LHip"]] + X[:, IDX["RHip"]])
    X[:, IDX["Neck"]] = 0.5 * (X[:, IDX["LShoulder"]] + X[:, IDX["RShoulder"]]) + [0, 0.04, 0]
    X[:, IDX["Head"]] = pelvis + np.array([0.0, 0.52 * Hh, 0])
    X[:, IDX["Nose"]] = pelvis + np.array([0.11, 0.41 * Hh, 0])
    gt.update(belt_speed=p.belt_speed, stride_time=p.stride_time, stride_length=p.belt_speed * p.stride_time,
              step_length=p.belt_speed * p.stride_time / 2, step_width=2 * p.foot_half_width,
              stance_pct=100 * p.duty, cadence=120 / p.stride_time)
    return X, gt


def default_camera(p: GaitParams, image_size=(1920, 1080), f=1300.0,
                   eye=(0.3, 1.0, 2.8), target=(0.0, 0.8, 0.0)) -> Camera:
    R, tt = look_at(eye, target)
    K = np.array([[f, 0, (image_size[0] - 1) / 2], [0, f, (image_size[1] - 1) / 2], [0, 0, 1]])
    return Camera(K, np.zeros(5), R, tt, image_size)


def make_session(p: GaitParams | None = None, cam: Camera | None = None, noise_px: float = 1.5,
                 far_side_noise_px: float = 3.0, landmark_noise_px: float = 0.5,
                 seed: int = 0) -> SyntheticSession:
    p = p or GaitParams()
    rng = np.random.default_rng(seed)
    X, gt = generate_kinematics(p)
    cam = cam or default_camera(p)
    uv = cam.project(X)
    # far side (left, if the camera is on the subject's right) is noisier
    far = "L" if cam.center[2] > 0 else "R"
    sig = np.full(X.shape[1], noise_px)
    for n, i in IDX.items():
        if n.startswith(far) and n not in ("LEye", "REye", "LEar", "REar"):
            sig[i] = far_side_noise_px
    uv = uv + rng.normal(size=uv.shape) * sig[None, :, None]
    conf = np.where(sig[None] > noise_px, 0.7, 0.9) * np.ones(uv.shape[:2])
    k2d = Keypoints2D(np.concatenate([uv, conf[..., None]], -1), p.fps, cam.image_size,
                      meta={"source": "synthetic"})
    corners = belt_corner_world(p.belt_length, p.belt_width)
    lms = [Landmark(n, w, cam.project(w[None])[0] + rng.normal(size=2) * landmark_noise_px)
           for n, w in corners.items()]
    return SyntheticSession(p, X, cam, k2d, lms, gt)
