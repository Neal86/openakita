import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Play, Square, RotateCw, Activity, FileText, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
}[value] || value);

export function ExecutionInstancesView({ apiBaseUrl = "http://127.0.0.1:18900" }: { apiBaseUrl?: string }) {
  const [instances, setInstances] = useState<ExecutionInstance[]>([]);
  const [dockerAvailable, setDockerAvailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [logs, setLogs] = useState<{ name: string; content: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listExecutionInstances(apiBaseUrl);
      setInstances(result.instances || []);
      setDockerAvailable(result.docker_available);
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
      setMessage(action === "test" ? "连接测试完成" : "操作已完成");
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
      setLogs({ name: instance.name, content: await instanceLogs(apiBaseUrl, instance.id) });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取日志失败");
    } finally {
      setBusy("");
    }
  };

  const remove = async (instance: ExecutionInstance) => {
    if (instance.mode === "shared") return;
    if (!window.confirm(`确定删除 ${instance.name} 的容器吗？数据卷会保留。`)) return;
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

  return (
    <div className="pageContainer space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="pageTitle">执行模式实例</h1>
          <p className="pageDescription">管理共享 Hermes 服务和 Agent 专属的独立实例。Agent 仍在原有 Agent 页面创建和编辑。</p>
        </div>
        <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />刷新
        </Button>
      </div>

      {!dockerAvailable && (
        <Card className="border-amber-300 bg-amber-50/50 dark:bg-amber-950/20">
          <CardContent className="pt-6 text-sm">当前 OpenAkita 未挂载 Docker Socket。共享实例可通过 Compose 使用；独立实例会保存为“等待启动”，挂载后即可自动创建。</CardContent>
        </Card>
      )}

      {message && <div className="text-sm text-muted-foreground">{message}</div>}

      <div className="grid gap-4 xl:grid-cols-2">
        {instances.map(instance => {
          const running = Boolean(instance.container?.running) || instance.lifecycle_status === "running";
          const actionBusy = busy.startsWith(`${instance.id}:`);
          return (
            <Card key={instance.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-base">
                      {instance.name}
                      <Badge variant={instance.mode === "shared" ? "secondary" : "outline"}>{instance.mode === "shared" ? "共享实例" : "独立实例"}</Badge>
                    </CardTitle>
                    <CardDescription className="mt-1">{instance.container_name}</CardDescription>
                  </div>
                  <Badge variant={running ? "default" : instance.lifecycle_status === "error" ? "destructive" : "secondary"}>{statusLabel(instance.lifecycle_status)}</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                  <div><div className="text-muted-foreground">绑定 Agent</div><div className="mt-1 font-medium">{instance.agent_count || 0}</div></div>
                  <div><div className="text-muted-foreground">健康状态</div><div className="mt-1 font-medium">{statusLabel(instance.health_status)}</div></div>
                  <div><div className="text-muted-foreground">当前任务</div><div className="mt-1 font-medium">{instance.current_inflight}/{instance.max_concurrency}</div></div>
                  <div><div className="text-muted-foreground">网络</div><div className="mt-1 truncate font-medium" title={instance.network}>{instance.network}</div></div>
                </div>

                <div className="rounded-lg border bg-muted/20 p-3 text-sm">
                  <div className="text-muted-foreground">模型服务</div>
                  <div className="mt-1 break-all font-mono text-xs">OpenAkita /v1 · 按各 Agent 的模型配置调用</div>
                  <div className="mt-3 text-muted-foreground">数据卷</div>
                  <div className="mt-1 break-all font-mono text-xs">{instance.volume_name}</div>
                </div>

                {instance.last_error && <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{instance.last_error}</div>}

                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={actionBusy || !dockerAvailable} onClick={() => void run(instance, "start")}><Play className="mr-1 h-4 w-4" />启动</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !dockerAvailable || instance.mode === "shared"} onClick={() => void run(instance, "stop")}><Square className="mr-1 h-4 w-4" />停止</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !dockerAvailable} onClick={() => void run(instance, "restart")}><RotateCw className="mr-1 h-4 w-4" />重启</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy} onClick={() => void run(instance, "test")}><Activity className="mr-1 h-4 w-4" />测试</Button>
                  <Button size="sm" variant="outline" disabled={actionBusy || !dockerAvailable} onClick={() => void showLogs(instance)}><FileText className="mr-1 h-4 w-4" />日志</Button>
                  {instance.mode === "dedicated" && <Button size="sm" variant="destructive" disabled={actionBusy} onClick={() => void remove(instance)}><Trash2 className="mr-1 h-4 w-4" />删除实例</Button>}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {!loading && instances.length === 0 && <Card><CardContent className="py-12 text-center text-muted-foreground">暂无执行模式实例</CardContent></Card>}

      <Dialog open={Boolean(logs)} onOpenChange={open => !open && setLogs(null)}>
        <DialogContent className="max-w-4xl">
          <DialogHeader><DialogTitle>{logs?.name} 日志</DialogTitle><DialogDescription>最近 200 行容器日志</DialogDescription></DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-muted p-4 text-xs whitespace-pre-wrap">{logs?.content || "暂无日志"}</pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}
