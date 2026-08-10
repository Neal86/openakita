(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !SDK.React || !window.__HERMES_PLUGINS__) return;
  const React = SDK.React;
  const h = React.createElement;
  const { useCallback, useEffect, useMemo, useState } = React;
  const fetchJSON = SDK.fetchJSON;
  const API = "/api/plugins/hermes-extensions";
  const PREFS_KEY = "hermes-extensions.task-center.prefs";

  function request(path, init) {
    const options = Object.assign({}, init || {});
    if (options.body && !options.headers) options.headers = { "Content-Type": "application/json" };
    return fetchJSON(API + path, options);
  }

  function fmt(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  function loadPrefs() {
    try { return JSON.parse(window.localStorage.getItem(PREFS_KEY) || "{}"); }
    catch (_) { return {}; }
  }

  function savePrefs(value) {
    try { window.localStorage.setItem(PREFS_KEY, JSON.stringify(value)); }
    catch (_) { /* localStorage is optional */ }
  }

  function Card(props) { return h("div", { className: "hx-card " + (props.className || "") }, props.children); }
  function Pill(props) { return h("span", { className: "hx-pill " + (props.kind || "") }, props.children); }
  function Stat(props) { return h(Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(props.value || 0)), h("div", { className: "hx-muted" }, props.label)); }
  function field(label, child) { return h("label", null, label, child); }

  function TaskCenterPage() {
    const prefs = useMemo(loadPrefs, []);
    const [overview, setOverview] = useState(null);
    const [upcoming, setUpcoming] = useState([]);
    const [profile, setProfile] = useState(prefs.profile || "");
    const [range, setRange] = useState(Number(prefs.range) || 168);
    const [includeCompleted, setIncludeCompleted] = useState(Boolean(prefs.includeCompleted));
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [formOpen, setFormOpen] = useState(false);
    const [form, setForm] = useState({ type: "cron", name: "", prompt: "", schedule: "", profile: "", priority: 50, deliver: "local" });
    const [selected, setSelected] = useState(null);
    const [history, setHistory] = useState([]);
    const [detailLoading, setDetailLoading] = useState(false);
    const [edit, setEdit] = useState(null);
    const [busyKey, setBusyKey] = useState("");

    useEffect(function () {
      savePrefs({ profile: profile, range: range, includeCompleted: includeCompleted });
    }, [profile, range, includeCompleted]);

    const load = useCallback(async function () {
      setLoading(true); setError("");
      try {
        const params = new URLSearchParams();
        if (profile) params.set("profile", profile);
        if (includeCompleted) params.set("include_completed", "true");
        const data = await request("/overview" + (params.toString() ? "?" + params.toString() : ""));
        const upcomingParams = new URLSearchParams({ hours: String(range) });
        if (profile) upcomingParams.set("profile", profile);
        const future = await request("/upcoming?" + upcomingParams.toString());
        setOverview(data); setUpcoming(future.items || []);
      } catch (err) { setError(err.message || String(err)); }
      finally { setLoading(false); }
    }, [profile, range, includeCompleted]);

    useEffect(function () { load(); }, [load]);

    const profileNames = useMemo(function () {
      const rows = (overview && overview.profiles) || [];
      return rows.map(function (row) { return row.name; }).filter(Boolean);
    }, [overview]);

    async function createTask(event) {
      event.preventDefault(); setError(""); setNotice(""); setBusyKey("create");
      try {
        const payload = Object.assign({}, form);
        if (payload.type === "kanban") { delete payload.schedule; delete payload.deliver; }
        if (!payload.profile) delete payload.profile;
        await request("/tasks", { method: "POST", body: JSON.stringify(payload) });
        setFormOpen(false);
        setForm({ type: "cron", name: "", prompt: "", schedule: "", profile: "", priority: 50, deliver: "local" });
        setNotice("Task saved in Hermes.");
        await load();
      } catch (err) { setError(err.message || String(err)); }
      finally { setBusyKey(""); }
    }

    async function action(type, id, verb, ownerProfile) {
      const key = type + ":" + id + ":" + verb;
      setError(""); setNotice(""); setBusyKey(key);
      try {
        await request("/tasks/" + encodeURIComponent(type) + "/" + encodeURIComponent(id) + "/action", {
          method: "POST", body: JSON.stringify({ action: verb, profile: ownerProfile || null })
        });
        if (selected && selected.type === type && selected.id === id && (verb === "remove" || verb === "archive")) {
          setSelected(null); setHistory([]); setEdit(null);
        }
        setNotice(verb.charAt(0).toUpperCase() + verb.slice(1) + " completed.");
        await load();
      } catch (err) { setError(err.message || String(err)); }
      finally { setBusyKey(""); }
    }

    async function openDetails(task) {
      setSelected(task);
      setEdit({
        name: task.name || "",
        prompt: task.prompt || task.body || "",
        schedule: task.schedule || "",
        profile: task.profile || "",
        priority: task.priority == null ? 50 : Number(task.priority)
      });
      setHistory([]); setDetailLoading(true); setError(""); setNotice("");
      try {
        const q = task.profile ? "?profile=" + encodeURIComponent(task.profile) + "&limit=30" : "?limit=30";
        const data = await request("/tasks/" + encodeURIComponent(task.type) + "/" + encodeURIComponent(task.id) + "/history" + q);
        setHistory(data.items || []);
      } catch (err) { setError(err.message || String(err)); }
      finally { setDetailLoading(false); }
    }

    async function saveDetails(event) {
      event.preventDefault();
      if (!selected || !edit) return;
      setError(""); setNotice(""); setBusyKey("save:" + selected.type + ":" + selected.id);
      try {
        const payload = selected.type === "cron"
          ? { name: edit.name, prompt: edit.prompt, schedule: edit.schedule, profile: selected.profile || edit.profile }
          : { name: edit.name, prompt: edit.prompt, priority: Number(edit.priority), profile: edit.profile };
        await request("/tasks/" + encodeURIComponent(selected.type) + "/" + encodeURIComponent(selected.id), {
          method: "PATCH", body: JSON.stringify(payload)
        });
        await load();
        setSelected(Object.assign({}, selected, payload));
        setNotice("Task changes saved.");
      } catch (err) { setError(err.message || String(err)); }
      finally { setBusyKey(""); }
    }

    const counts = (overview && overview.counts) || {};
    const profiles = (overview && overview.profiles) || [];

    return h("div", { className: "hx-page" },
      h("div", { className: "hx-header" },
        h("div", null, h("h1", null, "Hermes Task Center"), h("div", { className: "hx-muted" }, "All agents · fixed tasks · upcoming work · Cron · Kanban")),
        h("div", { className: "hx-actions" },
          h("button", { className: "hx-button secondary", onClick: load, disabled: loading || Boolean(busyKey) }, loading ? "Refreshing…" : "Refresh"),
          h("button", { className: "hx-button", onClick: function () { setFormOpen(!formOpen); }, disabled: Boolean(busyKey) }, formOpen ? "Close" : "+ Add task")
        )
      ),
      error ? h("div", { className: "hx-error" }, error) : null,
      notice ? h("div", { className: "hx-notice" }, notice) : null,
      overview && overview.kanban_error ? h("div", { className: "hx-error" }, "Kanban unavailable: " + overview.kanban_error) : null,
      h("div", { className: "hx-stats" },
        h(Stat, { label: "Agents", value: counts.profiles }),
        h(Stat, { label: "Running", value: counts.running }),
        h(Stat, { label: "Scheduled", value: counts.cron }),
        h(Stat, { label: "Recurring", value: counts.recurring }),
        h(Stat, { label: "One-shot", value: counts.one_shot }),
        h(Stat, { label: "Kanban", value: counts.kanban })
      ),
      formOpen ? h(Card, { className: "hx-form-card" },
        h("form", { onSubmit: createTask, className: "hx-form" },
          h("h2", null, "Add task directly to Hermes"),
          field("Type", h("select", { value: form.type, onChange: function (e) { setForm(Object.assign({}, form, { type: e.target.value })); } },
            h("option", { value: "cron" }, "Scheduled / recurring"), h("option", { value: "kanban" }, "Kanban task"))),
          field("Name", h("input", { required: true, value: form.name, onChange: function (e) { setForm(Object.assign({}, form, { name: e.target.value })); } })),
          field(form.type === "cron" ? "Prompt" : "Task details", h("textarea", { required: form.type === "cron", rows: 4, value: form.prompt, onChange: function (e) { setForm(Object.assign({}, form, { prompt: e.target.value })); } })),
          form.type === "cron" ? field("Schedule", h("input", { required: true, placeholder: "every 10m | 0 9 * * * | 2026-08-11T09:00:00", value: form.schedule, onChange: function (e) { setForm(Object.assign({}, form, { schedule: e.target.value })); } })) : null,
          field(form.type === "cron" ? "Profile" : "Assignee", h("input", { list: "hx-profile-list", placeholder: "default / support / warehouse", value: form.profile, onChange: function (e) { setForm(Object.assign({}, form, { profile: e.target.value })); } })),
          h("datalist", { id: "hx-profile-list" }, profileNames.map(function (p) { return h("option", { key: p, value: p }); })),
          form.type === "cron" ? field("Delivery", h("input", { value: form.deliver, onChange: function (e) { setForm(Object.assign({}, form, { deliver: e.target.value })); } })) : field("Priority", h("input", { type: "number", min: 0, max: 100, value: form.priority, onChange: function (e) { setForm(Object.assign({}, form, { priority: Number(e.target.value) })); } })),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: busyKey === "create" }, busyKey === "create" ? "Saving…" : "Save in Hermes"))
        )) : null,
      h(Card, null,
        h("div", { className: "hx-toolbar" },
          h("div", null, h("strong", null, "Upcoming"), h("span", { className: "hx-muted" }, " · recurring jobs expanded into actual future occurrences")),
          h("div", { className: "hx-actions" },
            h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: includeCompleted, onChange: function (e) { setIncludeCompleted(e.target.checked); } }), " Show completed"),
            h("select", { value: profile, onChange: function (e) { setProfile(e.target.value); } }, h("option", { value: "" }, "All agents"), profileNames.map(function (p) { return h("option", { key: p, value: p }, p); })),
            h("select", { value: range, onChange: function (e) { setRange(Number(e.target.value)); } }, h("option", { value: 24 }, "24 hours"), h("option", { value: 168 }, "7 days"), h("option", { value: 720 }, "30 days"))
          )
        ),
        h("div", { className: "hx-upcoming" }, upcoming.length ? upcoming.map(function (item, index) {
          return h("button", { type: "button", className: "hx-upcoming-row hx-row-button", key: item.type + ":" + item.id + ":" + item.at + ":" + index, onClick: function () {
            const found = profiles.flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); }).find(function (t) { return t.type === item.type && t.id === item.id && (!item.profile || t.profile === item.profile); });
            if (found) openDetails(found);
          } },
            h("div", { className: "hx-time" }, fmt(item.at)),
            h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, item.name), h("div", { className: "hx-muted" }, (item.profile || "unassigned") + (item.schedule ? " · " + item.schedule : ""))),
            h(Pill, { kind: item.type }, item.type), item.recurring ? h(Pill, { kind: "recurring" }, "recurring") : null
          );
        }) : h("div", { className: "hx-empty" }, loading ? "Loading upcoming tasks…" : "No upcoming tasks in this range."))
      ),
      h("div", { className: "hx-agent-grid" }, profiles.map(function (agent) {
        return h(Card, { key: agent.name },
          h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, agent.name), h("div", { className: "hx-muted" }, (agent.cron || []).length + " fixed/scheduled · " + (agent.kanban || []).length + " kanban"))),
          (agent.cron || []).length ? h("div", null, h("h3", null, "Fixed / scheduled tasks"), (agent.cron || []).map(function (job) {
            return h("div", { className: "hx-task", key: "cron:" + job.profile + ":" + job.id },
              h("button", { type: "button", className: "hx-grow hx-task-open", onClick: function () { openDetails(job); } }, h("div", { className: "hx-title" }, job.name), h("div", { className: "hx-muted" }, String(job.schedule || "") + " · next " + fmt(job.next_run_at))),
              h(Pill, { kind: job.enabled ? "ok" : "paused" }, job.enabled ? "active" : "paused"),
              h("div", { className: "hx-mini-actions" },
                job.enabled ? h("button", { disabled: Boolean(busyKey), onClick: function () { action("cron", job.id, "pause", job.profile); } }, busyKey === "cron:" + job.id + ":pause" ? "Pausing…" : "Pause") : h("button", { disabled: Boolean(busyKey), onClick: function () { action("cron", job.id, "resume", job.profile); } }, busyKey === "cron:" + job.id + ":resume" ? "Resuming…" : "Resume"),
                h("button", { disabled: Boolean(busyKey), onClick: function () { action("cron", job.id, "run", job.profile); } }, busyKey === "cron:" + job.id + ":run" ? "Running…" : "Run")
              )
            );
          })) : null,
          (agent.kanban || []).length ? h("div", null, h("h3", null, "Kanban work"), (agent.kanban || []).map(function (task) {
            return h("button", { type: "button", className: "hx-task hx-row-button", key: "kanban:" + task.id, onClick: function () { openDetails(task); } },
              h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, task.name), h("div", { className: "hx-muted" }, task.status || "task")),
              task.next_run_at ? h("div", { className: "hx-muted" }, fmt(task.next_run_at)) : null
            );
          })) : null,
          !(agent.cron || []).length && !(agent.kanban || []).length ? h("div", { className: "hx-empty" }, "No assigned tasks.") : null
        );
      })),
      selected && edit ? h(Card, { className: "hx-detail" },
        h("div", { className: "hx-header" }, h("div", null, h("h2", null, "Task details"), h("div", { className: "hx-muted" }, selected.type + " · " + selected.id + " · " + (selected.profile || "unassigned"))), h("button", { className: "hx-button secondary", onClick: function () { setSelected(null); setHistory([]); setEdit(null); } }, "Close")),
        h("form", { className: "hx-form hx-detail-form", onSubmit: saveDetails },
          field("Name", h("input", { value: edit.name, onChange: function (e) { setEdit(Object.assign({}, edit, { name: e.target.value })); } })),
          field(selected.type === "cron" ? "Profile" : "Assignee", h("input", { value: edit.profile, disabled: selected.type === "cron", onChange: function (e) { setEdit(Object.assign({}, edit, { profile: e.target.value })); } })),
          field(selected.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 5, value: edit.prompt, onChange: function (e) { setEdit(Object.assign({}, edit, { prompt: e.target.value })); } })),
          selected.type === "cron" ? field("Schedule", h("input", { value: edit.schedule, onChange: function (e) { setEdit(Object.assign({}, edit, { schedule: e.target.value })); } })) : field("Priority", h("input", { type: "number", min: 0, max: 100, value: edit.priority, onChange: function (e) { setEdit(Object.assign({}, edit, { priority: Number(e.target.value) })); } })),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit", disabled: Boolean(busyKey) }, busyKey.indexOf("save:") === 0 ? "Saving…" : "Save changes"), selected.type === "cron" ? h("button", { className: "hx-button danger", type: "button", disabled: Boolean(busyKey), onClick: function () { if (window.confirm("Remove this Hermes Cron task?")) action("cron", selected.id, "remove", selected.profile); } }, "Remove") : h("button", { className: "hx-button danger", type: "button", disabled: Boolean(busyKey), onClick: function () { if (window.confirm("Archive this Hermes Kanban task?")) action("kanban", selected.id, "archive", selected.profile); } }, "Archive"))
        ),
        h("h3", null, "Execution history"),
        detailLoading ? h("div", { className: "hx-empty" }, "Loading history…") : history.length ? h("div", { className: "hx-history" }, history.map(function (row, index) {
          const status = row.status || row.state || (row.completed_at ? "completed" : "record");
          const when = row.claimed_at || row.started_at || row.completed_at || row.updated_at || row.created_at;
          return h("div", { className: "hx-history-row", key: String(row.id || index) },
            h(Pill, { kind: status === "failed" ? "failed" : status }, status),
            h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, fmt(when)), row.error ? h("div", { className: "hx-error-text" }, String(row.error)) : row.result ? h("div", { className: "hx-muted hx-pre" }, typeof row.result === "string" ? row.result : JSON.stringify(row.result)) : null)
          );
        })) : h("div", { className: "hx-empty" }, "No execution history yet.")
      ) : null
    );
  }

  window.__HERMES_PLUGINS__.register("hermes-extensions", TaskCenterPage);
})();
