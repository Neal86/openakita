import { Fragment, useState, useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { StepId, Step, ViewId, PluginUIApp } from "../types";
import {
  IconChat, IconIM, IconSkills, IconStatus, IconConfig,
  IconChevronDown, IconChevronRight, IconGlobe,
  IconZap, IconPlug, IconCalendar,
  IconBug, IconBrain, IconGitHub, IconGitee, IconUsers, IconBot,
  IconGear, IconBook, IconStorefront, IconPuzzle, IconFingerprint, IconLayoutGrid,
  IconShield, IconRadar, IconBuilding, IconBarChart,
} from "../icons";
import { MonitorSmartphone } from "lucide-react";
import logoUrl from "../assets/logo.png";
import { openExternalUrl } from "../platform";
import { ReleaseNotesDialog, normalizeReleaseVersion } from "./ReleaseNotesDialog";

export type SidebarProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  view: ViewId;
  onViewChange: (v: ViewId) => void;
  configExpanded: boolean;
  onToggleConfig: () => void;
  steps: Step[];
  stepId: StepId;
  onStepChange: (id: StepId) => void;
  disabledViews: string[];
  storeVisible: boolean;
  desktopVersion: string;
  backendVersion: string | null;
  serviceRunning: boolean;
  onRefreshStatus: () => Promise<void>;
  isWeb?: boolean;
  mobileOpen?: boolean;
  httpApiBase?: string;
  unreadFeedbackCount?: number;
  pendingApprovalsCount?: number;
};

const stepIcons: Partial<Record<StepId, React.ReactNode>> = {
  llm: <IconZap size={14} />, im: <IconIM size={14} />, tools: <IconSkills size={14} />,
  agent: <IconBot size={14} />, workspace: <IconBook size={14} />, advanced: <IconGear size={14} />,
};
function StepDot({ stepId: sid }: { stepId: StepId }) { return <div className="stepDot">{stepIcons[sid]}</div>; }

type NavGroupId = "capabilities" | "apps" | "monitor" | "multiAgent" | "store";
const GROUP_ICON_SIZE = 16;
const BETA_SUP = <sup style={{ fontSize: 9, color: "var(--primary, #3b82f6)", fontWeight: 600 }}>Beta</sup>;
const EXEC_PAGE_EVENT = "openakita:execution-page-change";
const EXEC_PAGE_KEY = "openakita:execution-page";
type ExecPage = "hermes" | "windows";

function NavGroupHeader({ collapsed, icon, label, expanded, onToggle }: { collapsed: boolean; icon: React.ReactNode; label: string; expanded: boolean; onToggle: () => void }) {
  return <div className="navGroupHeader" onClick={onToggle} role="button" tabIndex={0} title={collapsed ? label : undefined}>
    {!collapsed ? <><span className="navGroupLabelWrap"><span className="navGroupIcon">{icon}</span><span className="navGroupLabel">{label}</span></span><span className="navGroupChevron">{expanded ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}</span></> : <span className="navGroupIcon navGroupIconCollapsed">{icon}</span>}
  </div>;
}

export function Sidebar({
  collapsed, onToggleCollapsed, view, onViewChange, configExpanded, onToggleConfig,
  steps, stepId, onStepChange, disabledViews, storeVisible, desktopVersion, backendVersion,
  serviceRunning, onRefreshStatus, isWeb, mobileOpen, httpApiBase, unreadFeedbackCount, pendingApprovalsCount,
}: SidebarProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [expandedGroups, setExpandedGroups] = useState<Record<NavGroupId, boolean>>({ capabilities: false, apps: false, monitor: false, multiAgent: false, store: false });
  const [pluginApps, setPluginApps] = useState<PluginUIApp[]>([]);
  const [releaseNotesOpen, setReleaseNotesOpen] = useState(false);
  const [executionPage, setExecutionPage] = useState<ExecPage>(() => window.sessionStorage.getItem(EXEC_PAGE_KEY) === "windows" ? "windows" : "hermes");
  const releaseNotesVersion = normalizeReleaseVersion(desktopVersion);

  const pickAppTitle = (app: PluginUIApp): string => {
    const dict = app.title_i18n;
    if (dict && typeof dict === "object") {
      if (dict[lang]) return dict[lang];
      const base = lang.split("-")[0];
      if (base && dict[base]) return dict[base];
      if (dict.en) return dict.en;
      const first = Object.values(dict).find(v => typeof v === "string" && v);
      if (first) return first;
    }
    return app.title;
  };

  const toggleGroup = useCallback((id: NavGroupId) => setExpandedGroups(prev => ({ ...prev, [id]: !prev[id] })), []);
  const openExecutionPage = useCallback((page: ExecPage) => {
    setExecutionPage(page);
    window.sessionStorage.setItem(EXEC_PAGE_KEY, page);
    onViewChange("execution_instances");
    window.dispatchEvent(new CustomEvent(EXEC_PAGE_EVENT, { detail: { page } }));
  }, [onViewChange]);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ page?: string }>).detail;
      setExecutionPage(detail?.page === "windows" ? "windows" : "hermes");
    };
    window.addEventListener(EXEC_PAGE_EVENT, listener);
    return () => window.removeEventListener(EXEC_PAGE_EVENT, listener);
  }, []);

  useEffect(() => {
    if (!httpApiBase || !serviceRunning) { setPluginApps([]); return; }
    let cancelled = false;
    const retryDelays = [2_000, 8_000, 20_000, 60_000, 120_000];
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const clearTimers = () => { timers.forEach(timer => clearTimeout(timer)); timers.clear(); };
    const refetch = async (attempt = 0) => {
      try {
        const r = await fetch(`${httpApiBase}/api/plugins/ui-apps`);
        const data = r.ok ? await r.json() : [];
        if (cancelled) return;
        const apps = Array.isArray(data) ? data : [];
        setPluginApps(apps);
        if (!apps.length && retryDelays[attempt] != null) {
          const timer = setTimeout(() => { timers.delete(timer); void refetch(attempt + 1); }, retryDelays[attempt]);
          timers.add(timer);
        }
      } catch {
        if (!cancelled && retryDelays[attempt] != null) {
          const timer = setTimeout(() => { timers.delete(timer); void refetch(attempt + 1); }, retryDelays[attempt]);
          timers.add(timer);
        }
      }
    };
    void refetch();
    const onChanged = () => { clearTimers(); void refetch(); };
    window.addEventListener("openakita:plugin-apps-changed", onChanged);
    return () => { cancelled = true; clearTimers(); window.removeEventListener("openakita:plugin-apps-changed", onChanged); };
  }, [httpApiBase, serviceRunning]);

  const capViews: ViewId[] = ["skills", "mcp", "plugins", "memory", "scheduler"];
  const monViews: ViewId[] = ["token_stats", "skill_usage", "security", "pending_approvals"];
  const maViews: ViewId[] = ["dashboard", "org_editor", "pixel_office", "agent_manager"];
  const stViews: ViewId[] = ["agent_store", "skill_store"];
  const prevViewRef = useRef(view);
  useEffect(() => {
    if (prevViewRef.current === view) return;
    prevViewRef.current = view;
    const groupOf = (v: ViewId): NavGroupId | null => capViews.includes(v) ? "capabilities" : monViews.includes(v) ? "monitor" : maViews.includes(v) ? "multiAgent" : stViews.includes(v) ? "store" : (typeof v === "string" && v.startsWith("plugin_app:")) ? "apps" : null;
    const group = groupOf(view);
    if (group) setExpandedGroups(prev => ({ ...prev, [group]: true }));
  }, [view]);

  const capExpanded = expandedGroups.capabilities, appsExpanded = expandedGroups.apps, monExpanded = expandedGroups.monitor, maExpanded = expandedGroups.multiAgent, stExpanded = expandedGroups.store;

  return <aside className={`sidebar ${collapsed ? "sidebarCollapsed" : ""}${mobileOpen ? " sidebarOpen" : ""}`}>
    <div className="sidebarHeader"><div style={{ display: "flex", alignItems: "center", gap: 10 }}><img src={logoUrl} alt="OpenAkita" className="brandLogo" onClick={onToggleCollapsed} style={{ cursor: "pointer" }} title={collapsed ? t("sidebar.expand") : t("sidebar.collapse")} />{!collapsed && <div><div className="brandTitle">{t("brand.title")}</div><div className="brandSub">{t("brand.sub")}</div></div>}</div></div>
    <div className="sidebarNav">
      <div className={`navItem ${view === "chat" ? "navItemActive" : ""}`} onClick={() => onViewChange("chat")} role="button" tabIndex={0} title={t("sidebar.chat")}><IconChat size={16} />{!collapsed && <span>{t("sidebar.chat")}</span>}</div>
      {!disabledViews.includes("im") && <div className={`navItem ${view === "im" ? "navItemActive" : ""}`} onClick={() => onViewChange("im")} role="button" tabIndex={0} title={t("sidebar.im")}><IconIM size={16} />{!collapsed && <span>{t("sidebar.im")}</span>}</div>}
      <div className={`navItem ${view === "status" ? "navItemActive" : ""}`} onClick={async () => { onViewChange("status"); try { await onRefreshStatus(); } catch {} }} role="button" tabIndex={0} title={t("sidebar.status")}><IconStatus size={16} />{!collapsed && <span>{t("sidebar.status")}</span>}</div>

      <NavGroupHeader collapsed={collapsed} icon={<IconPuzzle size={GROUP_ICON_SIZE} />} label={t("sidebar.groupCapabilities")} expanded={capExpanded} onToggle={() => toggleGroup("capabilities")} />
      {(collapsed || capExpanded) && <div className="navGroupItems">
        {!disabledViews.includes("skills") && <div className={`navItem ${view === "skills" ? "navItemActive" : ""}`} onClick={() => onViewChange("skills")} role="button" tabIndex={0}><IconSkills size={16} />{!collapsed && <span>{t("sidebar.skills")}</span>}</div>}
        {!disabledViews.includes("mcp") && <div className={`navItem ${view === "mcp" ? "navItemActive" : ""}`} onClick={() => onViewChange("mcp")} role="button" tabIndex={0}><IconPlug size={16} />{!collapsed && <span>MCP {BETA_SUP}</span>}</div>}
        <div className={`navItem ${view === "plugins" ? "navItemActive" : ""}`} onClick={() => onViewChange("plugins")} role="button" tabIndex={0}><IconPuzzle size={16} />{!collapsed && <span>{t("sidebar.plugins")} {BETA_SUP}</span>}</div>
        <div className={`navItem ${view === "memory" ? "navItemActive" : ""}`} onClick={() => onViewChange("memory")} role="button" tabIndex={0}><IconBrain size={16} />{!collapsed && <span>{t("sidebar.memory")} {BETA_SUP}</span>}</div>
        <div className={`navItem ${view === "scheduler" ? "navItemActive" : ""}`} onClick={() => onViewChange("scheduler")} role="button" tabIndex={0}><IconCalendar size={16} />{!collapsed && <span>{t("sidebar.scheduler")} {BETA_SUP}</span>}</div>
      </div>}

      {pluginApps.length > 0 && <><NavGroupHeader collapsed={collapsed} icon={<IconLayoutGrid size={GROUP_ICON_SIZE} />} label={t("sidebar.groupApps", "Apps")} expanded={appsExpanded} onToggle={() => toggleGroup("apps")} />{(collapsed || appsExpanded) && <div className="navGroupItems">{pluginApps.map(app => { const appViewId: ViewId = `plugin_app:${app.id}`; const appTitle = pickAppTitle(app); return <div key={app.id} className={`navItem ${view === appViewId ? "navItemActive" : ""}`} onClick={() => onViewChange(appViewId)} role="button" tabIndex={0} title={appTitle}>{app.icon_url ? <img src={`${httpApiBase}${app.icon_url}`} alt="" style={{ width: 16, height: 16, borderRadius: 2 }} /> : <IconLayoutGrid size={16} />}{!collapsed && <span>{appTitle}</span>}</div>; })}</div>}</>}

      <NavGroupHeader collapsed={collapsed} icon={<IconRadar size={GROUP_ICON_SIZE} />} label={t("sidebar.groupMonitor")} expanded={monExpanded} onToggle={() => toggleGroup("monitor")} />
      {(collapsed || monExpanded) && <div className="navGroupItems">
        <div className={`navItem ${view === "token_stats" ? "navItemActive" : ""}`} onClick={() => onViewChange("token_stats")} role="button" tabIndex={0}><IconZap size={16} />{!collapsed && <span>{t("sidebar.tokenStats")}</span>}</div>
        <div className={`navItem ${view === "skill_usage" ? "navItemActive" : ""}`} onClick={() => onViewChange("skill_usage")} role="button" tabIndex={0}><IconBarChart size={16} />{!collapsed && <span>{t("sidebar.skillUsage")}</span>}</div>
        <div className={`navItem ${view === "security" ? "navItemActive" : ""}`} onClick={() => onViewChange("security")} role="button" tabIndex={0}><IconShield size={16} />{!collapsed && <span>{t("sidebar.security")}</span>}</div>
        <div className={`navItem ${view === "pending_approvals" ? "navItemActive" : ""}`} onClick={() => onViewChange("pending_approvals")} role="button" tabIndex={0} style={{ position: "relative" }}><IconFingerprint size={16} />{!collapsed && <span>{t("sidebar.pendingApprovals")}</span>}{(pendingApprovalsCount ?? 0) > 0 && <span style={{ position: "absolute", top: 4, right: 8, minWidth: 16, height: 16, borderRadius: 8, background: "#ef4444", color: "#fff", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 4px" }}>{pendingApprovalsCount}</span>}</div>
      </div>}

      <NavGroupHeader collapsed={collapsed} icon={<IconBot size={GROUP_ICON_SIZE} />} label={t("sidebar.groupMultiAgent")} expanded={maExpanded} onToggle={() => toggleGroup("multiAgent")} />
      {(collapsed || maExpanded) && <div className="navGroupItems">
        <div className={`navItem ${view === "dashboard" ? "navItemActive" : ""}`} onClick={() => onViewChange("dashboard")} role="button" tabIndex={0}><IconUsers size={16} />{!collapsed && <span>{t("sidebar.dashboard")} {BETA_SUP}</span>}</div>
        <div className={`navItem ${view === "org_editor" ? "navItemActive" : ""}`} onClick={() => onViewChange("org_editor")} role="button" tabIndex={0}><IconLayoutGrid size={16} />{!collapsed && <span>{t("sidebar.orgEditor")} {BETA_SUP}</span>}</div>
        <div className={`navItem ${view === "pixel_office" ? "navItemActive" : ""}`} onClick={() => onViewChange("pixel_office")} role="button" tabIndex={0}><IconBuilding size={16} />{!collapsed && <span>{t("sidebar.pixelOffice")} {BETA_SUP}</span>}</div>
        <div className={`navItem ${view === "agent_manager" ? "navItemActive" : ""}`} onClick={() => onViewChange("agent_manager")} role="button" tabIndex={0}><IconBot size={16} />{!collapsed && <span>{t("sidebar.agentManager")}</span>}</div>
      </div>}

      <div className={`navItem ${view === "execution_instances" && executionPage === "hermes" ? "navItemActive" : ""}`} onClick={() => openExecutionPage("hermes")} role="button" tabIndex={0} title="Hermes"><IconGear size={16} />{!collapsed && <span>Hermes</span>}</div>
      <div className={`navItem ${view === "execution_instances" && executionPage === "windows" ? "navItemActive" : ""}`} onClick={() => openExecutionPage("windows")} role="button" tabIndex={0} title="Windows Connector"><MonitorSmartphone size={16} />{!collapsed && <span>Windows Connector</span>}</div>

      {storeVisible && <><NavGroupHeader collapsed={collapsed} icon={<IconStorefront size={GROUP_ICON_SIZE} />} label={t("sidebar.groupStore")} expanded={stExpanded} onToggle={() => toggleGroup("store")} />{(collapsed || stExpanded) && <div className="navGroupItems"><div className={`navItem ${view === "agent_store" ? "navItemActive" : ""}`} onClick={() => onViewChange("agent_store")} role="button" tabIndex={0}><IconStorefront size={16} />{!collapsed && <span>{t("sidebar.agentStore")} {BETA_SUP}</span>}</div><div className={`navItem ${view === "skill_store" ? "navItemActive" : ""}`} onClick={() => onViewChange("skill_store")} role="button" tabIndex={0}><IconPuzzle size={16} />{!collapsed && <span>{t("sidebar.skillStore")} {BETA_SUP}</span>}</div></div>}</>}
    </div>

    <div className="configSection"><div className="configHeader" onClick={onToggleConfig} role="button" tabIndex={0} title={t("sidebar.config")}><div style={{ display: "flex", alignItems: "center", gap: 6 }}><IconConfig size={16} />{!collapsed && <span>{t("sidebar.config")}</span>}</div>{!collapsed && (configExpanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />)}</div>
      {!collapsed && configExpanded && <div className="stepList">{steps.map(s => { const isActive = view === "wizard" && s.id === stepId; return <Fragment key={s.id}><div className={`stepItem ${isActive ? "stepItemActive" : ""}`} onClick={() => { onViewChange("wizard"); onStepChange(s.id); }} role="button" tabIndex={0}><StepDot stepId={s.id} /><div className="stepMeta"><div className="stepTitle">{s.title}</div></div></div>{s.id === "agent" && <div className={`stepItem ${view === "identity" ? "stepItemActive" : ""}`} onClick={() => onViewChange("identity")} role="button" tabIndex={0}><div className="stepDot"><IconFingerprint size={14} /></div><div className="stepMeta"><div className="stepTitle">{t("sidebar.identity")}</div></div></div>}</Fragment>; })}</div>}
    </div>

    {!collapsed ? <div style={{ padding: "10px 16px", borderTop: "1px solid var(--line)", fontSize: 11, opacity: 0.4, lineHeight: 1.6, flexShrink: 0 }}>
      <div onClick={() => setReleaseNotesOpen(true)} style={{ cursor: "pointer" }}>{isWeb ? "Web" : "Desktop"} v{desktopVersion}{import.meta.env.VITE_PREVIEW_BUILD === "true" && <span style={{ marginLeft: 6, color: "#e8a735", fontWeight: 600, opacity: 1 }}>预览版</span>}</div>
      {backendVersion && <div>Backend v{backendVersion}</div>}{!backendVersion && serviceRunning && <div>Backend: -</div>}
      <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}><span onClick={() => openExternalUrl("https://openakita.ai")} style={{ color: "var(--accent, #5B8DEF)", opacity: 1, display: "inline-flex", alignItems: "center", gap: 3, cursor: "pointer" }}><IconGlobe size={11} />openakita.ai</span>{serviceRunning && <span onClick={() => onViewChange("my_feedback")} style={{ cursor: "pointer", opacity: 1, color: "var(--accent, #5B8DEF)", display: "inline-flex", alignItems: "center", gap: 2, position: "relative" }}><IconBug size={12} />{t("sidebar.myFeedback")}{(unreadFeedbackCount ?? 0) > 0 && <span style={{ position: "absolute", top: -4, right: -6, width: 7, height: 7, borderRadius: "50%", background: "#ef4444" }} />}</span>}<span onClick={() => onViewChange("docs")} style={{ color: "var(--accent, #5B8DEF)", opacity: 1, display: "inline-flex", alignItems: "center", gap: 3, cursor: "pointer" }}><IconBook size={12} />{t("sidebar.docs")}</span><span onClick={() => openExternalUrl("https://github.com/openakita/openakita")} style={{ color: "var(--accent, #5B8DEF)", opacity: 1, display: "inline-flex", cursor: "pointer" }}><IconGitHub size={13} /></span><span onClick={() => openExternalUrl("https://gitee.com/zacon365/openakita")} style={{ color: "var(--accent, #5B8DEF)", opacity: 1, display: "inline-flex", cursor: "pointer" }}><IconGitee size={13} /></span></div>
    </div> : <div style={{ padding: "8px 0", borderTop: "1px solid var(--line)", flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}><IconGlobe size={14} /><IconBook size={14} />{serviceRunning && <IconBug size={14} />}</div>}
    {releaseNotesOpen && <ReleaseNotesDialog version={releaseNotesVersion} onClose={() => setReleaseNotesOpen(false)} />}
  </aside>;
}
