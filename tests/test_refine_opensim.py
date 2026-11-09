import numpy as np
import pytest

from conftest import requires_opensim, requires_torch
from humotech.io.data import Keypoints3D
from humotech.keypoints import IDX
from humotech.pose2d.filtering import clean_keypoints


@requires_torch
def test_refine_recovers_from_bad_init(session, calibrated):
    from humotech.lift3d.refine import RefineConfig, refine
    cam, _ = calibrated
    k = clean_keypoints(session.k2d)
    X = session.X.copy()
    pel = X[:, IDX["Hip"]][:, None]
    X = pel + 1.08 * (X - pel)       # 8 % size error (typical monocular)
    X[..., 2] += 0.12                # subject 12 cm off the belt centre line
    init = Keypoints3D(X, np.ones(X.shape[:2]), session.params.fps)
    mpjpe0 = np.linalg.norm(init.X - session.X, axis=-1).mean()
    out, info = refine(k, init, cam, RefineConfig(verbose=False, init_belt_speed=1.0))
    mpjpe = np.linalg.norm(out.X - session.X, axis=-1).mean()
    assert mpjpe < 0.5 * mpjpe0 and mpjpe < 0.06
    assert abs(info["belt_speed"] - session.gt["belt_speed"]) / session.gt["belt_speed"] < 0.03
    assert info["reproj_rmse_px"] < 5


@requires_torch
def test_planar_init_plus_refine(session, calibrated):
    from humotech.lift3d.planar import planar_init
    from humotech.lift3d.refine import RefineConfig, refine
    cam, _ = calibrated
    k = clean_keypoints(session.k2d)
    out, info = refine(k, planar_init(k, cam, 1.75), cam, RefineConfig(verbose=False, iters=300))
    assert np.linalg.norm(out.X - session.X, axis=-1).mean() < 0.04


@requires_opensim
def test_opensim_scale_ik_fk(tmp_path, session):
    from humotech.biomech import opensim_pipeline as op
    from humotech.gait.analysis import analyze_3d
    k3d = session.k3d
    model, factors = op.scale_model(k3d, 70, tmp_path / "scaled.osim")
    assert all(0.6 < f < 1.6 for f in factors.values())
    trc = op.write_markers_trc(k3d, tmp_path / "markers.trc")
    mot = op.run_ik(model, trc, tmp_path / "ik.mot")
    km = op.ik_to_keypoints3d(model, mot, session.params.fps)
    err = np.nanmean(np.linalg.norm(km.X - session.X, axis=-1))
    assert err < 0.05
    r = analyze_3d(km.X, session.params.fps)
    assert abs(r["summary"]["stride_time"]["mean"] - session.gt["stride_time"]) < 0.01
    assert abs(r["belt_speed"]["belt_speed"] - session.gt["belt_speed"]) / session.gt["belt_speed"] < 0.03


@requires_torch
@pytest.mark.slow
def test_full_pipeline_synthetic(tmp_path, session, calibrated):
    from humotech.pipeline import load_config, run_pipeline
    cam, _ = calibrated
    cfg = load_config(overrides={"refine": {"iters": 300}})
    res = run_pipeline(cam, tmp_path / "out", cfg, k2d_raw=session.k2d, log=lambda *a: None)
    s = res["summary"]
    gt = session.gt
    assert abs(s["belt_speed_m_s"] - gt["belt_speed"]) / gt["belt_speed"] < 0.03
    assert abs(s["stride_time"]["mean"] - gt["stride_time"]) < 0.01
    assert abs(s["stride_length"]["mean"] - gt["stride_length"]) / gt["stride_length"] < 0.04
    assert (tmp_path / "out" / "summary.json").exists()
