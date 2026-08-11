(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !SDK.React || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useCallback, useEffect, useMemo, useState } = React;
  const fetchJSON = SDK.fetchJSON;
  const API = "/api/plugins/hermes-extensions";
  const PREFS = "hermes-extensions.management.prefs.v2";
  const TABS = ["overview", "agents", "projects", "tasks", "wechat"];

  function request(path, init) {
    const options = Object.assign({}, init || {});
    if (options.body && !options.headers) options.headers = { "Content-Type": "application/json" };
    return fetchJSON(API + path, options);
  }

  function errText(error) {
    if (!error) return "Unknown error";
    const detail = error.detail || (error.response && error.response.detail);
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    if (error.message) return error.message;
    try { return JSON.stringify(detail || error); } catch (_) { return String(error); }
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

  function Card(p) { return h("section", { className: "hx-card " + (p.className || "") }, p.children); }
  function Pill(p) { return h("span", { className: "hx-pill " + (p.kind || "") }, p.children); }
  function Stat(p) { return h(Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(p.value == null ? 0 : p.value)), h("div", { className: "hx-muted" }, p.label)); }
  function Field(label, child, help) { return h("label", null, h("span", null, label), child, help ? h("small", null, help) : null); }
  function Empty(p) { return h("div", { className: "hx-empty" }, p.children); }
  function LoadingBlock(p) { return h("div", { className: "hx-loading" }, h("span", { className: "hx-spinner" }), p.children || "Loading…"); }

  function Dialog(p) {
    useEffect(function () {
      if (!p.open) return undefined;
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      function onKey(e) {
        if (e.key === "Escape" && !p.locked) p.onClose();
      }
      document.addEventListener("keydown", onKey);
      return function () {
        document.removeEventListener("keydown", onKey);
        document.body.style.overflow = previousOverflow;
      };
    }, [p.open, p.locked, p.onClose]);
    if (!p.open) return null;
    return h("div", { className: "hx-dialog-backdrop", role: "presentation", onMouseDown: function (e) { if (e.target === e.currentTarget && !p.locked) p.onClose(); } },
      h("div", { className: "hx-dialog", role: "dialog", "aria-modal": "true", "aria-label": p.title },
        h("div", { className: "hx-dialog-head" }, h("div", null, h("h2", null, p.title), p.subtitle ? h("div", { className: "hx-muted" }, p.subtitle) : null), h("button", { type: "button", className: "hx-icon-button", disabled: p.locked, onClick: p.onClose, "aria-label": "Close" }, "×")),
        h("div", { className: "hx-dialog-body" }, p.children)
      )
    );
  }

  function Tabs(p) {
    return h("div", { className: "hx-tabs", role: "tablist" }, TABS.map(function (name) {
      const label = name === "wechat" ? "WeChat" : name.charAt(0).toUpperCase() + name.slice(1);
      return h("button", { key: name, role: "tab", "aria-selected": p.value === name, className: "hx-tab " + (p.value === name ? "active" : ""), onClick: function () { p.onChange(name); } }, label);
    }));
  }

  function SearchBox(p) {
    return h("input", { className: "hx-search", type: "search", placeholder: p.placeholder || "Search…", value: p.value, onChange: function (e) { p.onChange(e.target.value); } });
  }

  function ManagementApp() {
    const prefs = useMemo(loadPrefs, []);
    const [tab, setTab] = useState(TABS.indexOf(prefs.tab) >= 0 ? prefs.tab : "overview");
    const [management, setManagement] = useState(null);
    const [tasks, setTasks] = useState(null);
    const [upcoming, setUpcoming] = useState([]);
    const [wechatHealth, setWechatHealth] = useState(null);
    const [wechatStatus, setWechatStatus] = useState(null);
    const [wechatChats, setWechatChats] = useState([]);
    const [wechatUnread, setWechatUnread] = useState([]);
    const [coreLoading, setCoreLoading] = useState(true);
    const [tasksLoading, setTasksLoading] = useState(false);
    const [wechatLoading, setWechatLoading] = useState(false);
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
    const [historyLoading, setHistoryLoading] = useState(false);
    const [agentSearch, setAgentSearch] = useState("");
    const [projectSearch, setProjectSearch] = useState("");
    const [projectFilter, setProjectFilter] = useState("active");
    const [taskSearch, setTaskSearch] = useState("");
    const [taskTypeFilter, setTaskTypeFilter] = useState("all");
    const [taskProfile, setTaskProfile] = useState(prefs.taskProfile || "");
    const [taskRange, setTaskRange] = useState(Number(prefs.taskRange) || 168);
    const [includeCompleted, setIncludeCompleted] = useState(Boolean(prefs.includeCompleted));
    const [projectFolderInput, setProjectFolderInput] = useState("");
    const [wechatDryRun, setWechatDryRun] = useState({ chat: "", text: "Test message — dry run only" });
    const [agentForm, setAgentForm] = useState({ name: "", description: "", clone_mode: "blank", clone_from: "", workspace: "", model: "", provider: "", soul: "", no_skills: false });
    const [projectForm, setProjectForm] = useState({ name: "", profile: "default", slug: "", folders: "", primary: "", description: "", icon: "", color: "", board: "", agent: "", use: true });
    const [taskForm, setTaskForm] = useState({ type: "cron", name: "", prompt: "", schedule: "", profile: "default", priority: 50, deliver: "local" });

    useEffect(function () {
      savePrefs({ tab: tab, taskProfile: taskProfile, taskRange: taskRange, includeCompleted: includeCompleted });
    }, [tab, taskProfile, taskRange, includeCompleted]);

    const loadCore = useCallback(async function () {
      setCoreLoading(true); setError("");
      try {
        const results = await Promise.all([request("/management/overview"), request("/wechat/health")]);
        setManagement(results[0]);
        setWechatHealth(results[1]);
      } catch (e) {
        setError(errText(e));
      } finally {
        setCoreLoading(false);
      }
    }, []);

    const loadTasks = useCallback(async function () {
      setTasksLoading(true); setError("");
      try {
        const q = new URLSearchParams();
        if (taskProfile) q.set("profile", taskProfile);
        if (includeCompleted) q.set("include_completed", "true");
        const uq = new URLSearchParams({ hours: String(taskRange) });
        if (taskProfile) uq.set("profile", taskProfile);
        const results = await Promise.all([
          request("/overview" + (q.toString() ? "?" + q.toString() : "")),
          request("/upcoming?" + uq.toString())
        ]);
        setTasks(results[0]);
        setUpcoming(results[1].items || []);
        return results[0];
      } catch (e) {
        setError(errText(e));
        return null;
      } finally {
        setTasksLoading(false);
      }
    }, [taskProfile, taskRange, includeCompleted]);

    const loadWeChat = useCallback(async function (withDesktop) {
      setWechatLoading(true); setError("");
      try {
        const calls = [request("/wechat/health")];
        if (withDesktop) calls.push(request("/wechat/status"), request("/wechat/chats?limit=40"), request("/wechat/unread?limit=40"));
        const results = await Promise.all(calls);
        setWechatHealth(results[0]);
        if (withDesktop) {
          setWechatStatus(results[1]);
          setWechatChats((results[2] && results[2].items) || []);
          setWechatUnread((results[3] && results[3].items) || []);
        }
      } catch (e) {
        setError(errText(e));
      } finally {
        setWechatLoading(false);
      }
    }, []);

    useEffect(function () { loadCore(); }, [loadCore]);
    useEffect(function () { if (tab === "tasks") loadTasks(); }, [tab, loadTasks]);
    useEffect(function () { if (tab === "wechat") loadWeChat(true); }, [tab, loadWeChat]);

    const agents = (management && management.agents) || [];
    const projects = (management && management.projects) || [];
    const projectSupported = Boolean(management && management.project_supported);
    const taskProfiles = (tasks && tasks.profiles) || [];
    const agentNames = agents.map(function (a) { return a.name; });
    const taskRows = taskProfiles.flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); });

    function flattenTaskOverview(data) {
      return ((data && data.profiles) || []).flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); });
    }

    async function doAction(key, fn, success, after) {
      setBusy(key); setError(""); setNotice("");
      try {
        const result = await fn();
        if (result && result.ok === false) throw new Error(result.warning || result.message || "Hermes action could not be verified");
        const msg = typeof success === "function" ? success(result) : success;
        if (msg) setNotice(msg);
        await loadCore();
        if (tab === "tasks") await loadTasks();
        if (after) await after(result);
        return { ok: true, result: result };
      } catch (e) {
        setError(errText(e));
        return { ok: false, error: e };
      } finally {
        setBusy("");
      }
    }

    async function createAgent(e) {
      e.preventDefault();
      const payload = Object.assign({}, agentForm);
      ["clone_from", "workspace", "model", "provider", "soul"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const outcome = await doAction("agent-create", function () { return request("/agents", { method: "POST", body: JSON.stringify(payload) }); }, "Agent created.");
      if (!outcome.ok) return;
      setAgentModal(false);
      setAgentForm({ name: "", description: "", clone_mode: "blank", clone_from: "", workspace: "", model: "", provider: "", soul: "", no_skills: false });
      if (outcome.result && outcome.result.agent) setAgentDetail(outcome.result.agent);
    }

    async function openAgent(name) {
      setBusy("agent-open"); setError("");
      try { setAgentDetail(await request("/agents/" + encodeURIComponent(name))); setTab("agents"); }
      catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    async function saveAgent(e) {
      e.preventDefault();
      if (!agentDetail) return;
      const oldName = agentDetail.name;
      const payload = { name: agentDetail.edit_name || agentDetail.name, description: agentDetail.description || "", workspace: agentDetail.workspace || ".", model: agentDetail.model || "", provider: agentDetail.provider || "", soul: agentDetail.soul || "" };
      const outcome = await doAction("agent-save", function () { return request("/agents/" + encodeURIComponent(oldName), { method: "PATCH", body: JSON.stringify(payload) }); }, "Agent changes saved.");
      if (!outcome.ok) return;
      const nextName = outcome.result && outcome.result.agent ? outcome.result.agent.name : payload.name;
      await openAgent(nextName);
    }

    function agentAction(agent, action, value, label) {
      return doAction("agent:" + agent.name + ":" + action, function () {
        return request("/agents/" + encodeURIComponent(agent.name) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null }) });
      }, label || "Agent action completed.", function (result) {
        if (result && result.agent && agentDetail && agentDetail.name === agent.name) setAgentDetail(result.agent);
      });
    }

    async function restartAgent(agent) {
      if (!confirm("Restart Hermes gateway for '" + agent.name + "'? Active sessions may be interrupted.")) return;
      await agentAction(agent, "gateway_restart", null, "Gateway restarted.");
    }
    async function deleteAgent(agent) {
      if (!confirm("Delete Agent '" + agent.name + "'? This permanently removes its Hermes Profile state.")) return;
      const outcome = await doAction("agent-delete", function () { return request("/agents/" + encodeURIComponent(agent.name), { method: "DELETE" }); }, "Agent deleted.");
      if (outcome.ok) setAgentDetail(null);
    }

    async function createProject(e) {
      e.preventDefault();
      if (!projectSupported) return;
      const payload = Object.assign({}, projectForm);
      payload.folders = String(payload.folders || "").split(/[,\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
      ["slug", "primary", "description", "icon", "color", "board", "agent"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const outcome = await doAction("project-create", function () { return request("/projects", { method: "POST", body: JSON.stringify(payload) }); }, "Project created.");
      if (!outcome.ok) return;
      setProjectModal(false);
      setProjectForm({ name: "", profile: "default", slug: "", folders: "", primary: "", description: "", icon: "", color: "", board: "", agent: "", use: true });
      if (outcome.result && outcome.result.project) setProjectDetail(outcome.result.project);
    }

    async function openProject(project) {
      if (!projectSupported) return;
      setBusy("project-open"); setError("");
      try { setProjectDetail(await request("/projects/" + encodeURIComponent(project.slug) + "?profile=" + encodeURIComponent(project.profile || "default"))); setTab("projects"); }
      catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    async function saveProject(e) {
      e.preventDefault();
      if (!projectDetail) return;
      const payload = { profile: projectDetail.profile || "default", name: projectDetail.name || "", primary: projectDetail.primary_path || "", board: projectDetail.board || "" };
      const outcome = await doAction("project-save", function () { return request("/projects/" + encodeURIComponent(projectDetail.slug), { method: "PATCH", body: JSON.stringify(payload) }); }, "Project changes saved.");
      if (outcome.ok) await openProject(projectDetail);
    }

    function projectAction(project, action, value, label) {
      return doAction("project:" + project.slug + ":" + action, function () {
        return request("/projects/" + encodeURIComponent(project.slug) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null, profile: project.profile || "default" }) });
      }, label || "Project action completed.", function () { return openProject(project); });
    }

    async function createTask(e) {
      e.preventDefault();
      const payload = Object.assign({}, taskForm);
      if (payload.type === "kanban") { delete payload.schedule; delete payload.deliver; }
      else { delete payload.priority; }
      const outcome = await doAction("task-create", function () { return request("/tasks", { method: "POST", body: JSON.stringify(payload) }); }, "Task created.");
      if (!outcome.ok) return;
      setTaskModal(false);
      setTaskForm({ type: "cron", name: "", prompt: "", schedule: "", profile: "default", priority: 50, deliver: "local" });
      await loadTasks();
    }

    async function openTask(task) {
      setHistory([]); setHistoryLoading(true); setError(""); setTab("tasks");
      try {
        let actual = Object.assign({}, task);
        const hasEditablePayload = Object.prototype.hasOwnProperty.call(actual, "prompt") || Object.prototype.hasOwnProperty.call(actual, "body") || Object.prototype.hasOwnProperty.call(actual, "priority");
        if (!hasEditablePayload && task && task.type && task.id) {
          const q = new URLSearchParams({ include_completed: "true" });
          if (task.profile) q.set("profile", task.profile);
          const detailOverview = await request("/overview?" + q.toString());
          const candidate = flattenTaskOverview(detailOverview).find(function (row) {
            return row.id === task.id && row.type === task.type && (!task.profile || row.profile === task.profile);
          });
          if (candidate) actual = Object.assign({}, candidate);
        }
        setTaskDetail(actual);
        const historyQuery = actual.profile ? "?profile=" + encodeURIComponent(actual.profile) + "&limit=40" : "?limit=40";
        const data = await request("/tasks/" + encodeURIComponent(actual.type) + "/" + encodeURIComponent(actual.id) + "/history" + historyQuery);
        setHistory(data.items || []);
      } catch (e) { setError(errText(e)); setTaskDetail(Object.assign({}, task)); }
      finally { setHistoryLoading(false); }
    }

    async function saveTask(e) {
      e.preventDefault();
      if (!taskDetail) return;
      const t = taskDetail;
      const payload = { name: t.name || "", prompt: t.prompt || t.body || "", profile: t.profile || "" };
      if (t.type === "cron") payload.schedule = t.schedule || "";
      if (t.type === "kanban") payload.priority = Number(t.priority == null ? 50 : t.priority);
      const outcome = await doAction("task-save", function () { return request("/tasks/" + encodeURIComponent(t.type) + "/" + encodeURIComponent(t.id), { method: "PATCH", body: JSON.stringify(payload) }); }, "Task changes saved.");
      if (outcome.ok) { await loadTasks(); setTaskDetail(Object.assign({}, t, payload)); }
    }

    async function taskAction(task, action, value, label) {
      const destructive = action === "remove" || action === "archive";
      if (destructive && !confirm((action === "remove" ? "Remove" : "Archive") + " task '" + (task.name || task.id) + "'?")) return;
      const outcome = await doAction("task:" + task.id + ":" + action, function () {
        return request("/tasks/" + encodeURIComponent(task.type) + "/" + encodeURIComponent(task.id) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null, profile: task.profile || null }) });
      }, label || "Task action completed.");
      if (outcome.ok) {
        await loadTasks();
        if (destructive) { setTaskDetail(null); setHistory([]); }
        else if (taskDetail && taskDetail.id === task.id && taskDetail.type === task.type) {
          if (action === "pause") setTaskDetail(Object.assign({}, taskDetail, { enabled: false }));
          if (action === "resume") setTaskDetail(Object.assign({}, taskDetail, { enabled: true }));
          if (action === "assign" && value) setTaskDetail(Object.assign({}, taskDetail, { profile: value }));
        }
      }
    }

    async function runWeChatDryRun(e) {
      e.preventDefault();
      setBusy("wechat-dry-run"); setError(""); setNotice("");
      try {
        const result = await request("/wechat/dry-run", { method: "POST", body: JSON.stringify(wechatDryRun) });
        setNotice(result && result.dry_run ? "Dry run completed. No message was sent." : "Dry run completed.");
        await loadWeChat(false);
      } catch (e2) { setError(errText(e2)); }
      finally { setBusy(""); }
    }

    const filteredAgents = agents.filter(function (a) {
      const q = agentSearch.trim().toLowerCase();
      return !q || [a.name, a.display_name, a.description, a.workspace, a.model, a.provider].some(function (v) { return String(v || "").toLowerCase().includes(q); });
    });
    const filteredProjects = projects.filter(function (p) {
      const q = projectSearch.trim().toLowerCase();
      const stateOk = projectFilter === "all" || (projectFilter === "archived" ? p.archived : !p.archived);
      return stateOk && (!q || [p.name, p.slug, p.profile, p.primary_path, p.board].some(function (v) { return String(v || "").toLowerCase().includes(q); }));
    });
    const filteredTasks = taskRows.filter(function (t) {
      const q = taskSearch.trim().toLowerCase();
      const typeOk = taskTypeFilter === "all" || t.type === taskTypeFilter;
      return typeOk && (!q || [t.name, t.id, t.schedule, t.status, t.profile].some(function (v) { return String(v || "").toLowerCase().includes(q); }));
    });
    const meaningfulErrors = ((management && management.errors) || []).filter(function (row) { return !(row.scope === "projects" && !projectSupported); });

    function Header() {
      return h(React.Fragment, null,
        h("div", { className: "hx-header" },
          h("div", null, h("h1", null, "Hermes Management Center"), h("div", { className: "hx-muted" }, "Agents · Projects · Tasks · Windows WeChat")),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", disabled: coreLoading || Boolean(busy), onClick: loadCore }, coreLoading ? "Refreshing…" : "Refresh"))
        ),
        h(Tabs, { value: tab, onChange: setTab }),
        meaningfulErrors.length ? h("div", { className: "hx-warning" }, "Some Hermes state could not be loaded. Open Overview for details.") : null,
        error ? h("div", { className: "hx-toast hx-error", role: "alert" }, h("span", null, error), h("button", { onClick: function () { setError(""); } }, "×")) : null,
        notice ? h("div", { className: "hx-toast hx-notice", role: "status" }, h("span", null, notice), h("button", { onClick: function () { setNotice(""); } }, "×")) : null
      );
    }

    function Overview() {
      if (coreLoading && !management) return h(LoadingBlock, null, "Loading Management Center…");
      const c = (management && management.counts) || {};
      const tc = (management && management.task_counts) || {};
      const wh = wechatHealth || {};
      const healthKind = wh.status === "healthy" ? "ok" : wh.status === "degraded" ? "warning" : wh.status === "failed" ? "failed" : "paused";
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-stats" }, h(Stat, { label: "Agents", value: c.agents }), h(Stat, { label: "Running agents", value: c.running_agents }), h(Stat, { label: "Projects", value: projectSupported ? c.projects : "—" }), h(Stat, { label: "Scheduled", value: tc.cron }), h(Stat, { label: "Running tasks", value: tc.running }), h(Stat, { label: "Failed", value: tc.failed })),
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "WeChat Desktop"), h("div", { className: "hx-muted" }, "Gateway polling health; no UI focus is taken here.")), h(Pill, { kind: healthKind }, wh.status || "unknown")), h("div", { className: "hx-kv" }, h("span", null, "Last success"), h("strong", null, fmt(wh.last_success_at)), h("span", null, "Failures"), h("strong", null, wh.consecutive_failures == null ? "—" : String(wh.consecutive_failures)), h("span", null, "Last error"), h("strong", null, wh.last_error || "—")), h("button", { className: "hx-button secondary", onClick: function () { setTab("wechat"); } }, "Open WeChat status")),
          projectSupported ? h(Card, null, h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native Hermes Projects")), h("button", { className: "hx-button", onClick: function () { setProjectModal(true); setTab("projects"); } }, "+ Project")), projects.filter(function (p) { return !p.archived; }).slice(0, 6).map(function (p) { return h("button", { className: "hx-list-row hx-row-button", key: p.profile + ":" + p.slug, onClick: function () { openProject(p); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, p.name || p.slug), h("div", { className: "hx-muted" }, p.primary_path || "No primary folder")), p.active ? h(Pill, { kind: "ok" }, "active") : null); })) : h(Card, { className: "hx-unsupported" }, h("h2", null, "Projects unavailable"), h("p", null, "This Hermes build does not expose the native `hermes project` command. Agents, Tasks and WeChat remain fully available."), h("div", { className: "hx-muted" }, "Upgrade Hermes later and refresh capabilities to enable this section."))
        ),
        meaningfulErrors.length ? h(Card, null, h("h2", null, "Partial load errors"), meaningfulErrors.map(function (row, i) { return h("div", { className: "hx-error-row", key: i }, h("strong", null, row.scope), h("span", null, row.message)); })) : null,
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Agents"), h("button", { className: "hx-button", onClick: function () { setAgentModal(true); setTab("agents"); } }, "+ Agent")), agents.slice(0, 8).map(function (a) { return h("button", { className: "hx-list-row hx-row-button", key: a.name, onClick: function () { openAgent(a.name); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, a.display_name || a.name), h("div", { className: "hx-muted" }, a.description || a.workspace || "No description")), h(Pill, { kind: String(a.gateway).toLowerCase().startsWith("running") ? "ok" : "paused" }, a.gateway || "unknown")); })),
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Next 7 days"), h("button", { className: "hx-button secondary", onClick: function () { setTab("tasks"); } }, "Open Tasks")), ((management && management.upcoming) || []).length ? (management.upcoming || []).slice(0, 10).map(function (t, i) { return h("button", { className: "hx-list-row hx-row-button", key: t.type + ":" + t.id + ":" + i, onClick: function () { openTask(t); } }, h("div", { className: "hx-time" }, fmt(t.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, t.name), h("div", { className: "hx-muted" }, t.profile || "unassigned")), h(Pill, { kind: t.type }, t.type)); }) : h(Empty, null, "No upcoming tasks."))
        )
      );
    }

    function Agents() {
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Agents"), h("div", { className: "hx-muted" }, "Hermes Profiles are isolated Agents.")), h("button", { className: "hx-button", onClick: function () { setAgentModal(true); } }, "+ Create Agent")),
        h("div", { className: "hx-toolbar" }, h(SearchBox, { value: agentSearch, onChange: setAgentSearch, placeholder: "Search name, role, workspace, model…" }), h("span", { className: "hx-muted" }, filteredAgents.length + " of " + agents.length)),
        filteredAgents.length ? h("div", { className: "hx-agent-grid" }, filteredAgents.map(function (a) { const running = String(a.gateway || "").toLowerCase().startsWith("running"); return h(Card, { key: a.name }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, a.display_name || a.name), h("div", { className: "hx-muted" }, a.name)), a.is_default ? h(Pill, { kind: "ok" }, "default") : h(Pill, { kind: running ? "ok" : "paused" }, a.gateway || "stopped")), h("p", { className: "hx-description" }, a.description || "No role description"), h("div", { className: "hx-kv" }, h("span", null, "Model"), h("strong", null, a.model || "not configured"), h("span", null, "Provider"), h("strong", null, a.provider || "—"), h("span", null, "Workspace"), h("strong", null, a.workspace || "—")), h("div", { className: "hx-actions hx-wrap" }, h("button", { className: "hx-button secondary", onClick: function () { openAgent(a.name); } }, "Manage"), !a.is_default ? h("button", { className: "hx-button secondary", onClick: function () { agentAction(a, "use", null, "Default Agent changed."); } }, "Set default") : null, running ? h("button", { className: "hx-button secondary", onClick: function () { agentAction(a, "gateway_stop", null, "Gateway stopped."); } }, "Stop") : h("button", { className: "hx-button secondary", onClick: function () { agentAction(a, "gateway_start", null, "Gateway started."); } }, "Start"), running ? h("button", { className: "hx-button secondary", onClick: function () { restartAgent(a); } }, "Restart") : null)); })) : h(Card, null, h(Empty, null, agentSearch ? "No Agents match your search." : "No Agents."))
      );
    }

    function Projects() {
      if (!projectSupported) return h("div", { className: "hx-stack" }, h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native Hermes Projects"))), h(Card, { className: "hx-unsupported" }, h("h2", null, "Native Projects unavailable"), h("p", null, "Your current Hermes installation does not expose `hermes project`. The UI intentionally disables Project creation instead of letting actions fail with 409."), h("button", { className: "hx-button secondary", onClick: async function () { try { await request("/capabilities?refresh=true"); await loadCore(); } catch (e) { setError(errText(e)); } } }, "Refresh capabilities")));
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native multi-folder Hermes workspaces.")), h("button", { className: "hx-button", onClick: function () { setProjectModal(true); } }, "+ Create Project")),
        h("div", { className: "hx-toolbar" }, h(SearchBox, { value: projectSearch, onChange: setProjectSearch, placeholder: "Search project, slug, profile, folder…" }), h("select", { value: projectFilter, onChange: function (e) { setProjectFilter(e.target.value); } }, h("option", { value: "active" }, "Active"), h("option", { value: "archived" }, "Archived"), h("option", { value: "all" }, "All"))),
        filteredProjects.length ? h("div", { className: "hx-agent-grid" }, filteredProjects.map(function (p) { return h(Card, { key: p.profile + ":" + p.slug }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, p.name || p.slug), h("div", { className: "hx-muted" }, p.profile + " · " + p.slug)), p.archived ? h(Pill, { kind: "paused" }, "archived") : p.active ? h(Pill, { kind: "ok" }, "active") : null), h("div", { className: "hx-kv" }, h("span", null, "Primary"), h("strong", null, p.primary_path || "—"), h("span", null, "Board"), h("strong", null, p.board || "—"), h("span", null, "Folders"), h("strong", null, String((p.folders || []).length)), h("span", null, "Workspace Agents"), h("strong", null, (p.agents || []).join(", ") || "—")), h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", onClick: function () { openProject(p); } }, "Manage"), !p.active && !p.archived ? h("button", { className: "hx-button secondary", onClick: function () { projectAction(p, "use", null, "Project activated."); } }, "Use") : null)); })) : h(Card, null, h(Empty, null, "No Projects match this view."))
      );
    }

    function Tasks() {
      if (tasksLoading && !tasks) return h(LoadingBlock, null, "Loading Tasks…");
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Tasks"), h("div", { className: "hx-muted" }, "Native Cron and Kanban across Agents.")), h("button", { className: "hx-button", onClick: function () { setTaskModal(true); } }, "+ Create Task")),
        h("div", { className: "hx-toolbar hx-wrap" }, h(SearchBox, { value: taskSearch, onChange: setTaskSearch, placeholder: "Search tasks…" }), h("select", { value: taskProfile, onChange: function (e) { setTaskProfile(e.target.value); } }, h("option", { value: "" }, "All Agents"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); })), h("select", { value: taskTypeFilter, onChange: function (e) { setTaskTypeFilter(e.target.value); } }, h("option", { value: "all" }, "Cron + Kanban"), h("option", { value: "cron" }, "Cron"), h("option", { value: "kanban" }, "Kanban")), h("select", { value: taskRange, onChange: function (e) { setTaskRange(Number(e.target.value)); } }, h("option", { value: 24 }, "24 hours"), h("option", { value: 168 }, "7 days"), h("option", { value: 720 }, "30 days")), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: includeCompleted, onChange: function (e) { setIncludeCompleted(e.target.checked); } }), " Show completed")),
        h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Upcoming"), tasksLoading ? h("span", { className: "hx-muted" }, "Refreshing…") : null), upcoming.length ? upcoming.slice(0, 30).map(function (u, i) { return h("button", { className: "hx-list-row hx-row-button", key: "u:" + u.type + ":" + u.id + ":" + i, onClick: function () { const found = taskRows.find(function (r) { return r.id === u.id && r.type === u.type && (!u.profile || r.profile === u.profile); }); openTask(found || u); } }, h("div", { className: "hx-time" }, fmt(u.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, u.name), h("div", { className: "hx-muted" }, u.profile || "unassigned")), h(Pill, { kind: u.type }, u.type)); }) : h(Empty, null, "No upcoming tasks in this range.")),
        filteredTasks.length ? h("div", { className: "hx-agent-grid" }, filteredTasks.map(function (t) { return h(Card, { key: (t.profile || "") + ":" + t.type + ":" + t.id }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, t.name || t.id), h("div", { className: "hx-muted" }, (t.profile || "unassigned") + " · " + t.type)), h(Pill, { kind: t.type }, t.type)), h("div", { className: "hx-kv" }, h("span", null, "Schedule"), h("strong", null, t.type === "cron" ? (t.schedule || "—") : "—"), h("span", null, "Status"), h("strong", null, t.status || (t.enabled === false ? "paused" : "active")), h("span", null, "Next run"), h("strong", null, fmt(t.next_run_at))), h("button", { className: "hx-button secondary", onClick: function () { openTask(t); } }, "Manage")); })) : h(Card, null, h(Empty, null, "No Tasks match your filters."))
      );
    }

    function WeChat() {
      const wh = wechatHealth || {};
      const ws = wechatStatus || {};
      const healthKind = wh.status === "healthy" ? "ok" : wh.status === "degraded" ? "warning" : wh.status === "failed" ? "failed" : "paused";
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "WeChat Desktop"), h("div", { className: "hx-muted" }, "Local Windows UI Automation status and safe test tools.")), h("button", { className: "hx-button secondary", disabled: wechatLoading, onClick: function () { loadWeChat(true); } }, wechatLoading ? "Checking…" : "Check desktop")),
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Gateway health"), h(Pill, { kind: healthKind }, wh.status || "unknown")), h("div", { className: "hx-kv" }, h("span", null, "Last success"), h("strong", null, fmt(wh.last_success_at)), h("span", null, "Failures"), h("strong", null, wh.consecutive_failures == null ? "—" : String(wh.consecutive_failures)), h("span", null, "Last error"), h("strong", null, wh.last_error || "—"), h("span", null, "Updated"), h("strong", null, fmt(wh.updated_at)))),
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Desktop connection"), h(Pill, { kind: ws.available ? "ok" : "failed" }, ws.available == null ? "not checked" : ws.available ? "available" : "unavailable")), h("div", { className: "hx-kv" }, h("span", null, "Window"), h("strong", null, ws.window_title || "—"), h("span", null, "Backend"), h("strong", null, ws.backend || ws.transport || "—"), h("span", null, "Fail closed"), h("strong", null, ws.fail_closed_send === false ? "No" : "Yes"), h("span", null, "Reason"), h("strong", null, ws.reason || "—")))
        ),
        h("div", { className: "hx-two-col" },
          h(Card, null, h("h2", null, "Unread chats"), wechatUnread.length ? wechatUnread.map(function (c) { return h("div", { className: "hx-list-row", key: c.name }, h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, c.name), h("div", { className: "hx-muted" }, c.preview || "Unread")), h(Pill, { kind: "warning" }, "unread")); }) : h(Empty, null, wechatStatus ? "No unread chats detected." : "Run Check desktop to load chats.")),
          h(Card, null, h("h2", null, "Recent chats"), wechatChats.length ? wechatChats.slice(0, 20).map(function (c) { return h("button", { className: "hx-list-row hx-row-button", key: c.name, onClick: function () { setWechatDryRun(Object.assign({}, wechatDryRun, { chat: c.name })); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, c.name), h("div", { className: "hx-muted" }, c.preview || "—")), c.unread ? h(Pill, { kind: "warning" }, "unread") : null); }) : h(Empty, null, "No recent chats loaded."))
        ),
        h(Card, { className: "hx-safe-test" }, h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Safe dry-run test"), h("div", { className: "hx-muted" }, "Locates and verifies the exact conversation, types the text, then clears it. Enter is never pressed.")), h(Pill, { kind: "ok" }, "NO SEND")), h("form", { className: "hx-form", onSubmit: runWeChatDryRun }, Field("Exact chat name", h("input", { required: true, value: wechatDryRun.chat, onChange: function (e) { setWechatDryRun(Object.assign({}, wechatDryRun, { chat: e.target.value })); } })), Field("Test text", h("textarea", { rows: 3, required: true, value: wechatDryRun.text, onChange: function (e) { setWechatDryRun(Object.assign({}, wechatDryRun, { text: e.target.value })); } })), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "wechat-dry-run" }, busy === "wechat-dry-run" ? "Testing…" : "Run dry test"))))
      );
    }

    function AgentDetail() {
      if (!agentDetail) return null;
      const a = agentDetail;
      const running = String(a.gateway || "").toLowerCase().startsWith("running");
      return h(Dialog, { open: true, title: "Agent · " + (a.display_name || a.name), subtitle: "Native Hermes Profile", locked: Boolean(busy), onClose: function () { setAgentDetail(null); } },
        h("form", { className: "hx-form", onSubmit: saveAgent },
          Field("Profile name", h("input", { value: a.edit_name == null ? a.name : a.edit_name, disabled: a.name === "default", onChange: function (e) { setAgentDetail(Object.assign({}, a, { edit_name: e.target.value })); } })),
          Field("Description / role", h("textarea", { rows: 3, value: a.description || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { description: e.target.value })); } })),
          Field("Workspace", h("input", { value: a.workspace || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { workspace: e.target.value })); } })),
          Field("Provider", h("input", { value: a.provider || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { provider: e.target.value })); } })),
          Field("Model", h("input", { value: a.model || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { model: e.target.value })); } })),
          Field("Gateway", h("input", { value: a.gateway || "unknown", readOnly: true })),
          Field("SOUL.md", h("textarea", { rows: 12, value: a.soul || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { soul: e.target.value })); } }), "Saved directly into this validated Profile's SOUL.md."),
          h("div", { className: "hx-actions hx-span-2 hx-wrap" }, h("button", { className: "hx-button", type: "submit", disabled: Boolean(busy) }, "Save"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "gateway_status", null, "Gateway status refreshed."); } }, "Check gateway"), running ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "gateway_stop", null, "Gateway stopped."); } }, "Stop") : h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "gateway_start", null, "Gateway started."); } }, "Start"), running ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { restartAgent(a); } }, "Restart") : null, h("button", { className: "hx-button secondary", type: "button", onClick: function () { agentAction(a, "export", null, function (r) { return "Agent exported" + (r && r.path ? " to " + r.path : "."); }); } }, "Export"), a.name !== "default" ? h("button", { className: "hx-button danger", type: "button", onClick: function () { deleteAgent(a); } }, "Delete") : null)
        ))
      );
    }

    function ProjectDetail() {
      if (!projectDetail) return null;
      const p = projectDetail;
      return h(Dialog, { open: true, title: "Project · " + (p.name || p.slug), subtitle: p.profile + " · " + p.slug, locked: Boolean(busy), onClose: function () { setProjectDetail(null); setProjectFolderInput(""); } },
        h("form", { className: "hx-form", onSubmit: saveProject }, Field("Name", h("input", { value: p.name || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { name: e.target.value })); } })), Field("Primary folder", h("input", { value: p.primary_path || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { primary_path: e.target.value })); } })), Field("Kanban board", h("input", { value: p.board || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { board: e.target.value })); } }), "Leave blank and save/bind to clear when supported by Hermes."), h("div", { className: "hx-actions hx-span-2 hx-wrap" }, h("button", { className: "hx-button", type: "submit" }, "Save"), !p.active && !p.archived ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "use", null, "Project activated."); } }, "Use project") : null, p.archived ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "restore", null, "Project restored."); } }, "Restore") : h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "archive", null, "Project archived."); } }, "Archive"))),
        h("div", { className: "hx-detail-section" }, h("div", { className: "hx-section-head" }, h("h3", null, "Folders"), h("div", { className: "hx-inline-add" }, h("input", { placeholder: "Folder path", value: projectFolderInput, onChange: function (e) { setProjectFolderInput(e.target.value); } }), h("button", { className: "hx-button secondary", type: "button", disabled: !projectFolderInput.trim(), onClick: async function () { const value = projectFolderInput.trim(); await projectAction(p, "add_folder", value, "Folder added."); setProjectFolderInput(""); } }, "Add"))), (p.folders || []).length ? (p.folders || []).map(function (f) { return h("div", { className: "hx-list-row", key: f.path }, h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, f.path), f.label ? h("div", { className: "hx-muted" }, f.label) : null), f.is_primary ? h(Pill, { kind: "ok" }, "primary") : h("button", { className: "hx-button secondary", type: "button", onClick: function () { projectAction(p, "set_primary", f.path, "Primary folder updated."); } }, "Set primary"), !f.is_primary ? h("button", { className: "hx-button danger ghost", type: "button", onClick: function () { if (confirm("Remove folder from project?\n" + f.path)) projectAction(p, "remove_folder", f.path, "Folder removed."); } }, "Remove") : null); }) : h(Empty, null, "No folders.")),
        h("div", { className: "hx-detail-section" }, h("h3", null, "Workspace Agents"), h("div", { className: "hx-muted" }, (p.agents || []).join(", ") || "None. Assignment sets the Agent terminal.cwd to this Project's primary folder."), h("select", { defaultValue: "", onChange: function (e) { if (e.target.value) projectAction(p, "assign_agent", e.target.value, "Workspace Agent assigned."); } }, h("option", { value: "" }, "Assign workspace Agent…"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); })))
      );
    }

    function TaskDetail() {
      if (!taskDetail) return null;
      const t = taskDetail;
      return h(Dialog, { open: true, title: "Task · " + (t.name || t.id), subtitle: (t.profile || "unassigned") + " · " + t.type, locked: Boolean(busy), onClose: function () { setTaskDetail(null); setHistory([]); } },
        h("form", { className: "hx-form", onSubmit: saveTask }, Field("Name", h("input", { value: t.name || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { name: e.target.value })); } })), Field("Agent/Profile", h("select", { value: t.profile || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { profile: e.target.value })); } }, h("option", { value: "" }, "Unassigned/default"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field(t.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 5, value: t.prompt || t.body || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { prompt: e.target.value })); } })), t.type === "cron" ? Field("Schedule", h("input", { value: t.schedule || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { schedule: e.target.value })); } })) : Field("Priority", h("input", { type: "number", min: 0, max: 100, value: t.priority == null ? 50 : t.priority, onChange: function (e) { setTaskDetail(Object.assign({}, t, { priority: Number(e.target.value) })); } })), h("div", { className: "hx-actions hx-span-2 hx-wrap" }, h("button", { className: "hx-button", type: "submit" }, "Save"), t.type === "cron" ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { taskAction(t, t.enabled === false ? "resume" : "pause", null, t.enabled === false ? "Task resumed." : "Task paused."); } }, t.enabled === false ? "Resume" : "Pause") : null, t.type === "cron" ? h("button", { className: "hx-button secondary", type: "button", onClick: function () { taskAction(t, "run", null, "Task started."); } }, "Run now") : null, t.type === "cron" ? h("button", { className: "hx-button danger", type: "button", onClick: function () { taskAction(t, "remove"); } }, "Delete") : h("button", { className: "hx-button danger", type: "button", onClick: function () { taskAction(t, "archive"); } }, "Archive"))),
        h("div", { className: "hx-detail-section" }, h("h3", null, "Execution history"), historyLoading ? h(LoadingBlock, null, "Loading history…") : history.length ? history.map(function (row, i) { return h("div", { className: "hx-history-row", key: i }, h(Pill, { kind: row.status || row.state || "" }, row.status || row.state || "record"), h("div", { className: "hx-grow" }, fmt(row.claimed_at || row.started_at || row.completed_at || row.updated_at)), row.error ? h("div", { className: "hx-muted" }, row.error) : null); }) : h(Empty, null, "No execution history."))
      );
    }

    function AgentModal() {
      return h(Dialog, { open: agentModal, title: "Create Agent", subtitle: "Create a native Hermes Profile", locked: busy === "agent-create", onClose: function () { setAgentModal(false); } }, h("form", { className: "hx-form", onSubmit: createAgent }, Field("Name", h("input", { required: true, pattern: "[a-z0-9][a-z0-9_-]{0,63}", value: agentForm.name, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { name: e.target.value.toLowerCase() })); } })), Field("Description / role", h("textarea", { rows: 3, value: agentForm.description, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { description: e.target.value })); } })), Field("Clone mode", h("select", { value: agentForm.clone_mode, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_mode: e.target.value })); } }, h("option", { value: "blank" }, "Blank"), h("option", { value: "clone" }, "Clone config"), h("option", { value: "clone_all" }, "Clone all state"))), agentForm.clone_mode !== "blank" ? Field("Clone from", h("select", { value: agentForm.clone_from, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_from: e.target.value })); } }, h("option", { value: "" }, "Active/default source"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))) : null, Field("Workspace", h("input", { value: agentForm.workspace, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { workspace: e.target.value })); } })), Field("Provider", h("input", { value: agentForm.provider, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { provider: e.target.value })); } })), Field("Model", h("input", { value: agentForm.model, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { model: e.target.value })); } })), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: agentForm.no_skills, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { no_skills: e.target.checked })); } }), " Create without bundled skills"), Field("Initial SOUL.md", h("textarea", { rows: 8, value: agentForm.soul, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { soul: e.target.value })); } })), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "agent-create" }, busy === "agent-create" ? "Creating…" : "Create Agent"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setAgentModal(false); } }, "Cancel"))));
    }

    function ProjectModal() {
      return h(Dialog, { open: projectModal && projectSupported, title: "Create Project", subtitle: "Create a native Hermes Project", locked: busy === "project-create", onClose: function () { setProjectModal(false); } }, h("form", { className: "hx-form", onSubmit: createProject }, Field("Name", h("input", { required: true, value: projectForm.name, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { name: e.target.value })); } })), Field("Slug", h("input", { value: projectForm.slug, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { slug: e.target.value })); } })), Field("Profile owner", h("select", { value: projectForm.profile, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Workspace Agent", h("select", { value: projectForm.agent, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { agent: e.target.value })); } }, h("option", { value: "" }, "None"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Folders (comma/newline)", h("textarea", { rows: 4, value: projectForm.folders, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { folders: e.target.value })); } })), Field("Primary folder", h("input", { value: projectForm.primary, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { primary: e.target.value })); } })), Field("Description", h("textarea", { rows: 3, value: projectForm.description, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { description: e.target.value })); } })), Field("Board", h("input", { value: projectForm.board, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { board: e.target.value })); } })), Field("Icon", h("input", { value: projectForm.icon, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { icon: e.target.value })); } })), Field("Color", h("input", { value: projectForm.color, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { color: e.target.value })); } })), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: projectForm.use, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { use: e.target.checked })); } }), " Use this Project after creation"), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "project-create" }, busy === "project-create" ? "Creating…" : "Create Project"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setProjectModal(false); } }, "Cancel"))));
    }

    function TaskModal() {
      return h(Dialog, { open: taskModal, title: "Create Task", subtitle: "Native Cron or Kanban", locked: busy === "task-create", onClose: function () { setTaskModal(false); } }, h("form", { className: "hx-form", onSubmit: createTask }, Field("Type", h("select", { value: taskForm.type, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { type: e.target.value })); } }, h("option", { value: "cron" }, "Cron"), h("option", { value: "kanban" }, "Kanban"))), Field("Name", h("input", { required: true, value: taskForm.name, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { name: e.target.value })); } })), Field("Agent/Profile", h("select", { value: taskForm.profile, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), taskForm.type === "cron" ? Field("Deliver", h("input", { value: taskForm.deliver, placeholder: "local / wechat_desktop / …", onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { deliver: e.target.value })); } })) : Field("Priority", h("input", { type: "number", min: 0, max: 100, value: taskForm.priority, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { priority: Number(e.target.value) })); } })), Field(taskForm.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 6, required: taskForm.type === "cron", value: taskForm.prompt, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { prompt: e.target.value })); } })), taskForm.type === "cron" ? Field("Schedule", h("input", { required: true, value: taskForm.schedule, placeholder: "every 10m or cron expression", onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { schedule: e.target.value })); } })) : null, h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busy === "task-create" }, busy === "task-create" ? "Creating…" : "Create Task"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setTaskModal(false); } }, "Cancel"))));
    }

    return h("div", { className: "hx-page" }, h(Header), tab === "overview" ? h(Overview) : tab === "agents" ? h(Agents) : tab === "projects" ? h(Projects) : tab === "tasks" ? h(Tasks) : h(WeChat), h(AgentDetail), h(ProjectDetail), h(TaskDetail), h(AgentModal), h(ProjectModal), h(TaskModal));
  }

  window.__HERMES_PLUGINS__.register("hermes-extensions", ManagementApp);
})();
