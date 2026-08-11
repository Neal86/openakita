(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.React) return;
  const React = HX.React;
  const h = HX.h;
  const { useEffect, useRef } = React;

  HX.Card = function Card(p) { return h("section", { className: "hx-card " + (p.className || "") }, p.children); };
  HX.Pill = function Pill(p) { return h("span", { className: "hx-pill " + (p.kind || "") }, p.children); };
  HX.Stat = function Stat(p) { return h(HX.Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(p.value == null ? 0 : p.value)), h("div", { className: "hx-muted" }, p.label)); };
  HX.Field = function Field(label, child, help) { return h("label", null, h("span", null, label), child, help ? h("small", null, help) : null); };
  HX.Empty = function Empty(p) { return h("div", { className: "hx-empty" }, p.children); };
  HX.LoadingBlock = function LoadingBlock(p) { return h("div", { className: "hx-loading" }, h("span", { className: "hx-spinner" }), p.children || "Loading…"); };
  HX.SearchBox = function SearchBox(p) { return h("input", { className: "hx-search", type: "search", placeholder: p.placeholder || "Search…", value: p.value, onChange: function (e) { p.onChange(e.target.value); } }); };
  HX.Tabs = function Tabs(p) {
    return h("div", { className: "hx-tabs", role: "tablist", "aria-label": "Management sections" }, HX.TABS.map(function (name) {
      const label = name === "wechat" ? "WeChat" : name.charAt(0).toUpperCase() + name.slice(1);
      return h("button", { key: name, role: "tab", type: "button", "aria-selected": p.value === name, className: "hx-tab " + (p.value === name ? "active" : ""), onClick: function () { p.onChange(name); } }, label);
    }));
  };

  function focusables(root) {
    if (!root) return [];
    return Array.from(root.querySelectorAll('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')).filter(function (el) {
      return el.offsetParent !== null || el === document.activeElement;
    });
  }

  HX.Dialog = function Dialog(p) {
    const boxRef = useRef(null);
    const previousFocus = useRef(null);
    useEffect(function () {
      if (!p.open) return undefined;
      previousFocus.current = document.activeElement;
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      const timer = setTimeout(function () {
        const items = focusables(boxRef.current);
        if (items.length) items[0].focus();
        else if (boxRef.current) boxRef.current.focus();
      }, 0);
      function onKey(e) {
        if (e.key === "Escape" && !p.locked) { e.preventDefault(); p.onRequestClose(); return; }
        if (e.key !== "Tab") return;
        const items = focusables(boxRef.current);
        if (!items.length) { e.preventDefault(); return; }
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
      document.addEventListener("keydown", onKey);
      return function () {
        clearTimeout(timer);
        document.removeEventListener("keydown", onKey);
        document.body.style.overflow = previousOverflow;
        const target = previousFocus.current;
        if (target && typeof target.focus === "function" && document.contains(target)) target.focus();
      };
    }, [p.open, p.locked]);
    if (!p.open) return null;
    return h("div", { className: "hx-dialog-backdrop", role: "presentation", onMouseDown: function (e) { if (e.target === e.currentTarget && !p.locked) p.onRequestClose(); } },
      h("div", { ref: boxRef, className: "hx-dialog", role: "dialog", "aria-modal": "true", "aria-label": p.title, tabIndex: -1 },
        h("div", { className: "hx-dialog-head" }, h("div", null, h("h2", null, p.title), p.subtitle ? h("div", { className: "hx-muted" }, p.subtitle) : null), h("button", { type: "button", className: "hx-icon-button", disabled: p.locked, onClick: p.onRequestClose, "aria-label": "Close" }, "×")),
        h("div", { className: "hx-dialog-body" }, p.children)
      )
    );
  };

  HX.ConfirmDialog = function ConfirmDialog(p) {
    const spec = p.spec;
    if (!spec) return null;
    return h(HX.Dialog, { open: true, title: spec.title || "Confirm action", subtitle: spec.subtitle || "", locked: Boolean(spec.locked), onRequestClose: p.onCancel },
      h("div", { className: "hx-confirm" },
        h("p", null, spec.message || "Are you sure?"),
        spec.detail ? h("div", { className: "hx-confirm-detail" }, spec.detail) : null,
        h("div", { className: "hx-actions hx-confirm-actions" },
          h("button", { type: "button", className: "hx-button secondary", onClick: p.onCancel, disabled: Boolean(spec.locked) }, spec.cancelLabel || "Cancel"),
          h("button", { type: "button", className: "hx-button " + (spec.destructive ? "danger" : ""), onClick: p.onConfirm, disabled: Boolean(spec.locked) }, spec.confirmLabel || "Confirm")
        )
      )
    );
  };
})();
