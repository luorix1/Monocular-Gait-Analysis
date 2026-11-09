"""Treadmill-constrained monocular 3D refinement (PyTorch; CPU or CUDA).

Optimises the whole sequence of 3D keypoints X (T, 26, 3) in the treadmill frame, plus the
(unknown) belt speed v, constant bone lengths and per-point foot "sole heights", so that:

  * reprojection   : X projects onto the 2D keypoints through the *calibrated* camera
                     (confidence-weighted, robust Huber)
  * bones          : segment lengths are constant over time (and L/R symmetric)
  * contact        : during flat-foot stance, heel/toes/ankle move with the belt,
                     velocity = (-v, 0, 0), and heel/toes sit at a constant height above
                     the belt (this is what fixes monocular depth)
  * no penetration : foot points stay above the belt
  * smoothness     : small joint accelerations
  * prior          : weak pull to the initial lift (GVHMR/WHAM/planar)

This mirrors the refinement of OpenCap Monocular (Miller et al. 2026) but replaces its
"stationary foot during contact" term with the moving-belt constraint and uses the measured
treadmill calibration instead of estimated extrinsics. Stance windows come from Zeni events
on the current estimate and are re-detected between rounds.

Each residual is divided by a noise scale (sigma), so weights are interpretable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..calibration.camera import Camera
from ..gait.analysis import analyze_3d
from ..io.data import Keypoints2D, Keypoints3D
from ..keypoints import BONES, FOOT, IDX, SYMMETRIC_BONES


@dataclass
class RefineConfig:
    iters: int = 600
    rounds: int = 2                      # contact re-detection rounds
    lr: float = 0.01
    sigma_px: float = 4.0                # 2D keypoint noise (px)
    huber_px: float = 3.0                # robust threshold in units of sigma
    sigma_bone: float = 0.01             # m
    sigma_contact_vel: float = 0.05      # m/s
    sigma_contact_h: float = 0.01        # m
    sigma_acc: float = 30.0              # m/s^2
    sigma_prior: float = 1.0             # m (weak pull to the initial lift)
    sole_heights: tuple = (0.03, 0.02, 0.02)  # expected heel / big-toe / small-toe keypoint height in stance (m)
    sigma_sole: float = 0.01             # m; keep tight - a free sole height trades off with depth
    w_penetration: float = 100.0
    stance_window: tuple = (0.1, 0.8)    # fraction of stance considered flat-foot
    conf_thr: float = 0.2
    device: str = "cpu"
    verbose: bool = True
    init_belt_speed: float | None = None
    extra: dict = field(default_factory=dict)


def _contact_mask(X: np.ndarray, fps: float, window) -> tuple[np.ndarray, float]:
    """(T, 26) contact weights for foot points, and a belt speed estimate, from Zeni events."""
    res = analyze_3d(X, fps)
    ev = res["events"]
    T = len(X)
    m = np.zeros((T, X.shape[1]))
    for s in ("L", "R"):
        pts = [IDX[FOOT[s][k]] for k in ("heel", "toe", "toe2", "ankle")]
        for h in ev.hs[s]:
            nxt = ev.to[s][ev.to[s] > h]
            if len(nxt):
                d = nxt[0] - h
                a, b = int(np.ceil(h + window[0] * d)), int(np.floor(h + window[1] * d))
                m[max(a, 0):min(b, T - 1) + 1, pts] = 1.0
    return m, res["belt_speed"]["belt_speed"]


def _project_torch(X, K, dist, R, t):
    import torch
    Xc = X @ R.T + t
    z = Xc[..., 2:3].clamp(min=1e-3)
    xy = Xc[..., :2] / z
    k1, k2, p1, p2, k3 = dist
    r2 = (xy ** 2).sum(-1, keepdim=True)
    radial = 1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
    x, y = xy[..., :1], xy[..., 1:]
    xd = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x ** 2)
    yd = y * radial + p1 * (r2 + 2 * y ** 2) + 2 * p2 * x * y
    u = K[0, 0] * xd + K[0, 2]
    v = K[1, 1] * yd + K[1, 2]
    return torch.cat([u, v], -1)


def refine(k2d: Keypoints2D, init: Keypoints3D, cam: Camera, cfg: RefineConfig | None = None
           ) -> tuple[Keypoints3D, dict]:
    import torch
    cfg = cfg or RefineConfig()
    dev = torch.device(cfg.device)
    f32 = dict(dtype=torch.float32, device=dev)
    fps = k2d.fps
    T, J = k2d.kp.shape[:2]

    uv = np.nan_to_num(k2d.uv)
    w2d = np.where((k2d.conf > cfg.conf_thr) & np.isfinite(k2d.uv).all(-1), k2d.conf, 0.0)
    X0 = init.X.copy()
    # fill any missing init points with the pelvis position
    bad = ~np.isfinite(X0).all(-1)
    X0[bad] = np.nan_to_num(X0[:, IDX["Hip"]])[np.nonzero(bad)[0]]

    t_uv, t_w = torch.tensor(uv, **f32), torch.tensor(w2d, **f32)
    K, R, tt = (torch.tensor(a, **f32) for a in (cam.K, cam.R, cam.t))
    dist = [float(d) for d in np.r_[cam.dist.ravel(), np.zeros(5)][:5]]
    X_init = torch.tensor(X0, **f32)

    bi = torch.tensor([[IDX[a], IDX[b]] for a, b in BONES], device=dev)
    # symmetric bone groups -> shared length parameter
    bone_param = list(range(len(BONES)))
    for (a1, b1), (a2, b2) in SYMMETRIC_BONES:
        bone_param[BONES.index((a2, b2))] = BONES.index((a1, b1))
    bone_param = torch.tensor(bone_param, device=dev)
    L0 = np.nanmedian(np.linalg.norm(X0[:, bi[:, 0].cpu()] - X0[:, bi[:, 1].cpu()], axis=-1), 0)

    foot_h_idx = {k: [IDX[FOOT[s][k]] for s in ("L", "R")] for k in ("heel", "toe", "toe2")}

    # X = X_init + global offset + per-frame root offset + per-joint residual.
    # The coarse terms let Adam move the whole body (e.g. a lateral/depth error of the lift)
    # quickly; optimising free points alone converges very slowly for rigid shifts.
    g_off = torch.nn.Parameter(torch.zeros(1, 1, 3, **f32))
    r_off = torch.nn.Parameter(torch.zeros(T, 1, 3, **f32))
    d_jnt = torch.nn.Parameter(torch.zeros(T, J, 3, **f32))
    pel = X_init[:, IDX["Hip"]][:, None]
    log_s = torch.nn.Parameter(torch.zeros((), **f32))   # global size correction about the pelvis

    def current_X():
        return pel + torch.exp(log_s) * (X_init - pel) + g_off + r_off + d_jnt
    logL = torch.nn.Parameter(torch.tensor(np.log(np.maximum(L0, 0.02)), **f32))
    contact_m, v_est = _contact_mask(X0, fps, cfg.stance_window)
    v0 = cfg.init_belt_speed if cfg.init_belt_speed is not None else (v_est if np.isfinite(v_est) else 1.0)
    v = torch.nn.Parameter(torch.tensor(float(v0), **f32))
    sole_h0 = torch.tensor(cfg.sole_heights, **f32)
    sole_h = torch.nn.Parameter(sole_h0.clone())

    hist = []
    for rnd in range(cfg.rounds):
        if rnd > 0:
            contact_m, _ = _contact_mask(current_X().detach().cpu().numpy(), fps, cfg.stance_window)
        C = torch.tensor(contact_m, **f32)
        Cv = C[:-1] * C[1:]                       # contact on both frames of a velocity sample
        opt = torch.optim.Adam([{"params": [d_jnt, logL, v, sole_h], "lr": cfg.lr},
                                {"params": [g_off, log_s], "lr": cfg.lr * 2},
                                {"params": [r_off], "lr": cfg.lr}])
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, cfg.iters, eta_min=cfg.lr * 0.05)
        for it in range(cfg.iters):
            opt.zero_grad()
            X = current_X()
            proj = _project_torch(X, K, dist, R, tt)
            r = (proj - t_uv).norm(dim=-1) / cfg.sigma_px
            hub = torch.where(r < cfg.huber_px, 0.5 * r ** 2, cfg.huber_px * (r - 0.5 * cfg.huber_px))
            l_rep = (t_w * hub).sum() / t_w.sum().clamp(min=1)

            Lb = torch.exp(logL)[bone_param]
            d = (X[:, bi[:, 0]] - X[:, bi[:, 1]]).norm(dim=-1)
            l_bone = (((d - Lb) / cfg.sigma_bone) ** 2).mean()

            vel = (X[1:] - X[:-1]) * fps
            target = torch.stack([-v, torch.zeros((), **f32), torch.zeros((), **f32)])
            l_cv = (Cv[..., None] * ((vel - target) / cfg.sigma_contact_vel) ** 2).sum() / Cv.sum().clamp(min=1)

            l_ch = 0.0
            for k_i, (k, js) in enumerate(foot_h_idx.items()):
                y = X[:, js, 1]
                l_ch = l_ch + (C[:, js] * ((y - sole_h[k_i]) / cfg.sigma_contact_h) ** 2).sum()
            l_ch = l_ch / C.sum().clamp(min=1)

            feet = [IDX[n] for s in ("L", "R") for n in FOOT[s].values()]
            l_pen = cfg.w_penetration * (torch.relu(-X[:, feet, 1]) ** 2).mean() * 1e4

            acc = (X[2:] - 2 * X[1:-1] + X[:-2]) * fps ** 2
            l_acc = ((acc / cfg.sigma_acc) ** 2).mean()
            l_pri = (((X - X_init) / cfg.sigma_prior) ** 2).mean()

            l_sole = (((sole_h - sole_h0) / cfg.sigma_sole) ** 2).sum()
            loss = l_rep + l_bone + l_cv + l_ch + l_pen + l_acc + l_pri + l_sole
            loss.backward()
            opt.step()
            sched.step()
            with torch.no_grad():
                sole_h.clamp_(0.0, 0.08)
            if cfg.verbose and (it % 200 == 0 or it == cfg.iters - 1):
                rec = dict(round=rnd, it=it, **{k: float(val.detach()) for k, val in dict(
                    loss=loss, rep=l_rep, bone=l_bone, cvel=l_cv, ch=l_ch, acc=l_acc, prior=l_pri, v=v).items()})
                hist.append(rec)
                print("  ".join(f"{k}={val:.4g}" if isinstance(val, float) else f"{k}={val}" for k, val in rec.items()))

    with torch.no_grad():
        X = current_X()
        Xr = X.cpu().numpy()
        proj = _project_torch(X, K, dist, R, tt).cpu().numpy()
    err = np.linalg.norm(proj - uv, axis=-1)
    m = w2d > 0
    info = {
        "belt_speed": float(v.detach()),
        "bone_lengths": {f"{a}-{b}": float(l) for (a, b), l in zip(BONES, torch.exp(logL)[bone_param].detach().cpu().numpy())},
        "sole_heights": dict(zip(("heel", "toe", "toe2"), sole_h.detach().cpu().numpy().tolist())),
        "reproj_rmse_px": float(np.sqrt(np.mean(err[m] ** 2))),
        "history": hist,
    }
    out = Keypoints3D(Xr, init.conf.copy(), fps, list(init.names),
                      meta={**init.meta, "refined": True, "belt_speed": info["belt_speed"]})
    return out, info
