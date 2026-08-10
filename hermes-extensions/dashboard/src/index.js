(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !SDK.React || !window.__HERMES_PLUGINS__) return;
  const React = SDK.React;
  const h = React.createElement;
  const { useCallback, useEffect, useMemo, useState } = React;
  const fetchJSON = SDK.fetchJSON;
  const API = "/api/plugins/hermes-extensions";
  const PREFS = "hermes-extensions.management.prefs";

  function request(path, init) {
    const options = Object.assign({}, init || {});
    if (options.body && !options.headers) options.headers = { "Content-Type": "application/json" };
    return fetchJSON(API + path, options);
  }
  function fmt(value) {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }
  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(PREFS) || "{}"); } catch (_) { return {}; }
  }
  function savePrefs(value) {
    try { localStorage.setItem(PREFS, JSON.stringify(value)); } catch (_) {}
  }
  function Card(p) { return h("div", { className: "hx-card " + (p.className || "") }, p.children); }
  function Pill(p) { return h("span", { className: "hx-pill " + (p.kind || "") }, p.children); }
  function Stat(p) { return h(Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(p.value || 0)), h("div", { className: "hx-muted" }, p.label)); }
  function Field(label, child) { return h("label", null, label, child); }
  function Empty(p) { return h("div", { className: "hx-empty" }, p.children); }
  function Tabs(p) {
    return h("div", { className: "hx-tabs" }, ["overview", "agents", "projects", "tasks"].map(function (name) {
      return h("button", { key: name, className: "hx-tab " + (p.value === name ? "active" : ""), onClick: function () { p.onChange(name); } }, name.charAt(0).toUpperCase() + name.slice(1));
    }));
  }

  function ManagementApp() {
    const prefs = useMemo(loadPrefs, []);
    const [tab, setTab] = useState(prefs.tab || "overview");
    const [management, setManagement] = useState(null);
    const [tasks, setTasks] = useState(null);
    const [upcoming, setUpcoming] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [busy, setBusy] = useState("");
    const [agentModal, setAgentModal] = useState(false);
    const [projectModal, setProjectModal] = useState(false);
    const [taskModal, setTaskModal] = useState(false);
    const [agentDetail, setAgentDetail] = useState(null);
    const [projectDetail, setProjectDetail] = useState(null);
    const [taskDetail, setTaskDetail] = useState(null);
    const [history, setHistory] = useState([]);
    const [agentForm, setAgentForm] = useState({ name: "", description: "", clone_mode: "blank", clone_from: "", workspace: "", model: "", provider: "", soul: "", no_skills: false });
    const [projectForm, setProjectForm] = useState({ name: "", profile: "default", slug: "", folders: "", primary: "", description: "", board: "", agent: "", use: true });
    const [taskForm, setTaskForm] = useState({ type: "cron", name: "", prompt: "", schedule: "", profile: "default", priority: 50, deliver: "local" });
    const [taskProfile, setTaskProfile] = useState(prefs.taskProfile || "");
    const [taskRange, setTaskRange] = useState(Number(prefs.taskRange) || 168);
    const [includeCompleted, setIncludeCompleted] = useState(Boolean(prefs.includeCompleted));

    useEffect(function () {
      savePrefs({ tab: tab, taskProfile: taskProfile, taskRange: taskRange, includeCompleted: includeCompleted });
    }, [tab, taskProfile, taskRange, includeCompleted]);

    const load = useCallback(async function () {
      setLoading(true); setError("");
      try {
        const m = await request("/management/overview");
        setManagement(m);
        const q = new URLSearchParams();
        if (taskProfile) q.set("profile", taskProfile);
        if (includeCompleted) q.set("include_completed", "true");
        const t = await request("/overview" + (q.toString() ? "?" + q.toString() : ""));
        setTasks(t);
        const uq = new URLSearchParams({ hours: String(taskRange) });
        if (taskProfile) uq.set("profile", taskProfile);
        const u = await request("/upcoming?" + uq.toString());
        setUpcoming(u.items || []);
      } catch (e) {
        setError(e.message || String(e));
      } finally {
        setLoading(false);
      }
    }, [taskProfile, taskRange, includeCompleted]);

    useEffect(function () { load(); }, [load]);

    const agents = (management && management.agents) || [];
    const projects = (management && management.projects) || [];
    const taskProfiles = (tasks && tasks.profiles) || [];
    const agentNames = agents.map(function (a) { return a.name; });

    async function doAction(key, fn, success) {
      setBusy(key); setError(""); setNotice("");
      try {
        const result = await fn();
        if (result && result.ok === false) throw new Error(result.warning || result.message || "Hermes action could not be verified");
        setNotice(success);
        await load();
        return { ok: true, result: result };
      } catch (e) {
        setError(e.message || String(e));
        return { ok: false, error: e };
      } finally {
        setBusy("");
      }
    }

    async function createAgent(e) {
      e.preventDefault();
      const payload = Object.assign({}, agentForm);
      ["clone_from", "workspace", "model", "provider", "soul"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const outcome = await doAction("agent-create", function () { return request("/agents", { method: "POST", body: JSON.stringify(payload) }); }, "Agent created in Hermes.");
      if (!outcome.ok) return;
      setAgentModal(false);
      setAgentForm({ name: "", description: "", clone_mode: "blank", clone_from: "", workspace: "", model: "", provider: "", soul: "", no_skills: false });
      if (outcome.result && outcome.result.agent) setAgentDetail(outcome.result.agent);
    }

    async function openAgent(name) {
      setBusy("agent-open"); setError("");
      try { setAgentDetail(await request("/agents/" + encodeURIComponent(name))); setTab("agents"); }
      catch (e) { setError(e.message || String(e)); }
      finally { setBusy(""); }
    }

    async function saveAgent(e) {
      e.preventDefault();
      if (!agentDetail) return;
      const oldName = agentDetail.name;
      const payload = {
        name: agentDetail.edit_name || agentDetail.name,
        description: agentDetail.description || "",
        workspace: agentDetail.workspace || ".",
        model: agentDetail.model || "",
        provider: agentDetail.provider || "",
        soul: agentDetail.soul || "",
      };
      const outcome = await doAction("agent-save", function () { return request("/agents/" + encodeURIComponent(oldName), { method: "PATCH", body: JSON.stringify(payload) }); }, "Agent changes saved.");
      if (!outcome.ok) return;
      const nextName = outcome.result && outcome.result.agent ? outcome.result.agent.name : payload.name;
      await openAgent(nextName);
    }

    function agentAction(agent, action, value) {
      return doAction("agent:" + agent.name + ":" + action, function () {
        return request("/agents/" + encodeURIComponent(agent.name) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null }) });
      }, "Agent action completed.");
    }

    async function restartAgent(agent) {
      if (!confirm("Restart Hermes gateway for '" + agent.name + "'? Active sessions may be interrupted.")) return;
      await agentAction(agent, "gateway_restart");
    }

    async function deleteAgent(agent) {
      if (!confirm("Delete Hermes agent '" + agent.name + "'? This permanently removes its profile state.")) return;
      const outcome = await doAction("agent-delete", function () { return request("/agents/" + encodeURIComponent(agent.name), { method: "DELETE" }); }, "Agent deleted.");
      if (outcome.ok) setAgentDetail(null);
    }

    async function createProject(e) {
      e.preventDefault();
      const payload = Object.assign({}, projectForm);
      payload.folders = String(payload.folders || "").split(/[,\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
      ["slug", "primary", "description", "board", "agent"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const outcome = await doAction("project-create", function () { return request("/projects", { method: "POST", body: JSON.stringify(payload) }); }, "Project created in Hermes.");
      if (!outcome.ok) return;
      setProjectModal(false);
      setProjectForm({ name: "", profile: "default", slug: "", folders: "", primary: "", description: "", board: "", agent: "", use: true });
      if (outcome.result && outcome.result.project) setProjectDetail(outcome.result.project);
    }

    async function openProject(project) {
      setBusy("project-open"); setError("");
      try { setProjectDetail(await request("/projects/" + encodeURIComponent(project.slug) + "?profile=" + encodeURIComponent(project.profile || "default"))); setTab("projects"); }
      catch (e) { setError(e.message || String(e)); }
      finally { setBusy(""); }
    }

    async function saveProject(e) {
      e.preventDefault();
      if (!projectDetail) return;
      const payload = { profile: projectDetail.profile || "default", name: projectDetail.name || "", primary: projectDetail.primary_path || "", board: projectDetail.board || "" };
      const outcome = await doAction("project-save", function () { return request("/projects/" + encodeURIComponent(projectDetail.slug), { method: "PATCH", body: JSON.stringify(payload) }); }, "Project changes saved.");
      if (outcome.ok) await openProject(projectDetail);
    }

    function projectAction(project, action, value) {
      return doAction("project:" + project.slug + ":" + action, function () {
        return request("/projects/" + encodeURIComponent(project.slug) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null, profile: project.profile || "default" }) });
      }, "Project action completed.");
    }

    async function createTask(e) {
      e.preventDefault();
      const payload = Object.assign({}, taskForm);
      if (payload.type === "kanban") { delete payload.schedule; delete payload.deliver; }
      const outcome = await doAction("task-create", function () { return request("/tasks", { method: "POST", body: JSON.stringify(payload) }); }, "Task created in Hermes.");
      if (!outcome.ok) return;
      setTaskModal(false);
      setTaskForm({ type: "cron", name: "", prompt: "", schedule: "", profile: "default", priority: 50, deliver: "local" });
    }

    async function openTask(task) {
      setTaskDetail(task); setHistory([]);
      try {
        const q = task.profile ? "?profile=" + encodeURIComponent(task.profile) + "&limit=30" : "?limit=30";
        const data = await request("/tasks/" + encodeURIComponent(task.type) + "/" + encodeURIComponent(task.id) + "/history" + q);
        setHistory(data.items || []);
      } catch (e) { setError(e.message || String(e)); }
    }

    function taskAction(task, action) {
      return doAction("task:" + task.id + ":" + action, function () {
        return request("/tasks/" + encodeURIComponent(task.type) + "/" + encodeURIComponent(task.id) + "/action", { method: "POST", body: JSON.stringify({ action: action, profile: task.profile || null }) });
      }, "Task action completed.");
    }

    function Header() {
      return h(React.Fragment, null,
        h("div", { className: "hx-header" },
          h("div", null, h("h1", null, "Hermes Management Center"), h("div", { className: "hx-muted" }, "Native Agents · Projects · Tasks · Windows WeChat extensions")),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", disabled: loading || Boolean(busy), onClick: load }, loading ? "Refreshing…" : "Refresh"))
        ),
        h(Tabs, { value: tab, onChange: setTab }),
        management && management.partial ? h("div", { className: "hx-warning" }, "Some Hermes state could not be loaded. See details below.") : null,
        error ? h("div", { className: "hx-error" }, error) : null,
        notice ? h("div", { className: "hx-notice" }, notice) : null
      );
    }

    function Overview() {
      const c = (management && management.counts) || {};
      const tc = (management && management.task_counts) || {};
      return h("div", null,
        h("div", { className: "hx-stats" },
          h(Stat, { label: "Projects", value: c.projects }), h(Stat, { label: "Agents", value: c.agents }), h(Stat, { label: "Running agents", value: c.running_agents }),
          h(Stat, { label: "Scheduled", value: tc.cron }), h(Stat, { label: "Running tasks", value: tc.running }), h(Stat, { label: "Failed", value: tc.failed })
        ),
        management && management.errors && management.errors.length ? h(Card, null, h("h2", null, "Partial load errors"), management.errors.map(function (row, i) { return h("div", { className: "hx-error-row", key: i }, h("strong", null, row.scope), h("span", null, row.message)); })) : null,
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Agents"), h("button", { className: "hx-button", onClick: function () { setAgentModal(true); setTab("agents"); } }, "+ Agent")), agents.length ? agents.slice(0, 8).map(function (a) { return h("button", { className: "hx-list-row hx-row-button", key: a.name, onClick: function () { openAgent(a.name); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, a.display_name || a.name), h("div", { className: "hx-muted" }, (a.description || "No role description") + " · " + (a.workspace || "no workspace"))), h(Pill, { kind: String(a.gateway).toLowerCase().startsWith("running") ? "ok" : "paused" }, a.gateway || "unknown")); }) : h(Empty, null, "No agents.")),
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Projects"), h("button", { className: "hx-button", onClick: function () { setProjectModal(true); setTab("projects"); } }, "+ Project")), projects.filter(function (p) { return !p.archived; }).slice(0, 8).map(function (p) { return h("button", { className: "hx-list-row hx-row-button", key: p.profile + ":" + p.slug, onClick: function () { openProject(p); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, p.name || p.slug), h("div", { className: "hx-muted" }, (p.profile || "default") + " · " + (p.primary_path || "no primary folder"))), p.active ? h(Pill, { kind: "ok" }, "active") : null); }))
        ),
        h(Card, null, h("h2", null, "Next 7 days"), (management && management.upcoming || []).length ? (management.upcoming || []).map(function (t, i) { return h("button", { className: "hx-list-row hx-row-button", key: t.type + ":" + t.id + ":" + i, onClick: function () { setTab("tasks"); openTask(t); } }, h("div", { className: "hx-time" }, fmt(t.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, t.name), h("div", { className: "hx-muted" }, t.profile || "unassigned")), h(Pill, { kind: t.type }, t.type)); }) : h(Empty, null, "No upcoming tasks."))
      );
    }

    function Agents() {
      return h("div", null,
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Agents"), h("div", { className: "hx-muted" }, "Hermes Profiles are isolated Agents.")), h("button", { className: "hx-button", onClick: function () { setAgentModal(true); } }, "+ Create Agent")),
        h("div", { className: "hx-agent-grid" }, agents.map(function (a) { return h(Card, { key: a.name }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, a.display_name || a.name), h("div", { className: "hx-muted" }, a.name)), a.is_default ? h(Pill, { kind: "ok" }, "default") : null), h("p", { className: "hx-description" }, a.description || "No role description"), h("div", { className: "hx-kv" }, h("span", null, "Model"), h("strong", null, a.model || "not configured"), h("span", null, "Workspace"), h("strong", null, a.workspace || "—"), h("span", null, "Gateway"), h("strong", null, a.gateway || "unknown")), h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", onClick: function () { openAgent(a.name); } }, "Manage"), !a.is_default ? h("button", { className: "hx-button secondary", onClick: function () { agentAction(a, "use"); } }, "Set default") : null, String(a.gateway).toLowerCase().startsWith("running") ? h("button", { className: "hx-button secondary", onClick: function () { restartAgent(a); } }, "Restart") : h("button", { className: "hx-button secondary", onClick: function () { agentAction(a, "gateway_start"); } }, "Start"))); }))
      );
    }

    function Projects() {
      return h("div", null,
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native Hermes multi-folder workspaces. Workspace Agents are computed from terminal.cwd.")), h("button", { className: "hx-button", onClick: function () { setProjectModal(true); } }, "+ Create Project")),
        h("div", { className: "hx-agent-grid" }, projects.map(function (p) { return h(Card, { key: p.profile + ":" + p.slug }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, p.name || p.slug), h("div", { className: "hx-muted" }, p.profile + " · " + p.slug)), p.archived ? h(Pill, { kind: "paused" }, "archived") : p.active ? h(Pill, { kind: "ok" }, "active") : null), h("div", { className: "hx-kv" }, h("span", null, "Primary"), h("strong", null, p.primary_path || "—"), h("span", null, "Board"), h("strong", null, p.board || "—"), h("span", null, "Workspace Agents"), h("strong", null, (p.agents || []).join(", ") || "—")), h("button", { className: "hx-button secondary", onClick: function () { openProject(p); } }, "Manage")); }))
      );
    }

    function Tasks() {
      const profiles = taskProfiles;
      const rows = profiles.flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); });
      return h("div", null,
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Tasks"), h("div", { className: "hx-muted" }, "Native Cron and Kanban.")), h("button", { className: "hx-button", onClick: function () { setTaskModal(true); } }, "+ Create Task")),
        h(Card, null, h("div", { className: "hx-toolbar" }, h("select", { value: taskProfile, onChange: function (e) { setTaskProfile(e.target.value); } }, h("option", { value: "" }, "All agents"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); })), h("select", { value: taskRange, onChange: function (e) { setTaskRange(Number(e.target.value)); } }, h("option", { value: 24 }, "24 hours"), h("option", { value: 168 }, "7 days"), h("option", { value: 720 }, "30 days")), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: includeCompleted, onChange: function (e) { setIncludeCompleted(e.target.checked); } }), " Show completed")), upcoming.map(function (u, i) { return h("button", { className: "hx-list-row hx-row-button", key: "u:" + i, onClick: function () { openTask(rows.find(function (r) { return r.id === u.id && r.type === u.type && (!u.profile || r.profile === u.profile); }) || u); } }, h("div", { className: "hx-time" }, fmt(u.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, u.name), h("div", { className: "hx-muted" }, u.profile || "unassigned")), h(Pill, { kind: u.type }, u.type)); })),
        h("div", { className: "hx-agent-grid" }, profiles.map(function (p) { return h(Card, { key: p.name }, h("h2", null, p.name), (p.cron || []).concat(p.kanban || []).map(function (t) { return h("button", { className: "hx-list-row hx-row-button", key: t.type + ":" + t.id, onClick: function () { openTask(t); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, t.name), h("div", { className: "hx-muted" }, t.type === "cron" ? (t.schedule || "") : (t.status || "task"))), h(Pill, { kind: t.type }, t.type)); })); }))
      );
    }

    function AgentDetail() {
      if (!agentDetail) return null;
      const a = agentDetail;
      return h(Card, { className: "hx-detail" }, h("div", { className: "hx-section-head" }, h("h2", null, "Agent details"), h("button", { className: "hx-button secondary", onClick: function () { setAgentDetail(null); } }, "Close")), h("form", { className: "hx-form", onSubmit: saveAgent }, Field("Profile name", h("input", { value: a.edit_name == null ? a.name : a.edit_name, disabled: a.name === "default", onChange: function (e) { setAgentDetail(Object.assign({}, a, { edit_name: e.target.value })); } })), Field("Description / role", h("textarea", { rows: 3, value: a.description || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { description: e.target.value })); } })), Field("Workspace", h("input", { value: a.workspace || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { workspace: e.target.value })); } })), Field("Provider", h("input", { value: a.provider || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { provider: e.target.value })); } })), Field("Model", h("input", { value: a.model || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { model: e.target.value })); } })), Field("SOUL.md", h("textarea", { rows: 12, value: a.soul || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { soul: e.target.value })); } })), h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: Boolean(busy) }, "Save"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "gateway_status"); } }, "Check gateway"), String(a.gateway).toLowerCase().startsWith("running") ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { restartAgent(a); } }, "Restart gateway") : h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "gateway_start"); } }, "Start gateway"), a.name !== "default" ? h("button", { className: "hx-button danger", type: "button", onClick: function () { deleteAgent(a); } }, "Delete Agent") : null)));
    }

    function ProjectDetail() {
      if (!projectDetail) return null;
      const p = projectDetail;
      return h(Card, { className: "hx-detail" }, h("div", { className: "hx-section-head" }, h("h2", null, "Project details"), h("button", { className: "hx-button secondary", onClick: function () { setProjectDetail(null); } }, "Close")), h("div", { className: "hx-muted" }, "Description/icon/color are creation-time fields because current Hermes project CLI has no stable edit command for them."), h("form", { className: "hx-form", onSubmit: saveProject }, Field("Name", h("input", { value: p.name || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { name: e.target.value })); } })), Field("Primary folder", h("input", { value: p.primary_path || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { primary_path: e.target.value })); } })), Field("Kanban board", h("input", { value: p.board || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { board: e.target.value })); } })), h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit" }, "Save"), p.archived ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "restore"); } }, "Restore") : h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "archive"); } }, "Archive"))), h("h3", null, "Folders"), (p.folders || []).map(function (f) { return h("div", { className: "hx-list-row", key: f.path }, h("div", { className: "hx-grow" }, f.path), f.is_primary ? h(Pill, { kind: "ok" }, "primary") : h("button", { className: "hx-button secondary", onClick: function () { projectAction(p, "set_primary", f.path); } }, "Set primary")); }), h("h3", null, "Workspace Agents"), h("div", { className: "hx-muted" }, (p.agents || []).join(", ") || "None. Assignment means setting Agent terminal.cwd to this project's primary folder."), h("select", { defaultValue: "", onChange: function (e) { if (e.target.value) projectAction(p, "assign_agent", e.target.value); } }, h("option", { value: "" }, "Assign workspace agent…"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); })));
    }

    function TaskDetail() {
      if (!taskDetail) return null;
      const t = taskDetail;
      return h(Card, { className: "hx-detail" }, h("div", { className: "hx-section-head" }, h("h2", null, t.name || "Task details"), h("button", { className: "hx-button secondary", onClick: function () { setTaskDetail(null); setHistory([]); } }, "Close")), h("div", { className: "hx-actions" }, t.type === "cron" ? h("button", { className: "hx-button secondary", onClick: function () { taskAction(t, t.enabled === false ? "resume" : "pause"); } }, t.enabled === false ? "Resume" : "Pause") : null, t.type === "cron" ? h("button", { className: "hx-button secondary", onClick: function () { taskAction(t, "run"); } }, "Run") : null), h("h3", null, "Execution history"), history.length ? history.map(function (row, i) { return h("div", { className: "hx-history-row", key: i }, h(Pill, { kind: row.status || "" }, row.status || row.state || "record"), h("div", { className: "hx-grow" }, fmt(row.claimed_at || row.started_at || row.completed_at || row.updated_at))); }) : h(Empty, null, "No history."));
    }

    function AgentModal() {
      if (!agentModal) return null;
      return h(Card, { className: "hx-form-card" }, h("form", { className: "hx-form", onSubmit: createAgent }, h("h2", null, "Create Agent"), Field("Name", h("input", { required: true, pattern: "[a-z0-9][a-z0-9_-]{0,63}", value: agentForm.name, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { name: e.target.value.toLowerCase() })); } })), Field("Description", h("input", { value: agentForm.description, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { description: e.target.value })); } })), Field("Clone mode", h("select", { value: agentForm.clone_mode, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_mode: e.target.value })); } }, h("option", { value: "blank" }, "Blank"), h("option", { value: "clone" }, "Clone config"), h("option", { value: "clone_all" }, "Clone all"))), Field("Clone from", h("select", { value: agentForm.clone_from, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_from: e.target.value })); } }, h("option", { value: "" }, "Default source"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Workspace", h("input", { value: agentForm.workspace, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { workspace: e.target.value })); } })), Field("Provider", h("input", { value: agentForm.provider, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { provider: e.target.value })); } })), Field("Model", h("input", { value: agentForm.model, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { model: e.target.value })); } })), h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "agent-create" }, busy === "agent-create" ? "Creating…" : "Create"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setAgentModal(false); } }, "Cancel"))));
    }

    function ProjectModal() {
      if (!projectModal) return null;
      return h(Card, { className: "hx-form-card" }, h("form", { className: "hx-form", onSubmit: createProject }, h("h2", null, "Create Project"), Field("Name", h("input", { required: true, value: projectForm.name, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { name: e.target.value })); } })), Field("Profile owner", h("select", { value: projectForm.profile, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Folders (comma/newline)", h("textarea", { rows: 3, value: projectForm.folders, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { folders: e.target.value })); } })), Field("Primary folder", h("input", { value: projectForm.primary, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { primary: e.target.value })); } })), Field("Description", h("input", { value: projectForm.description, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { description: e.target.value })); } })), Field("Board", h("input", { value: projectForm.board, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { board: e.target.value })); } })), Field("Workspace Agent", h("select", { value: projectForm.agent, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { agent: e.target.value })); } }, h("option", { value: "" }, "None"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "project-create" }, busy === "project-create" ? "Creating…" : "Create"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setProjectModal(false); } }, "Cancel"))));
    }

    function TaskModal() {
      if (!taskModal) return null;
      return h(Card, { className: "hx-form-card" }, h("form", { className: "hx-form", onSubmit: createTask }, h("h2", null, "Create Task"), Field("Type", h("select", { value: taskForm.type, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { type: e.target.value })); } }, h("option", { value: "cron" }, "Cron"), h("option", { value: "kanban" }, "Kanban"))), Field("Name", h("input", { required: true, value: taskForm.name, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { name: e.target.value })); } })), Field("Agent/Profile", h("select", { value: taskForm.profile, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field(taskForm.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 4, value: taskForm.prompt, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { prompt: e.target.value })); } })), taskForm.type === "cron" ? Field("Schedule", h("input", { required: true, value: taskForm.schedule, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { schedule: e.target.value })); } })) : null, h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "task-create" }, busy === "task-create" ? "Creating…" : "Create"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setTaskModal(false); } }, "Cancel"))));
    }

    return h("div", { className: "hx-page" }, h(Header), tab === "overview" ? h(Overview) : tab === "agents" ? h(Agents) : tab === "projects" ? h(Projects) : h(Tasks), h(AgentDetail), h(ProjectDetail), h(TaskDetail), h(AgentModal), h(ProjectModal), h(TaskModal));
  }

  window.__HERMES_PLUGINS__.register("hermes-extensions", ManagementApp);
})();
