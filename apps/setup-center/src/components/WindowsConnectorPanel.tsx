import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppWindow,
  ChevronDown,
  ChevronRight,
  Chrome,
  Crosshair,
  Download,
  Link2,
  MonitorSmartphone,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { safeFetch } from "../providers";

const DEFAULT_API = "http://127.0.0.1:18900";

type PermissionSet = {
  read: boolean;
  screenshot: boolean;
  mouse: boolean;
  keyboard: boolean;
  launch: boolean;
  close: boolean;
};

type Grant = {
  id: string;
  node_id: string;
  agent_profile_id: string;
  resource_id: string;
  fingerprint: string;
  remark: string;
  permissions: PermissionSet;
  sync_state?: string;
  sync_error?: string;
};

type Resource = {
  id: string;
  fingerprint: string;
  kind: string;
  app_name: string;
  process_name: string;
  pid: number;
  hwnd: number;
  title: string;
  exe_path: string;
  account_name: string;
  browser_profile: string;
  tab_id: string;
  url: string;
  automation: string;
  controllable: boolean;
  limited: boolean;
  grants: Grant[];
};

type NodeInfo = {
  id: string;
  name: string;
  status: string;
  connector_version?: string;
  transport?: string;
  embedded?: boolean;
  resources: Resource[];
};

type AgentProfile = { id: string; name: string };

type AppGroup = {
  id: string;
  browser: boolean;
  label: string;
  subtitle: string;
  resources: Resource[];
  windowResource?: Resource;
  tabs: Resource[];
};

const defaultPermissions: PermissionSet = {
  read: true,
  screenshot: true,
  mouse: false,
  keyboard: false,
  launch: false,
  close: false,
};

function resourceLabel(resource: Resource): string {
  if (resource.kind === "wechat") {
    return resource.account_name
      ? `${resource.app_name} · ${resource.account_name}`
      : `${resource.app_name} · ${resource.title || `PID ${resource.pid}`}`;
  }
  if (resource.kind === "browser_tab") {
    return resource.title || resource.url || resource.tab_id || resource.app_name;
  }
  return `${resource.app_name} · ${resource.title || `PID ${resource.pid}`}`;
}

function browserGroupKey(resource: Resource): string {
  if (resource.automation === "cdp" && resource.browser_profile) {
    return `browser:cdp:${resource.browser_profile}:${resource.app_name}`;
  }
  if (resource.hwnd) return `browser:hwnd:${resource.hwnd}`;
  return `browser:${resource.app_name}:${resource.process_name}:${resource.browser_profile}`;
}

function groupApps(resources: Resource[]): AppGroup[] {
  const groups = new Map<string, Resource[]>();
  for (const resource of resources) {
    const browser = resource.kind === "browser_window" || resource.kind === "browser_tab";
    const key = browser ? browserGroupKey(resource) : `resource:${resource.id}`;
    const bucket = groups.get(key) || [];
    bucket.push(resource);
    groups.set(key, bucket);
  }

  return [...groups.entries()]
    .map(([id, rows]) => {
      const sorted = [...rows].sort((a, b) => {
        if (a.kind === "browser_window" && b.kind !== "browser_window") return -1;
        if (b.kind === "browser_window" && a.kind !== "browser_window") return 1;
        return (a.title || a.url || a.id).localeCompare(b.title || b.url || b.id);
      });
      const browser = sorted.some(row => row.kind.startsWith("browser"));
      const windowResource = sorted.find(row => row.kind === "browser_window");
      const tabs = sorted.filter(row => row.kind === "browser_tab");
      const representative = windowResource || tabs[0] || sorted[0];
      const label = browser ? representative?.app_name || "浏览器" : resourceLabel(representative);
      const subtitle = browser
        ? `${tabs.length} 个标签页${windowResource?.title ? ` · ${windowResource.title}` : ""}`
        : representative?.exe_path || representative?.process_name || representative?.title || "";
      return { id, browser, label, subtitle, resources: sorted, windowResource, tabs };
    })
    .sort((a, b) => `${a.label}${a.subtitle}`.localeCompare(`${b.label}${b.subtitle}`));
}

function stopEvent(event: React.SyntheticEvent) {
  event.stopPropagation();
}

function ResourceEditor({
  api,
  node,
  resource,
  profiles,
  reload,
}: {
  api: string;
  node: NodeInfo;
  resource: Resource;
  profiles: AgentProfile[];
  reload: () => Promise<void>;
}) {
  const [agentId, setAgentId] = useState(profiles[0]?.id || "");
  const [remark, setRemark] = useState("");
  const [permissions, setPermissions] = useState<PermissionSet>({ ...defaultPermissions });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!agentId && profiles[0]?.id) setAgentId(profiles[0].id);
  }, [profiles, agentId]);

  const createGrant = async () => {
    if (!agentId) return;
    setSaving(true);
    try {
      const response = await safeFetch(`${api}/api/windows-connector/grants`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          node_id: node.id,
          agent_profile_id: agentId,
          resource_id: resource.id,
          remark,
          permissions,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "授权失败");
      if (data?.grant?.sync_state === "pending") {
        toast.warning("授权已保存，远程设备恢复连接后会自动同步");
      } else {
        toast.success("已授权给 Agent");
      }
      setRemark("");
      setPermissions({ ...defaultPermissions });
      await reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const removeGrant = async (grantId: string) => {
    const response = await safeFetch(`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      toast.error(data.detail || "取消授权失败");
      return;
    }
    await reload();
  };

  const updateRemark = async (grantId: string, value: string) => {
    const response = await safeFetch(`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}/remark`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ remark: value }),
    });
    if (!response.ok) toast.error("备注保存失败");
    else await reload();
  };

  return (
    <div className="space-y-3" onClick={stopEvent} onKeyDown={stopEvent}>
      <div className="rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{(resource.automation || "uia").toUpperCase()}</Badge>
          {resource.limited && <Badge variant="secondary">受限模式</Badge>}
          <span>PID {resource.pid || "-"}</span>
          <span>HWND {resource.hwnd || "-"}</span>
          <span>{resource.kind}</span>
        </div>
        <div className="mt-1 truncate">{resource.url || resource.exe_path || resource.process_name || resource.title}</div>
      </div>

      {resource.grants?.length > 0 && (
        <div className="space-y-2">
          {resource.grants.map(grant => (
            <div key={grant.id} className="rounded-md border bg-muted/20 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <ShieldCheck size={15} />
                  <span className="text-sm font-medium">
                    {profiles.find(profile => profile.id === grant.agent_profile_id)?.name || grant.agent_profile_id}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {Object.entries(grant.permissions || {})
                      .filter(([, enabled]) => enabled)
                      .map(([key]) => key)
                      .join(" · ")}
                  </span>
                  {grant.sync_state === "pending" && <Badge variant="secondary">待同步</Badge>}
                  {grant.sync_error && (
                    <span className="text-xs text-destructive" title={grant.sync_error}>同步失败</span>
                  )}
                </div>
                <Button size="sm" variant="ghost" onClick={() => void removeGrant(grant.id)}>
                  <Trash2 size={14} />取消授权
                </Button>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Label className="shrink-0 text-xs">备注</Label>
                <Input
                  defaultValue={grant.remark}
                  placeholder="自定义备注"
                  onBlur={event => {
                    if (event.target.value !== grant.remark) void updateRemark(grant.id, event.target.value);
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-3 rounded-md border border-dashed p-3 lg:grid-cols-[220px_1fr_auto] lg:items-end">
        <div className="space-y-1.5">
          <Label>授权给 Agent</Label>
          <Select value={agentId} onValueChange={setAgentId}>
            <SelectTrigger><SelectValue placeholder="选择 Agent" /></SelectTrigger>
            <SelectContent>
              {profiles.map(profile => (
                <SelectItem key={profile.id} value={profile.id}>{profile.name} ({profile.id})</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>备注</Label>
          <Input
            value={remark}
            onChange={event => setRemark(event.target.value)}
            placeholder={resource.kind === "wechat" ? "客服微信名称" : resource.kind === "browser_tab" ? "Tab 备注" : "应用备注"}
          />
        </div>
        <Button disabled={saving || !agentId} onClick={() => void createGrant()}>
          <ShieldCheck size={14} />授权
        </Button>
        <div className="flex flex-wrap gap-3 lg:col-span-3">
          {([
            ["read", "读取界面"],
            ["screenshot", "截图"],
            ["mouse", "鼠标操作"],
            ["keyboard", "键盘输入"],
            ["launch", "启动应用"],
            ["close", "关闭应用"],
          ] as [keyof PermissionSet, string][]).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-xs">
              <Switch
                checked={permissions[key]}
                onCheckedChange={value => setPermissions(current => ({ ...current, [key]: value }))}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

function AppAccordion({
  api,
  node,
  group,
  profiles,
  open,
  selectedResourceId,
  activeTabId,
  activatingResourceId,
  onToggle,
  onActivate,
  onTabChange,
  reload,
}: {
  api: string;
  node: NodeInfo;
  group: AppGroup;
  profiles: AgentProfile[];
  open: boolean;
  selectedResourceId: string;
  activeTabId: string;
  activatingResourceId: string;
  onToggle: () => void;
  onActivate: (resource: Resource) => Promise<void>;
  onTabChange: (resource: Resource) => void;
  reload: () => Promise<void>;
}) {
  const selected = group.resources.some(resource => resource.id === selectedResourceId);
  const editorResource = group.browser
    ? group.resources.find(resource => resource.id === activeTabId) || group.windowResource || group.tabs[0]
    : group.resources[0];
  const focusResource = group.browser ? editorResource || group.resources[0] : group.resources[0];

  const handleHeader = () => {
    onToggle();
    if (focusResource) void onActivate(focusResource);
  };

  return (
    <div className={`rounded-lg border transition-colors ${selected ? "border-primary/60 bg-primary/[0.03] ring-1 ring-primary/20" : "bg-background"}`}>
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/35"
        aria-expanded={open}
        onClick={handleHeader}
      >
        {open ? <ChevronDown size={16} className="shrink-0 text-muted-foreground" /> : <ChevronRight size={16} className="shrink-0 text-muted-foreground" />}
        {group.browser ? <Chrome size={17} className="shrink-0" /> : <AppWindow size={17} className="shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium">{group.label}</span>
            {group.browser && <Badge variant="outline">{group.tabs.length} Tabs</Badge>}
            {selected && <Badge>当前选中</Badge>}
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{group.subtitle}</div>
        </div>
        {focusResource && (
          <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            <Crosshair size={13} className={activatingResourceId === focusResource.id ? "animate-pulse" : ""} />
            点击定位
          </span>
        )}
      </button>

      {open && editorResource && (
        <div className="border-t px-4 py-4">
          {group.browser && (
            <div className="mb-4 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <Label>浏览器标签页</Label>
                <span className="text-xs text-muted-foreground">点击 Tab 会切换并定位到真实浏览器标签页</span>
              </div>
              <div role="tablist" className="flex gap-2 overflow-x-auto pb-1">
                {group.windowResource && (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={editorResource.id === group.windowResource.id}
                    className={`max-w-[220px] shrink-0 rounded-md border px-3 py-2 text-left text-xs ${editorResource.id === group.windowResource.id ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted"}`}
                    onClick={() => {
                      onTabChange(group.windowResource!);
                      void onActivate(group.windowResource!);
                    }}
                  >
                    <span className="block truncate font-medium">浏览器窗口</span>
                    <span className="mt-0.5 block truncate text-muted-foreground">{group.windowResource.title || group.windowResource.app_name}</span>
                  </button>
                )}
                {group.tabs.map(tab => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={editorResource.id === tab.id}
                    title={tab.url || tab.title}
                    className={`max-w-[240px] shrink-0 rounded-md border px-3 py-2 text-left text-xs ${editorResource.id === tab.id ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted"}`}
                    onClick={() => {
                      onTabChange(tab);
                      void onActivate(tab);
                    }}
                  >
                    <span className="block truncate font-medium">{tab.title || "未命名 Tab"}</span>
                    <span className="mt-0.5 block truncate text-muted-foreground">{tab.url || tab.browser_profile || tab.tab_id}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <ResourceEditor api={api} node={node} resource={editorResource} profiles={profiles} reload={reload} />
        </div>
      )}
    </div>
  );
}

export function WindowsConnectorPanel({ apiBaseUrl = DEFAULT_API }: { apiBaseUrl?: string }) {
  const api = apiBaseUrl || DEFAULT_API;
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [nodeName, setNodeName] = useState("远程 Windows 电脑");
  const [pairingCode, setPairingCode] = useState("");
  const [openNodes, setOpenNodes] = useState<Set<string>>(() => new Set(["local"]));
  const [openApps, setOpenApps] = useState<Set<string>>(() => new Set());
  const [selectedResourceId, setSelectedResourceId] = useState("");
  const [activeTabs, setActiveTabs] = useState<Record<string, string>>({});
  const [activatingResourceId, setActivatingResourceId] = useState("");

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nodeResponse, profileResponse] = await Promise.all([
        safeFetch(`${api}/api/windows-connector/nodes`),
        safeFetch(`${api}/api/agents/profiles`),
      ]);
      const nodeData = await nodeResponse.json().catch(() => ({}));
      const profileData = await profileResponse.json().catch(() => ({}));
      if (!nodeResponse.ok) throw new Error(nodeData.detail || "加载 Windows 设备失败");
      if (!profileResponse.ok) throw new Error(profileData.detail || "加载 Agent 列表失败");
      setNodes(nodeData.nodes || []);
      setProfiles(profileData.profiles || []);
    } catch (error) {
      if (!quiet) toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const grouped = useMemo(
    () => nodes.map(node => ({ node, apps: groupApps(node.resources || []) })),
    [nodes],
  );

  const refreshNode = async (nodeId: string) => {
    const response = await safeFetch(`${api}/api/windows-connector/nodes/${encodeURIComponent(nodeId)}/refresh`, { method: "POST" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      toast.error(data.detail || "扫描失败");
      return;
    }
    window.setTimeout(() => void load(true), nodeId === "local" ? 150 : 800);
  };

  const previewFocus = useCallback(async (node: NodeInfo, resource: Resource) => {
    setActivatingResourceId(resource.id);
    try {
      const response = await safeFetch(`${api}/api/windows-connector/preview-focus`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: node.id, resource_id: resource.id }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "定位应用失败");
      setSelectedResourceId(resource.id);
      toast.success(node.id === "local" ? `已定位：${resourceLabel(resource)}` : `已向远程设备发送定位：${resourceLabel(resource)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setActivatingResourceId("");
    }
  }, [api]);

  const download = async () => {
    setDownloading(true);
    try {
      const response = await safeFetch(`${api}/api/windows-connector/connector/download`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Windows Connector 尚未生成");
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = "OpenAkita-Windows-Connector-Windows-x64.zip";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setDownloading(false);
    }
  };

  const createPairingCode = async () => {
    setPairing(true);
    try {
      const response = await safeFetch(`${api}/api/windows-connector/pairing-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_name: nodeName || "远程 Windows 电脑", ttl_seconds: 3600 }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "生成配对码失败");
      setPairingCode(data.code || "");
      toast.success("配对码已生成，有效期 1 小时");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setPairing(false);
    }
  };

  const toggleNode = (nodeId: string) => {
    setOpenNodes(current => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  const toggleApp = (groupId: string) => {
    setOpenApps(current => {
      const next = new Set(current);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const local = grouped.find(entry => entry.node.id === "local");
  const remotes = grouped.filter(entry => entry.node.id !== "local");

  const renderNode = ({ node, apps }: { node: NodeInfo; apps: AppGroup[] }) => {
    const embedded = node.id === "local" || node.embedded || node.transport === "local";
    const online = node.status === "online";
    const open = openNodes.has(node.id);
    const resourceCount = apps.reduce((total, app) => total + app.resources.length, 0);

    return (
      <Card key={node.id} className="overflow-hidden">
        <button
          type="button"
          className="flex w-full items-center gap-3 p-4 text-left hover:bg-muted/30"
          onClick={() => toggleNode(node.id)}
          aria-expanded={open}
        >
          {open ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
          <MonitorSmartphone size={17} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 font-semibold">
              {node.name || (embedded ? "本机" : node.id)}
              <Badge variant="outline">{embedded ? "内嵌 Runtime" : "远程 Connector"}</Badge>
              <Badge variant={online ? "default" : "secondary"}>{online ? "在线" : node.status === "unsupported" ? "当前平台不支持" : "离线"}</Badge>
            </div>
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {embedded
                ? `${apps.length} 个应用 · ${resourceCount} 个可操作目标`
                : `${node.id} · Connector ${node.connector_version || "未知"} · ${apps.length} 个应用`}
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={!online}
            onClick={event => {
              event.stopPropagation();
              void refreshNode(node.id);
            }}
          >
            <RefreshCw size={13} />扫描应用
          </Button>
        </button>

        {open && (
          <div className="space-y-2 border-t bg-muted/[0.08] p-3">
            {apps.map(group => {
              const appKey = `${node.id}:${group.id}`;
              const fallbackActive = group.windowResource?.id || group.tabs[0]?.id || group.resources[0]?.id || "";
              return (
                <AppAccordion
                  key={group.id}
                  api={api}
                  node={node}
                  group={group}
                  profiles={profiles}
                  open={openApps.has(appKey)}
                  selectedResourceId={selectedResourceId}
                  activeTabId={activeTabs[appKey] || fallbackActive}
                  activatingResourceId={activatingResourceId}
                  onToggle={() => toggleApp(appKey)}
                  onActivate={resource => previewFocus(node, resource)}
                  onTabChange={resource => setActiveTabs(current => ({ ...current, [appKey]: resource.id }))}
                  reload={() => load(true)}
                />
              );
            })}
            {!apps.length && (
              <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">
                {embedded
                  ? "暂未发现运行中的可见应用。先打开微信、浏览器或其他程序，然后点击“扫描应用”。"
                  : "远程设备在线后点击“扫描应用”，即可加载该电脑上的可见应用。"}
              </div>
            )}
          </div>
        )}
      </Card>
    );
  };

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">Windows 设备</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            设备和应用使用手风琴管理；浏览器标签页归组在对应浏览器下。点击应用或 Tab 会定位真实窗口，方便授权前确认目标。
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />刷新状态
        </Button>
      </div>

      <section className="space-y-3">
        <div>
          <h3 className="font-semibold">本机</h3>
          <p className="text-xs text-muted-foreground">零配置直连。展开设备后查看应用；点击具体目标可立即切到对应 Windows 窗口。</p>
        </div>
        {local ? renderNode(local) : <Card className="p-8 text-center text-sm text-muted-foreground">正在加载本机 Windows Runtime…</Card>}
      </section>

      <section className="mt-6 space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">远程设备</h3>
            <p className="text-xs text-muted-foreground">在其他 Windows 电脑上运行 Connector。远程设备也使用相同的设备 → 应用 → 浏览器 Tab 层级。</p>
          </div>
          <Button variant="outline" onClick={() => void download()} disabled={downloading}>
            <Download size={14} />下载远程 Connector
          </Button>
        </div>

        <Card className="p-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
            <div className="space-y-1.5">
              <Label>远程设备名称</Label>
              <Input value={nodeName} onChange={event => setNodeName(event.target.value)} placeholder="例如：仓库电脑 01" />
            </div>
            <Button onClick={() => void createPairingCode()} disabled={pairing}>
              <Link2 size={14} />生成配对码
            </Button>
          </div>
          {pairingCode && (
            <div className="mt-3 rounded-md border bg-muted/30 p-3">
              <div className="text-xs text-muted-foreground">配对码（1 小时有效）</div>
              <div className="mt-1 font-mono text-lg font-semibold tracking-wider">{pairingCode}</div>
            </div>
          )}
        </Card>

        {remotes.map(renderNode)}
        {!remotes.length && (
          <Card className="p-8 text-center text-sm text-muted-foreground">暂无远程 Windows 设备。下载 Connector 并使用上方配对码接入。</Card>
        )}
      </section>
    </div>
  );
}
