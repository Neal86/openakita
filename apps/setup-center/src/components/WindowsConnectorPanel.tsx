import { useCallback, useEffect, useMemo, useState } from "react";
import { AppWindow, Chrome, Download, Link2, MonitorSmartphone, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
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

type PermissionSet = { read: boolean; screenshot: boolean; mouse: boolean; keyboard: boolean; launch: boolean; close: boolean; };
type Grant = { id: string; node_id: string; agent_profile_id: string; resource_id: string; fingerprint: string; remark: string; permissions: PermissionSet; };
type Resource = { id: string; fingerprint: string; kind: string; app_name: string; process_name: string; pid: number; hwnd: number; title: string; exe_path: string; account_name: string; browser_profile: string; tab_id: string; url: string; automation: string; controllable: boolean; limited: boolean; grants: Grant[]; };
type NodeInfo = { id: string; name: string; status: string; connector_version?: string; transport?: string; embedded?: boolean; resources: Resource[]; };
type AgentProfile = { id: string; name: string };

const defaultPermissions: PermissionSet = { read: true, screenshot: true, mouse: true, keyboard: true, launch: false, close: false };

function resourceLabel(resource: Resource): string {
  if (resource.kind === "wechat") return resource.account_name ? `${resource.app_name} · ${resource.account_name}` : `${resource.app_name} · ${resource.title || `PID ${resource.pid}`}`;
  if (resource.kind === "browser_tab") return `${resource.app_name} · ${resource.title || resource.url || resource.tab_id}`;
  return `${resource.app_name} · ${resource.title || `PID ${resource.pid}`}`;
}

function ResourceCard({ api, node, resource, profiles, reload }: { api: string; node: NodeInfo; resource: Resource; profiles: AgentProfile[]; reload: () => Promise<void> }) {
  const [agentId, setAgentId] = useState(profiles[0]?.id || "");
  const [remark, setRemark] = useState("");
  const [permissions, setPermissions] = useState<PermissionSet>(defaultPermissions);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (!agentId && profiles[0]?.id) setAgentId(profiles[0].id); }, [profiles, agentId]);

  const createGrant = async () => {
    if (!agentId) return;
    setSaving(true);
    try {
      const response = await safeFetch(`${api}/api/windows-connector/grants`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ node_id: node.id, agent_profile_id: agentId, resource_id: resource.id, remark, permissions }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "授权失败");
      toast.success("已授权给 Agent"); setRemark(""); await reload();
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)); } finally { setSaving(false); }
  };

  const removeGrant = async (grantId: string) => {
    const response = await safeFetch(`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}`, { method: "DELETE" });
    if (!response.ok) { const data = await response.json().catch(() => ({})); toast.error(data.detail || "取消授权失败"); return; }
    await reload();
  };

  const updateRemark = async (grantId: string, value: string) => {
    const response = await safeFetch(`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}/remark`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ remark: value }) });
    if (!response.ok) toast.error("备注保存失败"); else await reload();
  };

  const isBrowser = resource.kind.startsWith("browser");
  return <div className="space-y-3 rounded-lg border p-4">
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2 font-medium">{isBrowser ? <Chrome size={16} /> : <AppWindow size={16} />}<span>{resourceLabel(resource)}</span><Badge variant="outline">{(resource.automation || "uia").toUpperCase()}</Badge>{resource.limited && <Badge variant="secondary">受限模式</Badge>}</div>
      <div className="mt-1 max-w-3xl truncate text-xs text-muted-foreground">{resource.url || resource.exe_path || resource.process_name}</div>
      <div className="mt-1 text-xs text-muted-foreground">PID {resource.pid || "-"} · HWND {resource.hwnd || "-"} · {resource.kind}</div>
    </div>
    {resource.grants?.length > 0 && <div className="space-y-2">{resource.grants.map(grant => <div key={grant.id} className="rounded-md border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><ShieldCheck size={15} /><span className="text-sm font-medium">{profiles.find(p => p.id === grant.agent_profile_id)?.name || grant.agent_profile_id}</span><span className="text-xs text-muted-foreground">{Object.entries(grant.permissions || {}).filter(([, enabled]) => enabled).map(([key]) => key).join(" · ")}</span></div><Button size="sm" variant="ghost" onClick={() => void removeGrant(grant.id)}><Trash2 size={14} />取消授权</Button></div>
      <div className="mt-2 flex items-center gap-2"><Label className="shrink-0 text-xs">备注</Label><Input defaultValue={grant.remark} placeholder="自定义备注" onBlur={e => { if (e.target.value !== grant.remark) void updateRemark(grant.id, e.target.value); }} /></div>
    </div>)}</div>}
    <div className="grid gap-3 rounded-md border border-dashed p-3 lg:grid-cols-[220px_1fr_auto] lg:items-end">
      <div className="space-y-1.5"><Label>授权给 Agent</Label><Select value={agentId} onValueChange={setAgentId}><SelectTrigger><SelectValue placeholder="选择 Agent" /></SelectTrigger><SelectContent>{profiles.map(profile => <SelectItem key={profile.id} value={profile.id}>{profile.name} ({profile.id})</SelectItem>)}</SelectContent></Select></div>
      <div className="space-y-1.5"><Label>备注</Label><Input value={remark} onChange={e => setRemark(e.target.value)} placeholder={resource.kind === "wechat" ? "客服微信名称" : resource.kind === "browser_tab" ? "Tab 备注" : "应用备注"} /></div>
      <Button disabled={saving || !agentId} onClick={() => void createGrant()}><ShieldCheck size={14} />授权</Button>
      <div className="flex flex-wrap gap-3 lg:col-span-3">{([ ["read", "读取"], ["screenshot", "截图"], ["mouse", "鼠标"], ["keyboard", "键盘"], ["launch", "启动"], ["close", "关闭"] ] as [keyof PermissionSet, string][]).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs"><Switch checked={permissions[key]} onCheckedChange={value => setPermissions(current => ({ ...current, [key]: value }))} />{label}</label>)}</div>
    </div>
  </div>;
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nodeResponse, profileResponse] = await Promise.all([safeFetch(`${api}/api/windows-connector/nodes`), safeFetch(`${api}/api/agents/profiles`)]);
      const nodeData = await nodeResponse.json().catch(() => ({})); const profileData = await profileResponse.json().catch(() => ({}));
      if (!nodeResponse.ok) throw new Error(nodeData.detail || "加载 Windows 设备失败");
      setNodes(nodeData.nodes || []); setProfiles(profileData.profiles || []);
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)); } finally { setLoading(false); }
  }, [api]);

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 10000); return () => window.clearInterval(timer); }, [load]);
  const grouped = useMemo(() => nodes.map(node => ({ node, resources: [...(node.resources || [])].sort((a, b) => `${a.app_name}${a.title}`.localeCompare(`${b.app_name}${b.title}`)) })), [nodes]);

  const refreshNode = async (nodeId: string) => { const response = await safeFetch(`${api}/api/windows-connector/nodes/${encodeURIComponent(nodeId)}/refresh`, { method: "POST" }); if (!response.ok) { const data = await response.json().catch(() => ({})); toast.error(data.detail || "扫描失败"); return; } window.setTimeout(() => void load(), nodeId === "local" ? 150 : 800); };
  const download = async () => { setDownloading(true); try { const response = await safeFetch(`${api}/api/windows-connector/connector/download`); if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Windows Connector 尚未生成"); } const blob = await response.blob(); const href = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = href; anchor.download = "OpenAkita-Windows-Connector-Windows-x64.zip"; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(href); } catch (error) { toast.error(error instanceof Error ? error.message : String(error)); } finally { setDownloading(false); } };
  const createPairingCode = async () => { setPairing(true); try { const response = await safeFetch(`${api}/api/windows-connector/pairing-code`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ node_name: nodeName || "远程 Windows 电脑", ttl_seconds: 3600 }) }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || "生成配对码失败"); setPairingCode(data.code || ""); toast.success("配对码已生成，有效期 1 小时"); } catch (error) { toast.error(error instanceof Error ? error.message : String(error)); } finally { setPairing(false); } };

  const local = grouped.find(entry => entry.node.id === "local"); const remotes = grouped.filter(entry => entry.node.id !== "local");
  const renderNode = ({ node, resources }: { node: NodeInfo; resources: Resource[] }) => { const embedded = node.id === "local" || node.embedded || node.transport === "local"; const online = node.status === "online"; return <Card key={node.id} className="p-4">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><div className="flex items-center gap-2 font-semibold"><MonitorSmartphone size={16} />{node.name || (embedded ? "本机" : node.id)}<Badge variant="outline">{embedded ? "内嵌 Runtime" : "远程 Connector"}</Badge></div><div className="mt-1 text-xs text-muted-foreground">{embedded ? "本机无需安装 Connector，OpenAkita 直接发现和操作已授权应用。" : `${node.id} · Connector ${node.connector_version || "未知"}`}</div></div><div className="flex items-center gap-2"><Badge variant={online ? "default" : "secondary"}>{online ? "在线" : node.status === "unsupported" ? "当前平台不支持" : "离线"}</Badge><Button size="sm" variant="outline" disabled={!online} onClick={() => void refreshNode(node.id)}><RefreshCw size={13} />扫描应用</Button></div></div>
    <div className="space-y-3">{resources.map(resource => <ResourceCard key={resource.id} api={api} node={node} resource={resource} profiles={profiles} reload={load} />)}{!resources.length && <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">{embedded ? "暂未发现运行中的可见应用。先打开微信、浏览器或其他程序，然后点击“扫描应用”。" : "远程设备在线后点击“扫描应用”，即可加载该电脑上的可见应用。"}</div>}</div>
  </Card>; };

  return <div className="h-full overflow-y-auto p-5">
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-bold">Windows 设备</h2><p className="mt-1 text-sm text-muted-foreground">本机使用 OpenAkita 内嵌 Runtime；只有远程 Windows 电脑需要额外 Connector。所有 App 都按设备和资源单独授权给 Agent。</p></div><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} />刷新</Button></div>
    <section className="space-y-3"><div><h3 className="font-semibold">本机</h3><p className="text-xs text-muted-foreground">零配置直连，不需要下载或配对 Connector。</p></div>{local ? renderNode(local) : <Card className="p-8 text-center text-sm text-muted-foreground">正在加载本机 Windows Runtime…</Card>}</section>
    <section className="mt-6 space-y-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">远程设备</h3><p className="text-xs text-muted-foreground">在其他 Windows 电脑上运行 Connector，并使用配对码接入当前 OpenAkita。</p></div><Button variant="outline" onClick={() => void download()} disabled={downloading}><Download size={14} />下载远程 Connector</Button></div>
      <Card className="p-4"><div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end"><div className="space-y-1.5"><Label>远程设备名称</Label><Input value={nodeName} onChange={e => setNodeName(e.target.value)} placeholder="例如：仓库电脑 01" /></div><Button onClick={() => void createPairingCode()} disabled={pairing}><Link2 size={14} />生成配对码</Button></div>{pairingCode && <div className="mt-4 rounded-lg border bg-muted/20 p-4"><div className="text-xs text-muted-foreground">配对码（1 小时内有效）</div><div className="mt-1 select-all font-mono text-2xl font-bold tracking-[0.2em]">{pairingCode}</div><div className="mt-2 text-xs text-muted-foreground">在远程电脑的 OpenAkita Windows Connector 中输入该配对码。配对完成后，该设备会自动出现在下面。</div></div>}</Card>
      <div className="space-y-3">{remotes.map(renderNode)}{!remotes.length && <Card className="p-10 text-center text-sm text-muted-foreground">暂无远程 Windows 设备。下载 Connector 并使用上方配对码连接。</Card>}</div>
    </section>
  </div>;
}
