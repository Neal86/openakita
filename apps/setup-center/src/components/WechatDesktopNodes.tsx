import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Copy, Download, RefreshCw, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { safeFetch } from "../providers";

type Conversation = { id: string; name: string; type: string };
type Account = {
  id: string;
  nickname: string;
  avatar_url?: string;
  login_status: string;
  groups: Conversation[];
  contacts: Conversation[];
};
type Node = {
  id: string;
  name: string;
  status: string;
  connector_version: string;
  last_heartbeat_at?: string | null;
  accounts: Account[];
};

export function WechatDesktopNodes({ apiBase }: { apiBase: string }) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [nodeName, setNodeName] = useState("Windows 微信节点");
  const [pairCode, setPairCode] = useState("");
  const [pairExpires, setPairExpires] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await safeFetch(`${apiBase}/api/wechat-desktop/nodes`);
      const data = await response.json();
      setNodes(data.nodes || []);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载节点失败");
    }
  }, [apiBase]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const generateCode = async () => {
    setBusy(true);
    try {
      if (pairCode) {
        await safeFetch(`${apiBase}/api/wechat-desktop/pairing-code/close`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: pairCode }),
        });
      }
      const response = await safeFetch(`${apiBase}/api/wechat-desktop/pairing-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_name: nodeName, ttl_seconds: 3600 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "生成失败");
      setPairCode(data.code);
      setPairExpires(data.expires_in || null);
      setMessage("新配对码已生成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "生成配对码失败");
    } finally {
      setBusy(false);
    }
  };

  const closeCode = async () => {
    const code = pairCode;
    setPairCode("");
    setPairExpires(null);
    if (!code) return;
    await safeFetch(`${apiBase}/api/wechat-desktop/pairing-code/close`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).catch(() => undefined);
  };

  const removeNode = async (node: Node) => {
    if (!window.confirm(`确定撤销节点“${node.name}”吗？`)) return;
    const response = await safeFetch(`${apiBase}/api/wechat-desktop/nodes/${encodeURIComponent(node.id)}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setMessage(data.detail || "撤销失败");
      return;
    }
    setExpanded(current => {
      const next = new Set(current);
      next.delete(node.id);
      return next;
    });
    await load();
  };

  const toggle = (id: string) => setExpanded(current => {
    const next = new Set(current);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <div className="h-full w-full overflow-auto p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">微信桌面 Connector</h2>
          <p className="text-sm text-muted-foreground">管理 Windows 微信节点、配对和 Connector 下载。</p>
        </div>
        <Button variant="outline" onClick={() => void load()}><RefreshCw className="mr-2 h-4 w-4" />刷新节点</Button>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">添加 Windows Connector</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
            <div className="space-y-1.5"><Label>节点名称</Label><Input value={nodeName} onChange={event => setNodeName(event.target.value)} /></div>
            <Button onClick={() => void generateCode()} disabled={busy}>{pairCode ? "刷新配对码" : "生成配对码"}</Button>
            <Button variant="outline" onClick={() => window.open(`${apiBase}/api/wechat-desktop/connector/download`, "_blank")}><Download className="mr-2 h-4 w-4" />下载 Windows Connector</Button>
          </div>
          {pairCode && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 p-4">
              <div><div className="text-xs text-muted-foreground">配对码</div><div className="font-mono text-2xl font-semibold tracking-[0.3em]">{pairCode}</div></div>
              <Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(pairCode)}><Copy className="mr-1 h-4 w-4" />复制</Button>
              <Button size="sm" variant="outline" onClick={() => void generateCode()}><RefreshCw className="mr-1 h-4 w-4" />刷新</Button>
              <Button size="sm" variant="ghost" onClick={() => void closeCode()}><X className="mr-1 h-4 w-4" />关闭</Button>
              {pairExpires && <span className="text-xs text-muted-foreground">最长有效 {Math.round(pairExpires / 60)} 分钟；配对成功后自动失效</span>}
            </div>
          )}
          {message && <div className="text-sm text-muted-foreground">{message}</div>}
        </CardContent>
      </Card>

      <div className="space-y-3">
        {nodes.map(node => {
          const open = expanded.has(node.id);
          const account = node.accounts?.[0];
          return (
            <Card key={node.id}>
              <button type="button" className="flex w-full items-center justify-between gap-3 p-4 text-left" onClick={() => toggle(node.id)}>
                <div className="flex min-w-0 items-center gap-3">
                  {open ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                  <div className="min-w-0"><div className="truncate font-medium">{node.name}</div><div className="truncate text-xs text-muted-foreground">{account?.nickname || "未检测到微信账号"} · {node.connector_version || "版本未知"}</div></div>
                </div>
                <Badge variant={node.status === "online" ? "default" : "secondary"}>{node.status === "online" ? "在线" : "离线"}</Badge>
              </button>
              {open && (
                <CardContent className="border-t pt-4 space-y-4">
                  <div className="grid gap-4 text-sm md:grid-cols-3">
                    <div><div className="text-muted-foreground">节点 ID</div><div className="mt-1 break-all font-mono text-xs">{node.id}</div></div>
                    <div><div className="text-muted-foreground">当前微信账号</div><div className="mt-1 font-medium">{account?.nickname || "未登录"}</div></div>
                    <div><div className="text-muted-foreground">最后心跳</div><div className="mt-1 font-medium">{node.last_heartbeat_at ? new Date(node.last_heartbeat_at).toLocaleString() : "无"}</div></div>
                    <div><div className="text-muted-foreground">Connector 版本</div><div className="mt-1 font-medium">{node.connector_version || "未知"}</div></div>
                    <div><div className="text-muted-foreground">群聊</div><div className="mt-1 font-medium">{account?.groups?.length || 0}</div></div>
                    <div><div className="text-muted-foreground">联系人</div><div className="mt-1 font-medium">{account?.contacts?.length || 0}</div></div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => window.open(`${apiBase}/api/wechat-desktop/connector/download`, "_blank")}><Download className="mr-1 h-4 w-4" />下载 Connector</Button>
                    <Button size="sm" variant="destructive" onClick={() => void removeNode(node)}><Trash2 className="mr-1 h-4 w-4" />撤销节点</Button>
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
        {!nodes.length && <Card><CardContent className="py-10 text-center text-muted-foreground">暂无 Windows 微信节点</CardContent></Card>}
      </div>
    </div>
  );
}
