import { api } from "../api.js";
import { h, clear, icon, fmt, card, emptyState, jobBadge, progressBar, crumbs, toast } from "../ui.js";

const KIND = { pipeline: ["activity", "Gait pipeline"], intrinsics: ["camera", "Camera intrinsics"], selftest: ["zap", "Self-test"] };

export async function render(view, [jid], ctx) {
  return jid ? detail(view, jid, ctx) : list(view, ctx);
}

function list(view, ctx) {
  const body = h("div");
  view.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Jobs"),
    h("div", { class: "sub" }, "Background runs, one at a time. Logs are kept in the data folder (.jobs/)."))), body);
  const draw = (jobs) => {
    clear(body);
    if (!jobs.length) { body.append(h("div", { class: "card" }, emptyState("list", "No jobs yet", "Processing a trial or calibrating a camera shows up here."))); return; }
    body.append(card(null, null, null, h("div", { class: "table-wrap" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, "Job"), h("th", {}, "Status"), h("th", {}, "Progress"), h("th", {}, "Started"), h("th", { class: "num" }, "Duration"))),
      h("tbody", {}, jobs.map((j) => {
        const [ic, kind] = KIND[j.kind] || ["file", j.kind];
        const dur = j.started ? ((j.finished || Date.now() / 1000) - j.started) : null;
        return h("tr", { class: "click", onclick: () => { location.hash = `#/jobs/${j.id}`; } },
          h("td", {}, h("div", { class: "row", style: { gap: "10px", flexWrap: "nowrap" } }, h("span", { class: "muted" }, icon(ic, 16)),
            h("div", {}, h("div", { class: "cell-main" }, j.title), h("div", { class: "cell-sub" }, kind)))),
          h("td", {}, jobBadge(j, false), j.status === "failed" && j.error ? h("div", { class: "cell-sub", style: { maxWidth: "360px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.error) : null),
          h("td", { style: { width: "200px" } }, j.status === "running" ? h("div", { style: { display: "grid", gap: "4px" } }, progressBar(j),
            h("span", { class: "cell-sub" }, j.stage ? `${j.stage_index}/${j.stage_count} ${j.stage}` : "")) : j.status === "queued" ? h("span", { class: "cell-sub" }, "waiting") : ""),
          h("td", { class: "nowrap" }, fmt.ago(j.started || j.created)),
          h("td", { class: "num" }, fmt.dur(dur)));
      }))))));
  };
  draw(ctx.jobs);
  ctx.onJobs(draw);
}

async function detail(view, jid, ctx) {
  const head = h("div"), meta = h("div"), logBox = h("pre", { class: "log", tabindex: 0 });
  let follow = true;
  logBox.addEventListener("scroll", () => { follow = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 30; });
  view.append(crumbs({ label: "Jobs", href: "#/jobs" }, { label: jid }), head, meta,
    card("Log", null, [h("a", { class: "btn sm", href: `/api/jobs/${api.enc(jid)}/log`, download: "" }, icon("download", 14), "Download")],
      h("div", { class: "card-body" }, logBox)));
  let timer = null, stopped = false;
  const tick = async () => {
    let j;
    try { j = await api.get(`/api/jobs/${api.enc(jid)}?tail=1500`); } catch (e) {
      clear(head).append(h("div", { class: "banner bad" }, icon("alert", 16), h("div", { class: "grow" }, e.message))); return;
    }
    const m = j.meta || {};
    const active = ["queued", "running"].includes(j.status);
    const cancel = h("button", { class: "btn danger", onclick: async () => { await api.post(`/api/jobs/${api.enc(jid)}/cancel`); toast("Cancel requested", "", "info", null, 3000); ctx.pollNow(); } }, icon("stop", 14), "Cancel");
    const links = [];
    if (j.kind === "pipeline") {
      links.push(h("a", { class: "btn", href: `#/s/${encodeURIComponent(m.subject)}` }, "Subject"));
      if (j.status === "done") links.push(h("a", { class: "btn primary", href: `#/s/${encodeURIComponent(m.subject)}/t/${encodeURIComponent(m.trial)}` }, "View results", icon("chevron", 14)));
    }
    if (j.kind === "intrinsics" && j.status === "done") links.push(h("a", { class: "btn primary", href: "#/cameras" }, "Open cameras", icon("chevron", 14)));
    clear(head).append(h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, j.title), h("div", { class: "sub" }, jobBadge(j), h("span", {}, `started ${fmt.date(j.started || j.created)}`),
        j.started ? h("span", {}, `duration ${fmt.dur((j.finished || Date.now() / 1000) - j.started)}`) : null)),
      h("div", { class: "actions" }, active ? cancel : null, links)));
    clear(meta);
    if (j.status === "running") {
      meta.append(h("div", { class: "card card-pad", style: { marginBottom: "18px", display: "grid", gap: "8px" } },
        h("div", { class: "row" }, h("b", {}, j.stage ? `Step ${j.stage_index} of ${j.stage_count}: ${j.stage}` : "Running"), h("span", { class: "spacer" }),
          j.progress != null ? h("span", { class: "tabnum ink2" }, `${Math.round(j.progress * 100)} %`) : null),
        progressBar(j), j.live ? h("div", { class: "small muted mono", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.live) : null));
    } else if (j.status === "failed" || j.status === "interrupted") {
      meta.append(h("div", { class: "banner bad", style: { marginBottom: "18px" } }, icon("alert", 16),
        h("div", { class: "grow" }, h("b", {}, j.status === "failed" ? "The run failed" : "Interrupted"), h("span", { class: "mono small" }, j.error || ""),
          hintFor(j.error))));
    }
    clear(logBox).append(j.log.join(""), j.live ? h("span", { class: "live" }, `${j.live}\n`) : "");
    if (follow) logBox.scrollTop = logBox.scrollHeight;
    if (!stopped) timer = setTimeout(tick, active ? 1200 : 6000);
  };
  await tick();
  return () => { stopped = true; clearTimeout(timer); };
}

function hintFor(err) {
  if (!err) return null;
  const tips = [
    [/onnxruntime fell back to CPU|CUDAExecutionProvider|libcublas|cudnn/i, "GPU libraries did not load. Check System, or process with Compute device = CPU."],
    [/No module named 'opensim'|OpenSim/i, "OpenSim is not available in this environment: untick “OpenSim scaling” when processing, or install it with conda."],
    [/usable checkerboard views/i, "Check the inner-corner counts (squares − 1), use a smaller frame step, or record a sharper video."],
    [/pip install|No module named/i, "A Python package is missing in the environment the app runs in. Open System to see which, and start the app from the humotech conda env."],
    [/CUDA out of memory/i, "The GPU ran out of memory: close other GPU programs or use CPU."],
    [/Cannot open video|Could not read frame/i, "OpenCV could not decode the video. Re-encode it as H.264 MP4 (e.g. with ffmpeg)."],
  ];
  const t = tips.find(([re]) => re.test(err));
  return t ? h("span", { class: "small" }, icon("info", 13), " ", t[1]) : null;
}
