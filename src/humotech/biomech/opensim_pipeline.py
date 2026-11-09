"""OpenSim stage: Halpe-26 markers -> scaled musculoskeletal model -> inverse kinematics.

Uses the Pose2Sim full-body model + Halpe-26 marker set (vendored in ``opensim_models/``,
BSD-3, Pagnon et al.). IK through the model is what turns free-floating keypoints into
anatomically consistent joint angles (fixed segment lengths, physiological joint axes
and ranges). The treadmill frame == OpenSim ground frame (X forward, Y up, Z right).

Scaling: walking trials make OpenSim's measurement-based ScaleTool unreliable (it averages
marker positions over the time range), so we compute one uniform scale factor per body
from the *median segment lengths* of the refined 3D keypoints, and apply them with
``Model.scale``. A static standing trial can be used instead if recorded.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..io.data import Keypoints3D, read_mot, write_trc
from ..keypoints import IDX, OPENSIM_MARKERS

OPENSIM_DIR = Path(os.environ.get("HUMOTECH_OPENSIM_DIR", Path(__file__).resolve().parents[3] / "opensim_models"))
MODEL = "Model_Pose2Sim_simple.osim"
MARKERS = "Markers_Halpe26.xml"
IK_SETUP = "IK_Setup_Pose2Sim_Halpe26.xml"

# body -> marker pairs whose length ratio (subject / model) gives the body's scale factor
SCALE_PAIRS = {
    "pelvis": [("LHip", "RHip")],
    "sacrum": [("LHip", "RHip")],
    "femur_r": [("RHip", "RKnee")], "femur_l": [("LHip", "LKnee")],
    "tibia_r": [("RKnee", "RAnkle")], "tibia_l": [("LKnee", "LAnkle")],
    "talus_r": [("RHeel", "RBigToe")], "calcn_r": [("RHeel", "RBigToe")], "toes_r": [("RHeel", "RBigToe")],
    "talus_l": [("LHeel", "LBigToe")], "calcn_l": [("LHeel", "LBigToe")], "toes_l": [("LHeel", "LBigToe")],
    "torso": [("RShoulder", "RHip"), ("LShoulder", "LHip")],
    "head": [("RShoulder", "RHip"), ("LShoulder", "LHip")],
    "humerus_r": [("RShoulder", "RElbow")], "humerus_l": [("LShoulder", "LElbow")],
    "ulna_r": [("RElbow", "RWrist")], "radius_r": [("RElbow", "RWrist")], "hand_r": [("RElbow", "RWrist")],
    "ulna_l": [("LElbow", "LWrist")], "radius_l": [("LElbow", "LWrist")], "hand_l": [("LElbow", "LWrist")],
}
# pairs averaged across sides (symmetric scaling is more robust with a far-side leg)
SYMMETRIC = True


def _osim():
    try:
        import opensim as osim
    except ImportError as e:  # pragma: no cover
        raise ImportError("OpenSim python bindings missing: conda install -c opensim-org opensim") from e
    # missing .vtp geometry is only a visualisation issue; keep logs readable
    osim.Logger.setLevelString(os.environ.get("HUMOTECH_OPENSIM_LOG", "error"))
    if (OPENSIM_DIR / "Geometry").is_dir():
        osim.ModelVisualizer.addDirToGeometrySearchPaths(str(OPENSIM_DIR / "Geometry"))
    return osim


def model_with_markers(out_path: str | Path) -> Path:
    osim = _osim()
    model = osim.Model(str(OPENSIM_DIR / MODEL))
    model.set_MarkerSet(osim.MarkerSet(str(OPENSIM_DIR / MARKERS)))
    model.finalizeConnections()
    model.initSystem()
    model.printToXML(str(out_path))
    return Path(out_path)


def model_marker_positions(model, state=None) -> dict[str, np.ndarray]:
    if state is None:
        state = model.initSystem()
    model.realizePosition(state)
    ms = model.getMarkerSet()
    return {ms.get(i).getName(): np.array(ms.get(i).getLocationInGround(state).to_numpy())
            for i in range(ms.getSize())}


def segment_lengths(k3d: Keypoints3D) -> dict[tuple[str, str], float]:
    X = k3d.X
    pairs = {p for v in SCALE_PAIRS.values() for p in v}
    return {(a, b): float(np.nanmedian(np.linalg.norm(X[:, IDX[a]] - X[:, IDX[b]], axis=-1))) for a, b in pairs}


def compute_scale_factors(k3d: Keypoints3D, model_markers: dict[str, np.ndarray]) -> dict[str, float]:
    subj = segment_lengths(k3d)
    ratio = {p: subj[p] / np.linalg.norm(model_markers[p[0]] - model_markers[p[1]]) for p in subj}
    if SYMMETRIC:
        sym = {}
        for (a, b), r in ratio.items():
            mirror = (_mirror(a), _mirror(b))
            sym[(a, b)] = 0.5 * (r + ratio.get(mirror, r))
        ratio = sym
    return {body: float(np.mean([ratio[p] for p in pairs])) for body, pairs in SCALE_PAIRS.items()}


def _mirror(n: str) -> str:
    return ("R" + n[1:]) if n.startswith("L") else ("L" + n[1:]) if n.startswith("R") else n


def scale_model(k3d: Keypoints3D, mass: float, out_path: str | Path, base_model: str | Path | None = None
                ) -> tuple[Path, dict]:
    osim = _osim()
    base = Path(base_model) if base_model else model_with_markers(Path(out_path).with_name("model_markers.osim"))
    model = osim.Model(str(base))
    state = model.initSystem()
    factors = compute_scale_factors(k3d, model_marker_positions(model, state))
    ss = osim.ScaleSet()
    for body, f in factors.items():
        if not model.getBodySet().contains(body):
            continue
        sc = osim.Scale()
        sc.setSegmentName(body)
        sc.setScaleFactors(osim.Vec3(f, f, f))
        sc.setApply(True)
        ss.cloneAndAppend(sc)
    model.scale(state, ss, True, float(mass))
    model.setName(Path(out_path).stem)
    model.printToXML(str(out_path))
    return Path(out_path), factors


def write_markers_trc(k3d: Keypoints3D, path: str | Path) -> Path:
    names = OPENSIM_MARKERS
    X = k3d.X[:, [IDX[n] for n in names]]
    write_trc(path, X, names, k3d.fps)
    return Path(path)


def run_ik(model_path: str | Path, trc_path: str | Path, out_mot: str | Path,
           setup: str | Path | None = None, accuracy: float = 1e-5) -> Path:
    osim = _osim()
    ik = osim.InverseKinematicsTool(str(setup or OPENSIM_DIR / IK_SETUP))
    model = osim.Model(str(model_path))
    ik.setModel(model)
    ik.set_model_file(str(model_path))
    ik.setMarkerDataFileName(str(trc_path))
    tbl = osim.TimeSeriesTableVec3(str(trc_path))
    times = tbl.getIndependentColumn()
    ik.setStartTime(times[0])
    ik.setEndTime(times[-1])
    ik.setOutputMotionFileName(str(out_mot))
    ik.set_accuracy(accuracy)
    ik.set_report_errors(True)
    ik.setResultsDir(str(Path(out_mot).parent))
    ik.run()
    return Path(out_mot)


def markers_from_ik(model_path: str | Path, mot_path: str | Path, names: list[str] | None = None
                    ) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Forward kinematics: model marker trajectories (T, M, 3) implied by the IK solution."""
    osim = _osim()
    model = osim.Model(str(model_path))
    state = model.initSystem()
    df = read_mot(mot_path)
    cs = model.getCoordinateSet()
    names = names or [model.getMarkerSet().get(i).getName() for i in range(model.getMarkerSet().getSize())]
    mk = [model.getMarkerSet().get(n) for n in names]
    coords = []
    for c in df.columns[1:]:
        if cs.contains(c):
            co = cs.get(c)
            rot = co.getMotionType() == 1  # Rotational
            coords.append((co, c, rot))
    X = np.zeros((len(df), len(names), 3))
    for i in range(len(df)):
        row = df.iloc[i]
        for co, c, rot in coords:
            co.setValue(state, np.deg2rad(row[c]) if rot else row[c], False)
        model.realizePosition(state)
        for j, m in enumerate(mk):
            X[i, j] = m.getLocationInGround(state).to_numpy()
    return X, names, df["time"].to_numpy()


def ik_to_keypoints3d(model_path, mot_path, fps: float) -> Keypoints3D:
    """Model-marker trajectories after IK, in Halpe-26 layout (eyes/ears = NaN)."""
    from ..keypoints import HALPE26
    Xm, names, _ = markers_from_ik(model_path, mot_path, OPENSIM_MARKERS)
    X = np.full((len(Xm), len(HALPE26), 3), np.nan)
    for j, n in enumerate(names):
        X[:, IDX[n]] = Xm[:, j]
    conf = np.isfinite(X).all(-1).astype(float)
    return Keypoints3D(X, conf, fps, meta={"source": "opensim_ik", "model": str(model_path), "mot": str(mot_path)})


def ik_errors(results_dir: str | Path) -> pd.DataFrame | None:
    p = next(Path(results_dir).glob("*_ik_marker_errors.sto"), None)
    return read_mot(p) if p else None
