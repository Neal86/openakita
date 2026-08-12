import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Play, Square, RotateCw, Activity, FileText, Trash2, MonitorSmartphone, Cpu } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { WindowsConnectorPanel } from "../components/WindowsConnectorPanel";
import {
  deleteExecutionInstance,
  instanceAction,
  instanceLogs,
  listExecutionInstances,
  type ExecutionInstance,
} from "../api/executionInstances";

const statusLabel = (value: string) => ({
  running: "运行正常",
  stopped: "已停止",
  pending: "等待启动",
  starting: "启动中",
  error: "异常",
  healthy: "健康",
  degraded: "不稳定",
  unhealthy: "不可用",
  unknown: "未知",
  disabled: "已停止",
}[value] || value);

type PageMode = "hermes" | "windows";
const PAGE_EVENT = "openakita:execution-page-change";
const PAGE_KEY = "openakita:execution-page";

function initialPage(): PageMode {
  const value = window.sessionStorage.getItem(PAGE_KEY);
  return value === "windows" ? "windows" : "hermes";
}

export function ExecutionInstancesView({ apiBaseUrl = "http://127.0.0.1:18900" }: { apiBaseUrl?: string }) {
  const [page, setPage] = useState<PageMode>(initialPage);
  const [instances, setInstances] = useState<ExecutionInstance[]>([]);
  const [dockerAvailable, setDockerAvailable] = useState(false);
  const [nativeAvailable, setNativeAvailable] = useState(false);
  const [nativeDefault, setNativeDefault] = useState(false);
  const [platform, setPlatform] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [logs, setLogs] = useState<{ name: string; content: string; native: boolean } | null>(null);

  const changePage = useCallback((next: PageMode) => {
    window.sessionStorage.setItem(PAGE_KEY, next);
    setPage(next);
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ page?: string }>).detail;
      changePage(detail?.page === "windows" ? "windows" : "hermes");
    };
    window.addEventListener(PAGE_EVENT, listener);
    return () => window.removeEventListener(PAGE_EVENT, listener);
  }, [changePage]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listExecutionInstances(apiBaseUrl);
      setInstances(result.instances || []);
      setDockerAvailable(result.docker_available);
      setNativeAvailable(Boolean(result.native_available));
      setNativeDefault(Boolean(result.native_default));
      setPlatform(result.platform || "");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (instance: ExecutionInstance, action: "start" | "stop" | "restart" | "test") => {
    setBusy(`${instance.id}:${action}`);
    try {
      await instanceAction(apiBaseUrl, instance.id, action);
      setMessage(action === "test" ? "Hermes Runtime 测试通过" : "操作已完成");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy("");
    }
  };

  const showLogs = async (instance: ExecutionInstance) => {
    setBusy(`${instance.id}:logs`);
    try {
      setLogs({ name: instance.name, content: await instanceLogs(apiBaseUrl, instance.id), native: Boolean(instance.runtime?.native) });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取日志失败");
    } finally {
      setBusy("");
    }
  };

  const remove = async (instance: ExecutionInstance) => {
    if (instance.mode === "shared") return;
    const noun = instance.runtime?.native ? "实例" : "容器";
    if (!window.confirm(`确定删除 ${instance.name} 的${noun}吗？数据目录会保留。`)) return;
    setBusy(`${instance.id}:delete`);
    try {
      await deleteExecutionInstance(apiBaseUrl, instance.id, false);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy("");
    }
  };

  if (page === "windows") {
    return <div className="h-full min-h-0"><div className="border-b px-5 pt-4"><div className="inline-flex rounded-lg border p-1"><Button size="sm" variant="ghost" onClick={() => changePage("hermes")}><Cpu className="mr-1 h-4 w-4" />Hermes 实例</Button><Button size="sm" variant="secondary"><MonitorSmartphone className="mr-1 h-4 w-4" />Windows 设备</Button></div></div><WindowsConnectorPanel apiBaseUrl={apiBaseUrl} /></div>;
  }

  return (
    <div className="pageContainer space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="pageTitle">执行模式实例</h1>
          <p className="pageDescription">Windows 桌面版优先使用内嵌 Hermes Runtime，不需要 Docker；服务器环境仍可使用 Docker/Compose。</p>
          <div className="mt-3 inline-flex rounded-lg border p-1"><Button size="sm" variant="secondary"><Cpu className="mr-1 h-4 w-4" />Hermes 实例</Button><Button size="sm" variant="ghost" onClick={() => changePage("windows")}><MonitorSmartphone className="mr-1 h-4 w-4" />Windows 设备</Button></div>
        </div>
        <Button variant="outline" onClick={() => void refresh()} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />刷新</Button>
      </div>

      {nativeDefault && (
        <Card className="border-emerald-300 bg-emerald-50/50 dark:bg-emerald-950/20">
          <CardContent className="pt-6 text-sm"><strong>Windows 原生模式已启用。</strong> Hermes 直接运行在 OpenAkita 后端进程中，无需 Docker。内嵌 Runtime：{nativeAvailable ? "可用" : "不可用"}{platform ? ` · ${platform}` : ""}</CardContent>
        </Card>
      )}
      {!nativeDefault && !dockerAvailable && (
        <Card className="border-amber-300 bg-amber-50/50 dark:bg-amber-950/20"><CardContent className="pt-6 text-sm">当前运行模式需要 Docker，但 OpenAkita 未检测到 Docker Socket。可设置 OPENAKITA_HERMES_RUNTIME=native 使用内嵌 Runtime（构建需包含 Hermes Agent）。</CardContent></Card>
      )}

      {message && <div className="text-sm text-muted-foreground">{message}</div>}

      <div className="grid gap-4 xl:grid-cols-2">
        {instances.map(instance => {
          const isNative = Boolean(instance.runtime?.native);
          const running = Boolean(instance.runtime?.running) || Boolean(instance.container?.running) || instance.lifecycle_status === "running";
          const actionBusy = busy.startsWith(`${instance.id}:`);
          const manageable = isNative ? Boolean(instance.runtime?.available) : dockerAvailable;
          return (
            <Card key={instance.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                      {instance.name}
                      <Badge variant={instance.mode === "shared" ? "secondary" : "outline"}>{instance.mode === "shared" ? "共享实例" : "独立实例"}</Badge>
                      <Badge variant="outline">{isNative ? "Windows 本机" : "Docker"}</Badge>
                    </CardTitle>
                    <CardDescription className="mt-1">{isNative ? `内嵌 Hermes ${instance.runtime?.version || ""}` : instance.container_name}</CardDescription>
                  </div>
                  <Badge variant={running ? "default" : instance.lifecycle_status === "error" ? "destructive" : "secondary"}>{statusLabel(instance.lifecycle_status)}</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                  <div><div className="text-muted-foreground">绑定 Agent</div><div className="mt-1 font-medium">{instance.agent_count || 0}</div></div>
                  <div><div className="text-muted-foreground">健康状态</div><div className="mt-1 font-medium">{statusLabel(instance.health_status)}</div></div>
                  <div><div className="text-muted-foreground">当前任务</div><div className="mt-1 font-medium">{instance.current_inflight}/{instance.max_concurrency}</div></div>
                  <div><div className="text-muted-foreground">{isNative ? "PID" : "网络"}</div><div className="mt-1 truncate font-medium" title={isNative ? String(instance.runtime?.pid || "-") : instance.network}>{isNative ? (instance.runtime?.pid || "-") : instance.network}</div></div>
                </div>

                <div className="rounded-lg border bg-muted/20 p-3 text-sm">
                  <div className="text-muted-foreground">模型服务</div><div className="mt-1 break-all font-mono text-xs">OpenAkita /v1 · 按各 Agent 的模型配置调用</div>
                  <div className="mt-3 text-muted-foreground">运行方式</div><div className="mt-1 break-all font-mono text-xs">{isNative ? `embedded_backend · native://${instance.id}` : `${instance.container_name} · ${instance.volume_name}`}</div>
                </div>

                {instance.last_error && <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{instance.last_error}</div>}

                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={actionBusy || !manageable || running} onClick={() => void run(instance, "start")}><Play className="mr-1 h-4 w-4" />启动</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !manageable || !running || (!isNative && instance.mode === "shared")} onClick={() => void run(instance, "stop")}><Square className="mr-1 h-4 w-4" />停止</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !manageable} onClick={() => void run(instance, "restart")}><RotateCw className="mr-1 h-4 w-4" />重启</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !running} onClick={() => void run(instance, "test")}><Activity className="mr-1 h-4 w-4" />测试</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || (!isNative && !dockerAvailable)} onClick={() => void showLogs(instance)}><FileText className="mr-1 h-4 w-4" />日志</Button>
                  {instance.mode === "dedicated" && <Button size="sm" variant="destructive" disabled={actionBusy} onClick={() => void remove(instance)}><Trash2 className="mr-1 h-4 w-4" />删除实例</Button>}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {!loading && instances.length === 0 && <Card><CardContent className="py-12 text-center text-muted-foreground">暂无执行模式实例</CardContent></Card>}

      <Dialog open={Boolean(logs)} onOpenChange={open => !open && setLogs(null)}>
        <DialogContent className="max-w-4xl"><DialogHeader><DialogTitle>{logs?.name} 日志</DialogTitle><DialogDescription>{logs?.native ? "内嵌 Runtime 状态日志" : "最近 200 行容器日志"}</DialogDescription></DialogHeader><pre className="max-h-[60vh] overflow-auto rounded-lg bg-muted p-4 text-xs whitespace-pre-wrap">{logs?.content || "暂无日志"}</pre></DialogContent>
      </Dialog>
    </div>
  );
}
