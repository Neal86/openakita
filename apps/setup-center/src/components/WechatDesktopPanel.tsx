import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ChevronDown, ChevronRight, Copy, Download, Link2, Loader2,
  Monitor, RefreshCw, Save, Smartphone, Trash2, X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { safeFetch } from "../providers";

const DEFAULT_API = "http://127.0.0.1:18900";

type Conversation = { id: string; name: string; type: string };
type Account = {
  id: string;
  nickname: string;
  login_status: string;
  groups: Conversation[];
  contacts: Conversation[];
};
type NodeInfo = {
  id: string;
  name: string;
  status: string;
  connector_version?: string;
  last_heartbeat_at?: string | null;
  accounts: Account[];
};
type AgentProfile = { id: string; name: string };
type Bot = {
  id: string;
  type: string;
  name: string;
  agent_profile_id: string;
  enabled: boolean;
  credentials: Record<string, unknown>;
};

type EditorForm = {
  id: string;
  name: string;
  nodeId: string;
  accountId: string;
  agentId: string;
  allowedGroups: string[];
  allowedContacts: string[];
  ignoreSenders: string;
  mentionOnly: boolean;
  privateChatEnabled: boolean;
  autoReply: boolean;
  humanTakeover: boolean;
  mergeWindowSeconds: number;
  sendIntervalSeconds: number;
  duplicateTtlSeconds: number;
  agentTimeoutSeconds: number;
};

const emptyForm: EditorForm = {
  id: "",
  name: "微信（桌面版）",
  nodeId: "",
  accountId: "",
  agentId: "default",
  allowedGroups: [],
  allowedContacts: [],
  ignoreSenders: "",
  mentionOnly: false,
  privateChatEnabled: false,
  autoReply: true,
  humanTakeover: false,
  mergeWindowSeconds: 2,
  sendIntervalSeconds: 3,
  duplicateTtlSeconds: 600,
  agentTimeoutSeconds: 180,
};

function formFromBot(bot: Bot): EditorForm {
  const c = bot.credentials || {};
  return {
    id: bot.id,
    name: bot.name || "微信（桌面版）",
    nodeId: String(c.node_id || ""),
    accountId: String(c.wechat_account_id || ""),
    agentId: bot.agent_profile_id || "default",
    allowedGroups: Array.isArray(c.allowed_groups) ? c.allowed_groups.map(String) : [],
    allowedContacts: Array.isArray(c.allowed_contacts) ? c.allowed_contacts.map(String) : [],
    ignoreSenders: Array.isArray(c.ignore_senders) ? c.ignore_senders.join(", ") : "",
    mentionOnly: Boolean(c.mention_only),
    privateChatEnabled: Boolean(c.private_chat_enabled),
    autoReply: c.auto_reply !== false,
    humanTakeover: Boolean(c.human_takeover),
    mergeWindowSeconds: Number(c.merge_window_seconds || 2),
    sendIntervalSeconds: Number(c.send_interval_seconds || 3),
    duplicateTtlSeconds: Number(c.duplicate_ttl_seconds || 600),
    agentTimeoutSeconds: Number(c.agent_timeout_seconds || 180),
  };
}

export function WechatDesktopPanel({ apiBaseUrl }: { apiBaseUrl?: string }) {
  const api = apiBaseUrl ?? DEFAULT_API;
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [pairingCode, setPairingCode] = useState("");
  const [pairingName, setPairingName] = useState("客服电脑");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [form, setForm] = useState<EditorForm>(emptyForm);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nodesRes, profilesRes, botsRes] = await Promise.all([
        safeFetch(`${api}/api/wechat-desktop/nodes`),
        safeFetch(`${api}/api/agents/profiles`),
        safeFetch(`${api}/api/agents/bots`),
      ]);
      const nodesData = await nodesRes.json();
      const profilesData = await profilesRes.json();
      const botsData = await botsRes.json();
      const nextNodes: NodeInfo[] = nodesData.nodes || [];
      const desktopBots: Bot[] = (botsData.bots || []).filter((bot: Bot) => bot.type === "wechat_desktop");
      setNodes(nextNodes);
      setProfiles(profilesData.profiles || []);
      setBots(desktopBots);
      setExpandedNodes((current) => {
        if (current.size || !nextNodes.length) return current;
        return new Set([nextNodes[0].id]);
      });
    } catch (error) {
      toast.error(`微信（桌面版）数据加载失败：${String(error)}`);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === form.nodeId),
    [nodes, form.nodeId],
  );
  const selectedAccount = useMemo(
    () => selectedNode?.accounts.find((account) => account.id === form.accountId),
    [selectedNode, form.accountId],
  );

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((current) => {
      const next = new Set(current);
      next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId);
      return next;
    });
  };

  const editBot = (bot: Bot) => {
    const nextForm = formFromBot(bot);
    setForm(nextForm);
    setExpandedNodes((current) => new Set(current).add(nextForm.nodeId));
  };

  const newBotForNode = (node: NodeInfo) => {
    const account = node.accounts[0];
    setForm({
      ...emptyForm,
      name: `${node.name} 微信客服`,
      nodeId: node.id,
      accountId: account?.id || "",
    });
    setExpandedNodes((current) => new Set(current).add(node.id));
  };

  const closePairingCode = useCallback(async () => {
    const code = pairingCode;
    setPairingCode("");
    if (!code) return;
    await safeFetch(`${api}/api/wechat-desktop/pairing-code/close`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).catch(() => undefined);
  }, [api, pairingCode]);

  const createPairingCode = async () => {
    try {
      if (pairingCode) await closePairingCode();
      const response = await safeFetch(`${api}/api/wechat-desktop/pairing-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_name: pairingName || "客服电脑", ttl_seconds: 3600 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "生成配对码失败");
      setPairingCode(data.code || "");
      toast.success("新配对码已生成；可手动刷新或关闭，配对成功后自动失效");
    } catch (error) {
      toast.error(`生成配对码失败：${String(error)}`);
    }
  };

  const revokeNode = async (node: NodeInfo) => {
    if (!window.confirm(`确定撤销 Windows 节点“${node.name}”吗？`)) return;
    try {
      const response = await safeFetch(`${api}/api/wechat-desktop/nodes/${encodeURIComponent(node.id)}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "撤销节点失败");
      }
      if (form.nodeId === node.id) setForm(emptyForm);
      toast.success("Windows 节点已撤销");
      await load();
    } catch (error) {
      toast.error(String(error));
    }
  };

  const toggleConversation = (kind: "group" | "contact", id: string, checked: boolean) => {
    const key = kind === "group" ? "allowedGroups" : "allowedContacts";
    setForm((previous) => ({
      ...previous,
      [key]: checked ? [...previous[key], id] : previous[key].filter((value) => value !== id),
    }));
  };

  const saveBot = async (restart: boolean) => {
    if (!form.nodeId || !form.accountId || !form.agentId) {
      toast.error("必须选择 Windows 节点、微信账号和绑定 Agent");
      return;
    }
    const selected = nodes.find((node) => node.id === form.nodeId)?.accounts.find((account) => account.id === form.accountId);
    if (!selected) {
      toast.error("所选微信账号当前不存在或节点离线");
      return;
    }
    const id = form.id || `wechat-desktop-${Math.random().toString(36).slice(2, 7)}`;
    const credentials = {
      node_id: form.nodeId,
      wechat_account_id: form.accountId,
      wechat_account_name: selected.nickname,
      allowed_groups: form.allowedGroups,
      allowed_contacts: form.allowedContacts,
      ignore_senders: form.ignoreSenders.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean),
      mention_only: form.mentionOnly,
      private_chat_enabled: form.privateChatEnabled,
      auto_reply: form.autoReply,
      human_takeover: form.humanTakeover,
      merge_window_seconds: form.mergeWindowSeconds,
      send_interval_seconds: form.sendIntervalSeconds,
      duplicate_ttl_seconds: form.duplicateTtlSeconds,
      agent_timeout_seconds: form.agentTimeoutSeconds,
    };
    setSaving(true);
    try {
      const exists = bots.some((bot) => bot.id === id);
      const response = await safeFetch(`${api}/api/agents/bots${exists ? `/${id}` : ""}`, {
        method: exists ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exists ? {
          type: "wechat_desktop",
          name: form.name,
          agent_profile_id: form.agentId,
          enabled: true,
          credentials,
        } : {
          id,
          type: "wechat_desktop",
          name: form.name,
          agent_profile_id: form.agentId,
          enabled: true,
          credentials,
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "保存失败");
      }
      setForm((previous) => ({ ...previous, id }));
      toast.success("微信（桌面版）Bot 已保存");
      await load();
      if (restart) await safeFetch(`${api}/api/restart`, { method: "POST" }).catch(() => undefined);
    } catch (error) {
      toast.error(`保存失败：${String(error)}`);
    } finally {
      setSaving(false);
    }
  };

  const downloadConnector = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const response = await safeFetch(`${api}/api/wechat-desktop/connector/download`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "发布包尚未生成");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const plainFilename = disposition.match(/filename=\"?([^\";]+)\"?/i)?.[1];
      const filename = plainFilename || "OpenAkita-WeChat-Connector-Windows-x64.zip";
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      toast.success("Windows Connector 下载已开始");
    } catch (error) {
      toast.error(`下载 Windows Connector 失败：${String(error)}`);
    } finally {
      setDownloading(false);
    }
  };

  const editor = form.nodeId ? (
    <div className="space-y-4 rounded-lg border bg-muted/10 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">{form.id ? `编辑 Bot：${form.name}` : "新建微信桌面 Bot"}</div>
        {form.id && <Button size="sm" variant="ghost" onClick={() => setForm(emptyForm)}>关闭编辑</Button>}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5"><Label>Bot 名称</Label><Input value={form.name} onChange={(event) => setForm((previous) => ({ ...previous, name: event.target.value }))} /></div>
        <div className="space-y-1.5"><Label>绑定 Agent</Label><Select value={form.agentId} onValueChange={(value) => setForm((previous) => ({ ...previous, agentId: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="default">默认 Agent</SelectItem>{profiles.map((profile) => <SelectItem key={profile.id} value={profile.id}>{profile.name} ({profile.id})</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><Label>Windows 节点</Label><Select value={form.nodeId} onValueChange={(value) => setForm((previous) => ({ ...previous, nodeId: value, accountId: "", allowedGroups: [], allowedContacts: [] }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{nodes.map((node) => <SelectItem key={node.id} value={node.id}>{node.name} · {node.status}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><Label>微信账号</Label><Select value={form.accountId} onValueChange={(value) => setForm((previous) => ({ ...previous, accountId: value, allowedGroups: [], allowedContacts: [] }))} disabled={!selectedNode}><SelectTrigger><SelectValue placeholder="选择节点上的微信" /></SelectTrigger><SelectContent>{selectedNode?.accounts.map((account) => <SelectItem key={account.id} value={account.id}>{account.nickname} · {account.login_status}</SelectItem>)}</SelectContent></Select></div>
      </div>
      {selectedAccount && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border p-3"><div className="mb-2 text-sm font-semibold">允许回复的群聊</div><div className="max-h-52 space-y-2 overflow-y-auto">{selectedAccount.groups.map((item) => <label key={item.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.allowedGroups.includes(item.id)} onCheckedChange={(value) => toggleConversation("group", item.id, Boolean(value))} />{item.name}</label>)}</div></div>
          <div className="rounded-lg border p-3"><div className="mb-2 text-sm font-semibold">允许回复的联系人</div><div className="max-h-52 space-y-2 overflow-y-auto">{selectedAccount.contacts.map((item) => <label key={item.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.allowedContacts.includes(item.id)} onCheckedChange={(value) => toggleConversation("contact", item.id, Boolean(value))} />{item.name}</label>)}</div></div>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">自动回复<Switch checked={form.autoReply} onCheckedChange={(value) => setForm((previous) => ({ ...previous, autoReply: value }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">人工接管<Switch checked={form.humanTakeover} onCheckedChange={(value) => setForm((previous) => ({ ...previous, humanTakeover: value }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">仅被 @ 时回复<Switch checked={form.mentionOnly} onCheckedChange={(value) => setForm((previous) => ({ ...previous, mentionOnly: value }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">允许私聊<Switch checked={form.privateChatEnabled} onCheckedChange={(value) => setForm((previous) => ({ ...previous, privateChatEnabled: value }))} /></label>
      </div>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        <div className="space-y-1"><Label>忽略发送人</Label><Input value={form.ignoreSenders} onChange={(event) => setForm((previous) => ({ ...previous, ignoreSenders: event.target.value }))} placeholder="昵称用逗号分隔" /></div>
        <div className="space-y-1"><Label>消息合并窗口（秒）</Label><Input type="number" min={0} value={form.mergeWindowSeconds} onChange={(event) => setForm((previous) => ({ ...previous, mergeWindowSeconds: Number(event.target.value) }))} /></div>
        <div className="space-y-1"><Label>最小发送间隔（秒）</Label><Input type="number" min={0} value={form.sendIntervalSeconds} onChange={(event) => setForm((previous) => ({ ...previous, sendIntervalSeconds: Number(event.target.value) }))} /></div>
        <div className="space-y-1"><Label>重复消息有效期（秒）</Label><Input type="number" min={1} value={form.duplicateTtlSeconds} onChange={(event) => setForm((previous) => ({ ...previous, duplicateTtlSeconds: Number(event.target.value) }))} /></div>
        <div className="space-y-1"><Label>Agent 超时（秒）</Label><Input type="number" min={1} value={form.agentTimeoutSeconds} onChange={(event) => setForm((previous) => ({ ...previous, agentTimeoutSeconds: Number(event.target.value) }))} /></div>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => void saveBot(false)} disabled={saving}>{saving ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}仅保存</Button>
        <Button onClick={() => void saveBot(true)} disabled={saving}><Monitor size={14} />保存并重启</Button>
      </div>
    </div>
  ) : null;

  return (
    <Card className="mt-4 space-y-5 border-emerald-200 p-4 dark:border-emerald-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="flex items-center gap-2 font-bold"><Smartphone size={18} />微信（桌面版）</h4>
          <p className="mt-1 text-xs text-muted-foreground">展开不同 Windows Connector，查看状态并编辑对应的微信 Bot。</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void downloadConnector()} disabled={downloading}>{downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}下载 Windows Connector</Button>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} />刷新</Button>
        </div>
      </div>

      <div className="rounded-lg border p-3">
        <div className="grid items-end gap-3 md:grid-cols-[1fr_auto]">
          <div className="space-y-1.5"><Label>Windows 节点名称</Label><Input value={pairingName} onChange={(event) => setPairingName(event.target.value)} /></div>
          <Button onClick={() => void createPairingCode()}><Link2 size={14} />{pairingCode ? "刷新配对码" : "生成配对码"}</Button>
        </div>
        {pairingCode && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-muted px-4 py-3">
            <span className="text-xs text-muted-foreground">配对码</span>
            <span className="font-mono text-xl font-bold tracking-[0.3em]">{pairingCode}</span>
            <Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(pairingCode)}><Copy size={14} />复制</Button>
            <Button size="sm" variant="outline" onClick={() => void createPairingCode()}><RefreshCw size={14} />刷新</Button>
            <Button size="sm" variant="ghost" onClick={() => void closePairingCode()}><X size={14} />关闭</Button>
            <span className="text-xs text-muted-foreground">最长有效 60 分钟；配对成功后自动失效</span>
          </div>
        )}
      </div>

      <div className="space-y-3">
        {nodes.map((node) => {
          const open = expandedNodes.has(node.id);
          const nodeBots = bots.filter((bot) => String(bot.credentials?.node_id || "") === node.id);
          const account = node.accounts[0];
          return (
            <div key={node.id} className="overflow-hidden rounded-lg border">
              <button type="button" className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-muted/40" onClick={() => toggleNode(node.id)}>
                <div className="flex min-w-0 items-center gap-3">
                  {open ? <ChevronDown size={16} className="shrink-0" /> : <ChevronRight size={16} className="shrink-0" />}
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{node.name}</div>
                    <div className="truncate text-xs text-muted-foreground">{account?.nickname || "未检测到微信账号"} · Connector {node.connector_version || "版本未知"} · {nodeBots.length} 个 Bot</div>
                  </div>
                </div>
                <Badge variant={node.status === "online" ? "default" : "secondary"}>{node.status === "online" ? "在线" : "离线"}</Badge>
              </button>
              {open && (
                <div className="space-y-4 border-t p-4">
                  <div className="grid gap-4 text-sm md:grid-cols-3">
                    <div><div className="text-muted-foreground">节点 ID</div><div className="mt-1 break-all font-mono text-xs">{node.id}</div></div>
                    <div><div className="text-muted-foreground">当前微信账号</div><div className="mt-1 font-medium">{account?.nickname || "未登录"}</div></div>
                    <div><div className="text-muted-foreground">最后心跳</div><div className="mt-1 font-medium">{node.last_heartbeat_at ? new Date(node.last_heartbeat_at).toLocaleString() : "无"}</div></div>
                    <div><div className="text-muted-foreground">Connector 版本</div><div className="mt-1 font-medium">{node.connector_version || "未知"}</div></div>
                    <div><div className="text-muted-foreground">群聊</div><div className="mt-1 font-medium">{account?.groups.length || 0}</div></div>
                    <div><div className="text-muted-foreground">联系人</div><div className="mt-1 font-medium">{account?.contacts.length || 0}</div></div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {nodeBots.map((bot) => <Button key={bot.id} size="sm" variant={form.id === bot.id ? "default" : "outline"} onClick={() => editBot(bot)}>{bot.name || bot.id}</Button>)}
                    <Button size="sm" variant="outline" onClick={() => newBotForNode(node)}>添加 Bot</Button>
                    <Button size="sm" variant="destructive" onClick={() => void revokeNode(node)}><Trash2 size={14} />撤销节点</Button>
                  </div>
                  {form.nodeId === node.id && editor}
                </div>
              )}
            </div>
          );
        })}
        {!nodes.length && <div className="rounded-lg border py-10 text-center text-sm text-muted-foreground">暂无 Windows 微信节点。请先生成配对码，并在桌面 Connector 中完成配对。</div>}
      </div>
    </Card>
  );
}
