import numpy as np

from humotech.calibration import Landmark, belt_corner_world, solve_camera
from humotech.calibration.solve import focal_from_homography
from humotech.synth.gait_generator import GaitParams, default_camera


def test_focal_and_pose_from_belt_corners(session, calibrated):
    cam, rep = calibrated
    assert abs(cam.K[0, 0] - session.cam.K[0, 0]) / session.cam.K[0, 0] < 0.03
    assert np.linalg.norm(cam.center - session.cam.center) < 0.05
    assert rep["rms_px"] < 2


def test_exact_corners_recover_camera_exactly():
    cam0 = default_camera(GaitParams())
    lms = [Landmark(n, w, cam0.project(w[None])[0]) for n, w in belt_corner_world(1.6, 0.5).items()]
    cam, rep = solve_camera(lms, cam0.image_size)
    assert abs(cam.K[0, 0] - cam0.K[0, 0]) < 1.0
    assert np.allclose(cam.R, cam0.R, atol=1e-4)
    assert rep["rms_px"] < 1e-3


def test_known_intrinsics_and_off_plane_landmark():
    cam0 = default_camera(GaitParams())
    rng = np.random.default_rng(1)
    world = belt_corner_world(1.6, 0.5)
    world["rail_front_left_top"] = np.array([0.8, 1.0, -0.4])  # e.g. handrail at a measured height
    lms = [Landmark(n, w, cam0.project(w[None])[0] + rng.normal(size=2) * 0.5) for n, w in world.items()]
    cam, _ = solve_camera(lms, cam0.image_size, K=cam0.K)
    assert np.linalg.norm(cam.center - cam0.center) < 0.03


def test_pixel_to_plane_roundtrip(calibrated):
    cam, _ = calibrated
    X = np.array([[0.3, 0.0, 0.1], [-0.5, 0.05, -0.2], [0.0, 0.02, 0.0]])
    for x in X:
        back = cam.pixel_to_plane_y(cam.project(x[None]), x[1])[0]
        assert np.allclose(back, x, atol=1e-6)
        back = cam.pixel_to_plane_z(cam.project(x[None]), x[2])[0]
        assert np.allclose(back, x, atol=1e-6)


def test_focal_from_homography_direct():
    cam0 = default_camera(GaitParams())
    import cv2
    w = np.array(list(belt_corner_world(1.6, 0.5).values()))
    H, _ = cv2.findHomography(w[:, [0, 2]], cam0.project(w))
    f = focal_from_homography(H, cam0.K[0, 2], cam0.K[1, 2])
    assert abs(f - cam0.K[0, 0]) < 0.5
