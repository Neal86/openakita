(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const React = SDK && SDK.React;
  if (!React || !window.__HERMES_PLUGINS__) return;
  const h = React.createElement;
  const { useCallback, useEffect, useMemo, useState } = React;
  const API = "/api/plugins/hermes-extensions";

  async function request(path, options) {
    const response = await fetch(API + path, Object.assign({ headers: { "Content-Type": "application/json" } }, options || {}));
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.detail || response.statusText || "Request failed");
    return data;
  }

  function fmt(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  function Card(props) {
    return h("div", { className: "hx-card " + (props.className || "") }, props.children);
  }

  function Pill(props) {
    return h("span", { className: "hx-pill " + (props.kind || "") }, props.children);
  }

  function Stat(props) {
    return h(Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(props.value || 0)), h("div", { className: "hx-muted" }, props.label));
  }

  function TaskCenterPage() {
    const [overview, setOverview] = useState(null);
    const [upcoming, setUpcoming] = useState([]);
    const [profile, setProfile] = useState("");
    const [range, setRange] = useState(168);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [formOpen, setFormOpen] = useState(false);
    const [form, setForm] = useState({ type: "cron", name: "", prompt: "", schedule: "", profile: "", priority: 50, deliver: "local" });

    const load = useCallback(async function () {
      setLoading(true); setError("");
      try {
        const query = profile ? "?profile=" + encodeURIComponent(profile) : "";
        const data = await request("/overview" + query);
        const uq = "?hours=" + encodeURIComponent(range) + (profile ? "&profile=" + encodeURIComponent(profile) : "");
        const future = await request("/upcoming" + uq);
        setOverview(data); setUpcoming(future.items || []);
      } catch (err) { setError(err.message || String(err)); }
      finally { setLoading(false); }
    }, [profile, range]);

    useEffect(function () { load(); }, [load]);

    const profileNames = useMemo(function () {
      const rows = (overview && overview.profiles) || [];
      return rows.map(function (row) { return row.name; }).filter(Boolean);
    }, [overview]);

    async function createTask(event) {
      event.preventDefault(); setError("");
      try {
        const payload = Object.assign({}, form);
        if (payload.type === "kanban") { delete payload.schedule; delete payload.deliver; }
        if (!payload.profile) delete payload.profile;
        await request("/tasks", { method: "POST", body: JSON.stringify(payload) });
        setFormOpen(false);
        setForm({ type: "cron", name: "", prompt: "", schedule: "", profile: "", priority: 50, deliver: "local" });
        await load();
      } catch (err) { setError(err.message || String(err)); }
    }

    async function action(type, id, verb, value) {
      setError("");
      try {
        await request("/tasks/" + encodeURIComponent(type) + "/" + encodeURIComponent(id) + "/action", {
          method: "POST", body: JSON.stringify({ action: verb, value: value || null })
        });
        await load();
      } catch (err) { setError(err.message || String(err)); }
    }

    const counts = (overview && overview.counts) || {};
    const profiles = (overview && overview.profiles) || [];

    return h("div", { className: "hx-page" },
      h("div", { className: "hx-header" },
        h("div", null, h("h1", null, "Hermes Task Center"), h("div", { className: "hx-muted" }, "All profiles · Cron · Kanban · upcoming work")),
        h("div", { className: "hx-actions" },
          h("button", { className: "hx-button secondary", onClick: load, disabled: loading }, loading ? "Refreshing…" : "Refresh"),
          h("button", { className: "hx-button", onClick: function () { setFormOpen(!formOpen); } }, formOpen ? "Close" : "+ Add task")
        )
      ),
      error ? h("div", { className: "hx-error" }, error) : null,
      h("div", { className: "hx-stats" },
        h(Stat, { label: "Agents", value: counts.profiles }), h(Stat, { label: "Scheduled", value: counts.cron }),
        h(Stat, { label: "Recurring", value: counts.recurring }), h(Stat, { label: "One-shot", value: counts.one_shot }),
        h(Stat, { label: "Kanban", value: counts.kanban })
      ),
      formOpen ? h(Card, { className: "hx-form-card" },
        h("form", { onSubmit: createTask, className: "hx-form" },
          h("h2", null, "Add Hermes task"),
          h("label", null, "Type", h("select", { value: form.type, onChange: function (e) { setForm(Object.assign({}, form, { type: e.target.value })); } },
            h("option", { value: "cron" }, "Scheduled / recurring"), h("option", { value: "kanban" }, "Kanban task"))),
          h("label", null, "Name", h("input", { required: true, value: form.name, onChange: function (e) { setForm(Object.assign({}, form, { name: e.target.value })); } })),
          h("label", null, form.type === "cron" ? "Prompt" : "Task details", h("textarea", { required: form.type === "cron", rows: 4, value: form.prompt, onChange: function (e) { setForm(Object.assign({}, form, { prompt: e.target.value })); } })),
          form.type === "cron" ? h("label", null, "Schedule", h("input", { required: true, placeholder: "every 10m | 0 9 * * * | 2026-08-11T09:00:00", value: form.schedule, onChange: function (e) { setForm(Object.assign({}, form, { schedule: e.target.value })); } })) : null,
          h("label", null, form.type === "cron" ? "Profile" : "Assignee", h("input", { placeholder: "default / support / warehouse", value: form.profile, onChange: function (e) { setForm(Object.assign({}, form, { profile: e.target.value })); } })),
          form.type === "cron" ? h("label", null, "Delivery", h("input", { value: form.deliver, onChange: function (e) { setForm(Object.assign({}, form, { deliver: e.target.value })); } })) : h("label", null, "Priority", h("input", { type: "number", min: 0, max: 100, value: form.priority, onChange: function (e) { setForm(Object.assign({}, form, { priority: Number(e.target.value) })); } })),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button", type: "submit" }, "Save in Hermes"))
        )) : null,
      h(Card, null,
        h("div", { className: "hx-toolbar" },
          h("div", null, h("strong", null, "Upcoming"), h("span", { className: "hx-muted" }, " expanded recurring occurrences")),
          h("div", { className: "hx-actions" },
            h("select", { value: profile, onChange: function (e) { setProfile(e.target.value); } }, h("option", { value: "" }, "All agents"), profileNames.map(function (p) { return h("option", { key: p, value: p }, p); })),
            h("select", { value: range, onChange: function (e) { setRange(Number(e.target.value)); } }, h("option", { value: 24 }, "24 hours"), h("option", { value: 168 }, "7 days"), h("option", { value: 720 }, "30 days"))
          )
        ),
        h("div", { className: "hx-upcoming" }, upcoming.length ? upcoming.map(function (item, index) {
          return h("div", { className: "hx-upcoming-row", key: item.type + ":" + item.id + ":" + item.at + ":" + index },
            h("div", { className: "hx-time" }, fmt(item.at)),
            h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, item.name), h("div", { className: "hx-muted" }, (item.profile || "unassigned") + (item.schedule ? " · " + item.schedule : ""))),
            h(Pill, { kind: item.type }, item.type), item.recurring ? h(Pill, { kind: "recurring" }, "recurring") : null
          );
        }) : h("div", { className: "hx-empty" }, "No upcoming tasks in this range."))
      ),
      h("div", { className: "hx-agent-grid" }, profiles.map(function (agent) {
        return h(Card, { key: agent.name },
          h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, agent.name), h("div", { className: "hx-muted" }, (agent.cron || []).length + " scheduled · " + (agent.kanban || []).length + " kanban"))),
          (agent.cron || []).length ? h("div", null, h("h3", null, "Fixed / scheduled tasks"), (agent.cron || []).map(function (job) {
            return h("div", { className: "hx-task", key: "cron:" + job.id },
              h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, job.name), h("div", { className: "hx-muted" }, String(job.schedule || "") + " · next " + fmt(job.next_run_at))),
              h(Pill, { kind: job.enabled ? "ok" : "paused" }, job.enabled ? "active" : "paused"),
              h("div", { className: "hx-mini-actions" },
                job.enabled ? h("button", { onClick: function () { action("cron", job.id, "pause"); } }, "Pause") : h("button", { onClick: function () { action("cron", job.id, "resume"); } }, "Resume"),
                h("button", { onClick: function () { action("cron", job.id, "run"); } }, "Run")
              )
            );
          })) : null,
          (agent.kanban || []).length ? h("div", null, h("h3", null, "Kanban work"), (agent.kanban || []).map(function (task) {
            return h("div", { className: "hx-task", key: "kanban:" + task.id },
              h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, task.name), h("div", { className: "hx-muted" }, task.status || "task")),
              task.next_run_at ? h("div", { className: "hx-muted" }, fmt(task.next_run_at)) : null
            );
          })) : null,
          !(agent.cron || []).length && !(agent.kanban || []).length ? h("div", { className: "hx-empty" }, "No assigned tasks.") : null
        );
      }))
    );
  }

  window.__HERMES_PLUGINS__.register("hermes-extensions", TaskCenterPage);
})();
