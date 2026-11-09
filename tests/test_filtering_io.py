import numpy as np

from humotech.io.data import Keypoints2D, read_trc, write_trc
from humotech.keypoints import IDX, coco17_to_halpe26
from humotech.pose2d.filtering import butter_lowpass, clean_keypoints, fix_left_right_swaps, fill_gaps


def test_left_right_swap_fix(session):
    kp = session.k2d.kp.copy()
    swapped = [100, 101, 102, 300]
    pairs = [("LKnee", "RKnee"), ("LAnkle", "RAnkle"), ("LHeel", "RHeel"), ("LBigToe", "RBigToe"),
             ("LSmallToe", "RSmallToe"), ("LHip", "RHip")]
    for f in swapped:
        for a, b in pairs:
            kp[f, [IDX[a], IDX[b]]] = kp[f, [IDX[b], IDX[a]]]
    fixed, mask = fix_left_right_swaps(kp)
    assert set(np.flatnonzero(mask)) >= set(swapped)
    assert np.allclose(fixed[swapped], session.k2d.kp[swapped])


def test_gap_fill_and_filter():
    t = np.linspace(0, 2 * np.pi, 200)
    x = np.sin(t)
    valid = np.ones(200, bool)
    valid[50:55] = False
    y = x.copy()
    y[~valid] = np.nan
    f = fill_gaps(y, valid, 10)
    assert np.allclose(f[50:55], x[50:55], atol=1e-3)
    z = butter_lowpass(x + 0.01 * np.random.default_rng(0).normal(size=200), 100, 5)
    assert np.abs(z - x).max() < 0.02


def test_clean_keypoints_shapes(session):
    k = clean_keypoints(session.k2d)
    assert k.kp.shape == session.k2d.kp.shape


def test_trc_roundtrip(tmp_path, session):
    names = ["RHeel", "LHeel", "Hip"]
    X = session.X[:50, [IDX[n] for n in names]]
    X[3, 1] = np.nan
    p = tmp_path / "m.trc"
    write_trc(p, X, names, 60)
    Y, n2, t = read_trc(p)
    assert n2 == names and np.allclose(t[1], 1 / 60, atol=1e-5)
    assert np.allclose(np.nan_to_num(Y), np.nan_to_num(X), atol=1e-6)


def test_keypoints_npz_roundtrip(tmp_path, session):
    p = tmp_path / "k.npz"
    session.k2d.save(p)
    k = Keypoints2D.load(p)
    assert np.allclose(k.kp, session.k2d.kp) and k.fps == session.k2d.fps


def test_coco_mapping():
    kp = np.random.default_rng(0).random((5, 17, 3))
    h = coco17_to_halpe26(kp)
    assert h.shape == (5, 26, 3)
    assert np.allclose(h[:, IDX["Hip"], :2], 0.5 * (kp[:, 11, :2] + kp[:, 12, :2]))
    assert np.all(h[:, IDX["LHeel"], 2] == 0)
