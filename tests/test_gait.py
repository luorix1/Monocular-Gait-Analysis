
from humotech.gait.analysis import analyze_2d, analyze_3d, compare_events
from humotech.gait.belt_speed import belt_speed_from_2d
from humotech.gait.events import detect_events_velocity, dominant_period
from humotech.keypoints import IDX
from humotech.pose2d.filtering import clean_keypoints


def test_belt_speed_exact_from_ground_truth_3d(session):
    r = analyze_3d(session.X, session.params.fps)
    assert abs(r["belt_speed"]["belt_speed"] - session.gt["belt_speed"]) < 0.005


def test_zeni_events_and_temporal_params(session):
    r = analyze_3d(session.X, session.params.fps)
    cmp = compare_events(r["events"], session.gt, session.params.fps)
    # Zeni has a known method bias of a few frames; it must still find every event
    assert cmp["hs"]["missed"] <= 2 and cmp["to"]["missed"] <= 2
    assert cmp["hs"]["mae_ms"] < 60 and cmp["to"]["mae_ms"] < 70
    s = r["summary"]
    assert abs(s["stride_time"]["mean"] - session.gt["stride_time"]) < 0.005
    assert abs(s["cadence_steps_per_min"] - session.gt["cadence"]) < 0.5
    assert abs(s["stride_length"]["mean"] - session.gt["stride_length"]) / session.gt["stride_length"] < 0.02
    assert abs(s["step_width"]["mean"] - session.gt["step_width"]) < 0.01


def test_velocity_events(session):
    X, fps = session.X, session.params.fps
    heel = {s: X[:, IDX[s + "Heel"]] for s in "LR"}
    toe = {s: X[:, IDX[s + "BigToe"]] for s in "LR"}
    ev = detect_events_velocity(heel, toe, fps, session.gt["belt_speed"], frac=0.9)
    cmp = compare_events(ev, session.gt, fps)
    assert cmp["hs"]["mae_ms"] < 25 and cmp["to"]["mae_ms"] < 25


def test_dominant_period(session):
    x = session.X[:, IDX["RHeel"], 0]
    assert abs(dominant_period(x, session.params.fps) - session.gt["stride_time"]) < 0.02


def test_2d_only_belt_speed_and_strides(session, calibrated):
    cam, _ = calibrated
    k = clean_keypoints(session.k2d)
    r = analyze_2d(k.uv, cam, session.params.fps, k.conf)
    v = r["belt_speed"]["belt_speed"]
    assert abs(v - session.gt["belt_speed"]) / session.gt["belt_speed"] < 0.03
    assert abs(r["summary"]["stride_time"]["mean"] - session.gt["stride_time"]) < 0.01


def test_plane_height_matters(session, calibrated):
    """Back-projecting an above-belt keypoint to Y=0 biases speed (documented pitfall)."""
    cam, _ = calibrated
    k = clean_keypoints(session.k2d)
    ev = analyze_2d(k.uv, cam, session.params.fps)["events"]
    right = belt_speed_from_2d(k.uv, cam, ev, session.params.fps, points=("ankle",))["belt_speed"]
    wrong = belt_speed_from_2d(k.uv, cam, ev, session.params.fps, points=("ankle",),
                               heights={"ankle": 0.0})["belt_speed"]
    gt = session.gt["belt_speed"]
    assert abs(right - gt) < abs(wrong - gt)
