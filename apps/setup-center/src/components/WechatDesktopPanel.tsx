import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, Link2, Loader2, Monitor, RefreshCw, Save, Smartphone } from "lucide-react";
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

const emptyForm = {
  id: "",
  name: "微信（桌面版）",
  nodeId: "",
  accountId: "",
  agentId: "default",
  allowedGroups: [] as string[],
  allowedContacts: [] as string[],
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

export function WechatDesktopPanel({ apiBaseUrl }: { apiBaseUrl?: string }) {
  const api = apiBaseUrl ?? DEFAULT_API;
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [pairingCode, setPairingCode] = useState("");
  const [pairingName, setPairingName] = useState("客服电脑");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(emptyForm);

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
      setNodes(nodesData.nodes || []);
      setProfiles(profilesData.profiles || []);
      const desktopBots = (botsData.bots || []).filter((b: Bot) => b.type === "wechat_desktop");
      setBots(desktopBots);
      if (desktopBots.length && !form.id) {
        editBot(desktopBots[0]);
      }
    } catch (error) {
      toast.error(`微信（桌面版）数据加载失败：${String(error)}`);
    } finally {
      setLoading(false);
    }
  }, [api, form.id]);

  useEffect(() => { load(); }, [load]);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === form.nodeId),
    [nodes, form.nodeId],
  );
  const selectedAccount = useMemo(
    () => selectedNode?.accounts.find((account) => account.id === form.accountId),
    [selectedNode, form.accountId],
  );

  function editBot(bot: Bot) {
    const c = bot.credentials || {};
    setForm({
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
    });
  }

  async function createPairingCode() {
    try {
      const res = await safeFetch(`${api}/api/wechat-desktop/pairing-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_name: pairingName || "客服电脑", ttl_seconds: 600 }),
      });
      const data = await res.json();
      setPairingCode(data.code || "");
      toast.success("配对码已生成，10 分钟内有效");
    } catch (error) {
      toast.error(`生成配对码失败：${String(error)}`);
    }
  }

  function toggleConversation(kind: "group" | "contact", id: string, checked: boolean) {
    const key = kind === "group" ? "allowedGroups" : "allowedContacts";
    setForm((prev) => ({
      ...prev,
      [key]: checked ? [...prev[key], id] : prev[key].filter((value) => value !== id),
    }));
  }

  async function saveBot(restart: boolean) {
    if (!form.nodeId || !form.accountId || !form.agentId) {
      toast.error("必须选择 Windows 节点、微信账号和绑定 Agent");
      return;
    }
    const selected = nodes.find((node) => node.id === form.nodeId)?.accounts.find((a) => a.id === form.accountId);
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
      ignore_senders: form.ignoreSenders.split(/[,，\n]/).map((v) => v.trim()).filter(Boolean),
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
      await safeFetch(`${api}/api/agents/bots${exists ? `/${id}` : ""}`, {
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
      setForm((prev) => ({ ...prev, id }));
      toast.success("微信（桌面版）Bot 已保存");
      await load();
      if (restart) {
        await safeFetch(`${api}/api/restart`, { method: "POST" }).catch(() => undefined);
      }
    } catch (error) {
      toast.error(`保存失败：${String(error)}`);
    } finally {
      setSaving(false);
    }
  }

  function downloadConnector() {
    window.location.href = `${api}/api/wechat-desktop/connector/download`;
  }

  return (
    <Card className="mt-4 p-4 space-y-5 border-emerald-200 dark:border-emerald-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="font-bold flex items-center gap-2"><Smartphone size={18} />微信（桌面版）</h4>
          <p className="text-xs text-muted-foreground mt-1">连接 Windows 微信电脑版，并将具体微信账号绑定到指定 Agent。</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={downloadConnector}><Download size={14} />下载 Windows Connector</Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} />刷新</Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] items-end rounded-lg border p-3">
        <div className="space-y-1.5"><Label>Windows 节点名称</Label><Input value={pairingName} onChange={(e) => setPairingName(e.target.value)} /></div>
        <Button onClick={createPairingCode}><Link2 size={14} />生成配对码</Button>
        <div className="min-w-28 rounded-md bg-muted px-4 py-2 text-center font-mono font-bold tracking-widest">{pairingCode || "--------"}</div>
      </div>

      {bots.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {bots.map((bot) => <Button key={bot.id} size="sm" variant={form.id === bot.id ? "default" : "outline"} onClick={() => editBot(bot)}>{bot.name || bot.id}</Button>)}
          <Button size="sm" variant="ghost" onClick={() => setForm(emptyForm)}>新建 Bot</Button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5"><Label>Bot 名称</Label><Input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} /></div>
        <div className="space-y-1.5"><Label>绑定 Agent</Label><Select value={form.agentId} onValueChange={(value) => setForm((p) => ({ ...p, agentId: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="default">默认 Agent</SelectItem>{profiles.map((p) => <SelectItem key={p.id} value={p.id}>{p.name} ({p.id})</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><Label>Windows 节点</Label><Select value={form.nodeId} onValueChange={(value) => setForm((p) => ({ ...p, nodeId: value, accountId: "", allowedGroups: [], allowedContacts: [] }))}><SelectTrigger><SelectValue placeholder="选择在线节点" /></SelectTrigger><SelectContent>{nodes.map((node) => <SelectItem key={node.id} value={node.id}>{node.name} · {node.status}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><Label>微信账号</Label><Select value={form.accountId} onValueChange={(value) => setForm((p) => ({ ...p, accountId: value, allowedGroups: [], allowedContacts: [] }))} disabled={!selectedNode}><SelectTrigger><SelectValue placeholder="选择节点上的微信" /></SelectTrigger><SelectContent>{selectedNode?.accounts.map((account) => <SelectItem key={account.id} value={account.id}>{account.nickname} · {account.login_status}</SelectItem>)}</SelectContent></Select></div>
      </div>

      {selectedAccount && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border p-3"><div className="font-semibold text-sm mb-2">允许回复的群聊</div><div className="max-h-52 overflow-y-auto space-y-2">{selectedAccount.groups.map((item) => <label key={item.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.allowedGroups.includes(item.id)} onCheckedChange={(v) => toggleConversation("group", item.id, Boolean(v))} />{item.name}</label>)}</div></div>
          <div className="rounded-lg border p-3"><div className="font-semibold text-sm mb-2">允许回复的联系人</div><div className="max-h-52 overflow-y-auto space-y-2">{selectedAccount.contacts.map((item) => <label key={item.id} className="flex items-center gap-2 text-sm"><Checkbox checked={form.allowedContacts.includes(item.id)} onCheckedChange={(v) => toggleConversation("contact", item.id, Boolean(v))} />{item.name}</label>)}</div></div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">自动回复<Switch checked={form.autoReply} onCheckedChange={(v) => setForm((p) => ({ ...p, autoReply: v }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">人工接管<Switch checked={form.humanTakeover} onCheckedChange={(v) => setForm((p) => ({ ...p, humanTakeover: v }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">仅被 @ 时回复<Switch checked={form.mentionOnly} onCheckedChange={(v) => setForm((p) => ({ ...p, mentionOnly: v }))} /></label>
        <label className="flex items-center justify-between rounded-lg border p-3 text-sm">允许私聊<Switch checked={form.privateChatEnabled} onCheckedChange={(v) => setForm((p) => ({ ...p, privateChatEnabled: v }))} /></label>
      </div>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        <div className="space-y-1"><Label>忽略发送人</Label><Input value={form.ignoreSenders} onChange={(e) => setForm((p) => ({ ...p, ignoreSenders: e.target.value }))} placeholder="昵称用逗号分隔" /></div>
        <div className="space-y-1"><Label>消息合并窗口（秒）</Label><Input type="number" min={0} value={form.mergeWindowSeconds} onChange={(e) => setForm((p) => ({ ...p, mergeWindowSeconds: Number(e.target.value) }))} /></div>
        <div className="space-y-1"><Label>最小发送间隔（秒）</Label><Input type="number" min={0} value={form.sendIntervalSeconds} onChange={(e) => setForm((p) => ({ ...p, sendIntervalSeconds: Number(e.target.value) }))} /></div>
        <div className="space-y-1"><Label>重复消息有效期（秒）</Label><Input type="number" min={1} value={form.duplicateTtlSeconds} onChange={(e) => setForm((p) => ({ ...p, duplicateTtlSeconds: Number(e.target.value) }))} /></div>
        <div className="space-y-1"><Label>Agent 超时（秒）</Label><Input type="number" min={1} value={form.agentTimeoutSeconds} onChange={(e) => setForm((p) => ({ ...p, agentTimeoutSeconds: Number(e.target.value) }))} /></div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => saveBot(false)} disabled={saving}>{saving ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}仅保存</Button>
        <Button onClick={() => saveBot(true)} disabled={saving}><Monitor size={14} />保存并重启</Button>
      </div>
    </Card>
  );
}
