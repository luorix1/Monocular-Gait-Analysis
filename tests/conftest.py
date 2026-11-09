import pytest

from humotech.calibration import solve_camera
from humotech.synth.gait_generator import make_session


@pytest.fixture(scope="session")
def session():
    return make_session(seed=0)


@pytest.fixture(scope="session")
def calibrated(session):
    cam, rep = solve_camera(session.landmarks, session.cam.image_size)
    return cam, rep


def has(mod, attr=None):
    try:
        m = __import__(mod)
        return attr is None or hasattr(m, attr)
    except Exception:
        return False


requires_torch = pytest.mark.skipif(not has("torch"), reason="PyTorch not installed")
requires_opensim = pytest.mark.skipif(not has("opensim", "Model"), reason="OpenSim not installed (conda)")
