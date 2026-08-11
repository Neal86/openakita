import { useCallback, useEffect, useMemo, useState } from "react";
import { AppWindow, Chrome, Download, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
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
  resources: Resource[];
};

type AgentProfile = { id: string; name: string };

const defaultPermissions: PermissionSet = {
  read: true,
  screenshot: true,
  mouse: true,
  keyboard: true,
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
    return `${resource.app_name} · ${resource.title || resource.url || resource.tab_id}`;
  }
  return `${resource.app_name} · ${resource.title || `PID ${resource.pid}`}`;
}

function ResourceCard({
  node,
  resource,
  profiles,
  reload,
}: {
  node: NodeInfo;
  resource: Resource;
  profiles: AgentProfile[];
  reload: () => Promise<void>;
}) {
  const [agentId, setAgentId] = useState(profiles[0]?.id || "default");
  const [remark, setRemark] = useState("");
  const [permissions, setPermissions] = useState<PermissionSet>(defaultPermissions);
  const [saving, setSaving] = useState(false);

  const createGrant = async () => {
    if (!agentId) return;
    setSaving(true);
    try {
      const response = await safeFetch(`${DEFAULT_API}/api/windows-connector/grants`, {
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
      toast.success("已授权给 Agent");
      await reload();
    } catch (error) {
      toast.error(String(error));
    } finally {
      setSaving(false);
    }
  };

  const removeGrant = async (grantId: string) => {
    const response = await safeFetch(`${DEFAULT_API}/api/windows-connector/grants/${encodeURIComponent(grantId)}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      toast.error(data.detail || "取消授权失败");
      return;
    }
    await reload();
  };

  const updateRemark = async (grantId: string, value: string) => {
    const response = await safeFetch(`${DEFAULT_API}/api/windows-connector/grants/${encodeURIComponent(grantId)}/remark`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ remark: value }),
    });
    if (!response.ok) toast.error("备注保存失败");
    else await reload();
  };

  const isBrowser = resource.kind.startsWith("browser");
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            {isBrowser ? <Chrome size={16} /> : <AppWindow size={16} />}
            <span>{resourceLabel(resource)}</span>
            <Badge variant="outline">{resource.automation.toUpperCase()}</Badge>
            {resource.limited && <Badge variant="secondary">受限模式</Badge>}
          </div>
          <div className="mt-1 max-w-3xl truncate text-xs text-muted-foreground">
            {resource.url || resource.exe_path || resource.process_name}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            PID {resource.pid || "-"} · HWND {resource.hwnd || "-"} · {resource.kind}
          </div>
        </div>
      </div>

      {resource.grants?.length > 0 && (
        <div className="space-y-2">
          {resource.grants.map((grant) => (
            <div key={grant.id} className="rounded-md border bg-muted/20 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={15} />
                  <span className="text-sm font-medium">
                    {profiles.find((profile) => profile.id === grant.agent_profile_id)?.name || grant.agent_profile_id}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {Object.entries(grant.permissions || {}).filter(([, enabled]) => enabled).map(([key]) => key).join(" · ")}
                  </span>
                </div>
                <Button size="sm" variant="ghost" onClick={() => void removeGrant(grant.id)}><Trash2 size={14} />取消授权</Button>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Label className="shrink-0 text-xs">备注</Label>
                <Input
                  defaultValue={grant.remark}
                  placeholder={resource.kind === "wechat" ? "例如：海外仓客服微信" : resource.kind === "browser_tab" ? "例如：领星 ERP 订单页" : "自定义备注"}
                  onBlur={(event) => { if (event.target.value !== grant.remark) void updateRemark(grant.id, event.target.value); }}
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
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="default">默认 Agent</SelectItem>
              {profiles.map((profile) => <SelectItem key={profile.id} value={profile.id}>{profile.name} ({profile.id})</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>备注</Label>
          <Input value={remark} onChange={(event) => setRemark(event.target.value)} placeholder={resource.kind === "wechat" ? "客服微信名称" : resource.kind === "browser_tab" ? "Tab 备注" : "应用备注"} />
        </div>
        <Button disabled={saving || !agentId} onClick={() => void createGrant()}><ShieldCheck size={14} />授权</Button>
        <div className="flex flex-wrap gap-3 lg:col-span-3">
          {([
            ["read", "读取"], ["screenshot", "截图"], ["mouse", "鼠标"], ["keyboard", "键盘"], ["launch", "启动"], ["close", "关闭"],
          ] as [keyof PermissionSet, string][]).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-xs">
              <Switch checked={permissions[key]} onCheckedChange={(value) => setPermissions((current) => ({ ...current, [key]: value }))} />
              {label}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

export function WindowsConnectorPanel({ apiBaseUrl = DEFAULT_API }: { apiBaseUrl?: string }) {
  const api = apiBaseUrl || DEFAULT_API;
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nodeResponse, profileResponse] = await Promise.all([
        safeFetch(`${api}/api/windows-connector/nodes`),
        safeFetch(`${api}/api/agents/profiles`),
      ]);
      const nodeData = await nodeResponse.json();
      const profileData = await profileResponse.json();
      if (!nodeResponse.ok) throw new Error(nodeData.detail || "加载 Windows Connector 失败");
      setNodes(nodeData.nodes || []);
      setProfiles(profileData.profiles || []);
    } catch (error) {
      toast.error(String(error));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const grouped = useMemo(() => nodes.map((node) => ({
    node,
    resources: [...(node.resources || [])].sort((a, b) => `${a.app_name}${a.title}`.localeCompare(`${b.app_name}${b.title}`)),
  })), [nodes]);

  const refreshNode = async (nodeId: string) => {
    await safeFetch(`${api}/api/windows-connector/nodes/${encodeURIComponent(nodeId)}/refresh`, { method: "POST" });
    window.setTimeout(() => void load(), 800);
  };

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
      toast.error(String(error));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">本机应用 / Windows Connector</h2>
          <p className="mt-1 text-sm text-muted-foreground">自动发现已配对电脑上的运行应用。微信按实例/账号区分，Chrome/Edge 按窗口或可用的 CDP Tab 区分；只有明确授权的资源才可被 Agent 操作。</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void download()} disabled={downloading}><Download size={14} />下载 Connector</Button>
          <Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} />刷新</Button>
        </div>
      </div>

      <div className="space-y-5">
        {grouped.map(({ node, resources }) => (
          <Card key={node.id} className="p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="font-semibold">{node.name}</div>
                <div className="text-xs text-muted-foreground">{node.id} · Connector {node.connector_version || "未知"}</div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={node.status === "online" ? "default" : "secondary"}>{node.status === "online" ? "在线" : "离线"}</Badge>
                <Button size="sm" variant="outline" disabled={node.status !== "online"} onClick={() => void refreshNode(node.id)}><RefreshCw size={13} />扫描应用</Button>
              </div>
            </div>
            <div className="space-y-3">
              {resources.map((resource) => <ResourceCard key={resource.id} node={node} resource={resource} profiles={profiles} reload={load} />)}
              {!resources.length && <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">暂未发现运行中的可见应用。启动 Connector 后点击“扫描应用”。</div>}
            </div>
          </Card>
        ))}
        {!nodes.length && <Card className="p-10 text-center text-sm text-muted-foreground">暂无已配对 Windows 节点。先在微信桌面页生成配对码并运行 Windows Connector。</Card>}
      </div>
    </div>
  );
}
