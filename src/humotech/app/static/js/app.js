// App shell: hash router, sidebar, global job poller (+ toasts when jobs finish).
import { api } from "./api.js";
import { h, clear, icon, toast, store } from "./ui.js";
import * as subjects from "./pages/subjects.js";
import * as subject from "./pages/subject.js";
import * as calibrate from "./pages/calibrate.js";
import * as results from "./pages/results.js";
import * as cameras from "./pages/cameras.js";
import * as jobsPage from "./pages/jobs.js";
import * as system from "./pages/system.js";

const ROUTES = [
  [/^\/?$/, subjects, "subjects"],
  [/^\/s\/([^/]+)\/?$/, subject, "subjects"],
  [/^\/s\/([^/]+)\/calibrate\/?$/, calibrate, "subjects"],
  [/^\/s\/([^/]+)\/t\/([^/]+)\/?$/, results, "subjects"],
  [/^\/cameras\/?$/, cameras, "cameras"],
  [/^\/jobs\/?$/, jobsPage, "jobs"],
  [/^\/jobs\/([^/]+)\/?$/, jobsPage, "jobs"],
  [/^\/system\/?$/, system, "system"],
];

const NAV = [
  ["subjects", "#/", "users", "Subjects"],
  ["cameras", "#/cameras", "camera", "Cameras"],
  ["jobs", "#/jobs", "list", "Jobs"],
  ["system", "#/system", "cpu", "System"],
];

// -------------------------------------------------------------- job state
const jobListeners = new Set();
let jobs = [];
let known = new Map();
let pollTimer = null;

export const ctx = {
  get jobs() { return jobs; },
  onJobs(fn) { jobListeners.add(fn); return () => jobListeners.delete(fn); },
  pollNow() { clearTimeout(pollTimer); poll(); },
};

async function poll() {
  try {
    jobs = await api.get("/api/jobs");
    for (const j of jobs) {
      const prev = known.get(j.id);
      if (prev && prev !== j.status && !["queued", "running"].includes(j.status)) notifyDone(j);
      known.set(j.id, j.status);
    }
    renderNavBadge();
    jobListeners.forEach((fn) => { try { fn(jobs); } catch (e) { console.error(e); } });
  } catch (e) { /* server restarting; try again */ }
  const active = jobs.some((j) => j.status === "queued" || j.status === "running");
  pollTimer = setTimeout(poll, active ? 1500 : 5000);
}

function notifyDone(j) {
  const m = j.meta || {};
  if (j.status === "done") {
    const action = j.kind === "pipeline" ? { href: `#/s/${m.subject}/t/${m.trial}`, label: "View results" }
      : j.kind === "intrinsics" ? { href: "#/cameras", label: "Open cameras" } : { href: `#/jobs/${j.id}`, label: "Open log" };
    toast(`${j.title} finished`, "", "good", action);
  } else if (j.status === "failed") {
    toast(`${j.title} failed`, j.error || "", "bad", { href: `#/jobs/${j.id}`, label: "Open log" }, 12000);
  }
}

// ------------------------------------------------------------------ shell
let current = { key: null };

function renderNav(section) {
  const nav = clear(document.getElementById("nav"));
  for (const [key, href, ic, label] of NAV) {
    nav.append(h("a", { href, class: key === section ? "active" : "", dataset: { key } }, icon(ic, 17),
      h("span", { class: "lbl" }, label), key === "jobs" ? h("span", { class: "badge count hidden", id: "jobs-badge" }) : null));
  }
  renderNavBadge();
}

function renderNavBadge() {
  const b = document.getElementById("jobs-badge");
  if (!b) return;
  const n = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  b.textContent = n;
  b.classList.toggle("hidden", n === 0);
  b.title = `${n} active job${n === 1 ? "" : "s"}`;
}

async function renderFoot() {
  const foot = clear(document.getElementById("sidebar-foot"));
  const theme = () => document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const btn = h("button", { class: "btn ghost sm theme-toggle", title: "Toggle light / dark" });
  const paint = () => { clear(btn).append(icon(theme() === "dark" ? "sun" : "moon", 14), theme() === "dark" ? "Light mode" : "Dark mode"); };
  btn.onclick = () => { const t = theme() === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; try { localStorage.setItem("humotech-theme", t); } catch (e) { /* */ } paint(); };
  paint();
  foot.append(btn);
  try {
    const o = await api.get("/api/overview");
    foot.append(h("div", {}, h("div", {}, "Data folder"), h("div", { class: "path" }, o.data_root)), h("div", {}, `v${o.version}`));
  } catch (e) { /* ignore */ }
}

async function route() {
  const path = location.hash.replace(/^#/, "") || "/";
  let match = null;
  for (const [re, mod, section] of ROUTES) {
    const m = path.match(re);
    if (m) { match = { mod, section, params: m.slice(1).map(decodeURIComponent) }; break; }
  }
  const view = document.getElementById("view");
  if (current.cleanup) { try { current.cleanup(); } catch (e) { /* */ } }
  current.unsubs?.forEach((u) => u());
  current = { unsubs: [] };
  if (!match) {
    clear(view).append(h("div", { class: "empty" }, h("h2", {}, "Page not found"), h("a", { href: "#/" }, "Go to subjects")));
    return;
  }
  renderNav(match.section);
  clear(view);
  const pageCtx = { ...ctx, onJobs: (fn) => { const u = ctx.onJobs(fn); current.unsubs.push(u); return u; } };
  try {
    current.cleanup = await match.mod.render(view, match.params, pageCtx);
  } catch (e) {
    console.error(e);
    clear(view).append(h("div", { class: "banner bad" }, icon("alert", 18),
      h("div", { class: "grow" }, h("b", {}, "Could not load this page"), h("span", {}, e.message),
        h("div", {}, h("a", { href: "#/" }, "Back to subjects")))));
  }
  view.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
renderFoot();
poll().then(() => { for (const j of jobs) known.set(j.id, j.status); });
route();
store("opened", Date.now());
