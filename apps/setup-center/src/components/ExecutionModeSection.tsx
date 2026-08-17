import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { safeFetch } from "../providers";
import {
  type AgentExecutionConfig,
  defaultExecution,
  getAgentExecution,
  saveAgentExecution,
} from "../api/executionInstances";

type WindowsResource = {
  id: string;
  kind: string;
  app_name?: string;
  title?: string;
  account_name?: string;
  browser_profile?: string;
  automation?: string;
  limited?: boolean;
};

type WindowsNode = {
  id: string;
  name?: string;
  status?: string;
  transport?: string;
  resources?: WindowsResource[];
};

type BrowserBinding = {
  node_id: string;
  resource: WindowsResource;
};

function ChoiceCard({
  checked,
  title,
  description,
  badge,
  disabled,
  onClick,
}: {
  checked: boolean;
  title: string;
  description: string;
  badge?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`flex w-full items-start gap-3 rounded-lg border p-4 text-left transition-colors ${checked ? "border-primary bg-primary/5" : "bg-background hover:bg-muted/40"}`}
    >
      <span className={`mt-1 h-4 w-4 shrink-0 rounded-full border ${checked ? "border-primary bg-primary shadow-[inset_0_0_0_3px_var(--background)]" : "border-muted-foreground/50"}`} />
      <span>
        <span className="flex items-center gap-2 font-medium">{title}{badge && <Badge variant="outline">{badge}</Badge>}</span>
        <span className="mt-1 block text-sm text-muted-foreground">{description}</span>
      </span>
    </button>
  );
}

async function agentProfileExists(apiBaseUrl: string, profileId: string): Promise<boolean> {
  if (!profileId) return false;
  try {
    await safeFetch(`${apiBaseUrl}/api/agents/profiles/${encodeURIComponent(profileId)}`);
    return true;
  } catch {
    return false;
  }
}

export function ExecutionModeSection({
  apiBaseUrl,
  profileId,
  disabled,
  onSaved,
}: {
  apiBaseUrl: string;
  profileId: string;
  disabled?: boolean;
  onSaved?: (value: AgentExecutionConfig) => void;
}) {
  const [value, setValue] = useState<AgentExecutionConfig>(() => defaultExecution(profileId));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const [nodes, setNodes] = useState<WindowsNode[]>([]);
  const [bindingLoading, setBindingLoading] = useState(false);
  const [bindingMessage, setBindingMessage] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedBrowser, setSelectedBrowser] = useState("");
  const [selectedResourceId, setSelectedResourceId] = useState("");
  const stagedBindingRef = useRef(false);

  useEffect(() => {
    setValue(defaultExecution(profileId));
    if (!profileId) return;
    setLoading(true);
    getAgentExecution(apiBaseUrl, profileId)
      .then(setValue)
      .catch(() => setValue(defaultExecution(profileId)))
      .finally(() => setLoading(false));
  }, [apiBaseUrl, profileId]);

  useEffect(() => {
    let active = true;
    setBindingLoading(true);
    Promise.all([
      safeFetch(`${apiBaseUrl}/api/windows-connector/nodes?refresh_local=true`).then(res => res.json()),
      profileId
        ? safeFetch(`${apiBaseUrl}/api/windows-connector/browser-bindings/${encodeURIComponent(profileId)}`).then(res => res.json()).catch(() => ({ binding: null }))
        : Promise.resolve({ binding: null }),
    ]).then(([nodeData, bindingData]) => {
      if (!active) return;
      const nextNodes = Array.isArray(nodeData?.nodes) ? nodeData.nodes as WindowsNode[] : [];
      setNodes(nextNodes);
      const binding = bindingData?.binding as BrowserBinding | null;
      if (binding?.resource?.id) {
        setSelectedNodeId(binding.node_id);
        setSelectedBrowser(binding.resource.app_name || "Browser");
        setSelectedResourceId(binding.resource.id);
      } else {
        const firstNode = nextNodes.find(node => (node.resources || []).some(resource => resource.kind === "browser_profile" || resource.kind === "browser_tab"));
        setSelectedNodeId(firstNode?.id || "");
        setSelectedBrowser("");
        setSelectedResourceId("");
      }
    }).catch(error => {
      if (active) setBindingMessage(error instanceof Error ? error.message : "无法读取 Windows Connector");
    }).finally(() => {
      if (active) setBindingLoading(false);
    });
    return () => { active = false; };
  }, [apiBaseUrl, profileId]);

  useEffect(() => {
    return () => {
      const stagedProfileId = profileId;
      if (!stagedBindingRef.current || !stagedProfileId) return;
      void (async () => {
        if (await agentProfileExists(apiBaseUrl, stagedProfileId)) return;
        try {
          await safeFetch(`${apiBaseUrl}/api/windows-connector/browser-bindings/${encodeURIComponent(stagedProfileId)}`, { method: "DELETE" });
        } catch {
          // Best effort cleanup. Orphan grants are inert until a matching Agent exists.
        }
      })();
    };
  }, [apiBaseUrl, profileId]);

  const selectedNode = useMemo(
    () => nodes.find(node => node.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  );

  const browserResources = useMemo(() => {
    const resources = selectedNode?.resources || [];
    const profiles = resources.filter(resource => resource.kind === "browser_profile");
    return profiles.length > 0 ? profiles : resources.filter(resource => resource.kind === "browser_tab");
  }, [selectedNode]);

  const browserNames = useMemo(
    () => Array.from(new Set(browserResources.map(resource => resource.app_name || "Browser"))),
    [browserResources],
  );

  const profileResources = useMemo(
    () => browserResources.filter(resource => (resource.app_name || "Browser") === selectedBrowser),
    [browserResources, selectedBrowser],
  );

  useEffect(() => {
    if (selectedBrowser && browserNames.includes(selectedBrowser)) return;
    const nextBrowser = browserNames[0] || "";
    setSelectedBrowser(nextBrowser);
    if (!nextBrowser) setSelectedResourceId("");
  }, [browserNames, selectedBrowser]);

  useEffect(() => {
    if (selectedResourceId && profileResources.some(resource => resource.id === selectedResourceId)) return;
    setSelectedResourceId(profileResources[0]?.id || "");
  }, [profileResources, selectedResourceId]);

  const patch = (next: Partial<AgentExecutionConfig>) => setValue(current => ({ ...current, ...next }));

  const save = async () => {
    if (!profileId) return;
    setSaving(true);
    setMessage("");
    try {
      const result = await saveAgentExecution(apiBaseUrl, profileId, value);
      setValue(result);
      setMessage("执行模式已保存");
      onSaved?.(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const saveBrowserBinding = async () => {
    if (!profileId || !selectedNodeId || !selectedResourceId) return;
    setBindingLoading(true);
    setBindingMessage("");
    try {
      const existed = await agentProfileExists(apiBaseUrl, profileId);
      await safeFetch(`${apiBaseUrl}/api/windows-connector/browser-bindings/${encodeURIComponent(profileId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: selectedNodeId, resource_id: selectedResourceId }),
      });
      stagedBindingRef.current = !existed;
      setBindingMessage(existed ? "浏览器绑定已保存" : "浏览器绑定已暂存；保存 Agent 后自动生效");
    } catch (error) {
      setBindingMessage(error instanceof Error ? error.message : "浏览器绑定保存失败");
    } finally {
      setBindingLoading(false);
    }
  };

  const clearBrowserBinding = async () => {
    if (!profileId) return;
    setBindingLoading(true);
    try {
      await safeFetch(`${apiBaseUrl}/api/windows-connector/browser-bindings/${encodeURIComponent(profileId)}`, { method: "DELETE" });
      stagedBindingRef.current = false;
      setSelectedResourceId("");
      setBindingMessage("已取消浏览器绑定；Agent 将使用默认本地浏览器");
    } catch (error) {
      setBindingMessage(error instanceof Error ? error.message : "取消绑定失败");
    } finally {
      setBindingLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">执行模式</CardTitle>
              <CardDescription>选择该 Agent 使用 OpenAkita 原生能力，或交给 Hermes 执行。</CardDescription>
            </div>
            {value.execution_mode === "hermes" && <Badge variant="secondary">Hermes Agent</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2">
            <ChoiceCard
              checked={value.execution_mode === "native"}
              title="原生 Agent"
              description="使用 OpenAkita 原有执行方式。"
              disabled={disabled || loading}
              onClick={() => patch({ execution_mode: "native" })}
            />
            <ChoiceCard
              checked={value.execution_mode === "hermes"}
              title="Hermes Agent"
              description="使用 Hermes 的记忆、工具与子 Agent 能力，模型仍由当前 Agent 单独配置。"
              disabled={disabled || loading}
              onClick={() => patch({ execution_mode: "hermes" })}
            />
          </div>

          {value.execution_mode === "hermes" && (
            <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
              <div className="space-y-2">
                <Label>Hermes 模式</Label>
                <div className="grid gap-3 md:grid-cols-2">
                  <ChoiceCard
                    checked={value.hermes_instance_mode === "shared"}
                    title="共享实例"
                    badge="推荐"
                    description="系统自动分配共享 Hermes；记忆、会话和工作目录按 Agent 隔离。"
                    onClick={() => patch({ hermes_instance_mode: "shared" })}
                  />
                  <ChoiceCard
                    checked={value.hermes_instance_mode === "dedicated"}
                    title="独立实例"
                    description="保存后自动创建该 Agent 专属的 Hermes 容器和数据卷。"
                    onClick={() => patch({ hermes_instance_mode: "dedicated" })}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between gap-4 rounded-lg border bg-background p-4">
                <div>
                  <div className="font-medium">允许子 Agent</div>
                  <div className="text-sm text-muted-foreground">允许 Hermes 在任务中创建隔离的子 Agent。</div>
                </div>
                <Switch checked={value.hermes_allow_sub_agents} onCheckedChange={hermes_allow_sub_agents => patch({ hermes_allow_sub_agents })} />
              </div>

              {value.hermes_allow_sub_agents && (
                <div className="space-y-2">
                  <Label>子 Agent 记忆</Label>
                  <Select value={value.hermes_sub_agent_memory_mode} onValueChange={(hermes_sub_agent_memory_mode: AgentExecutionConfig["hermes_sub_agent_memory_mode"]) => patch({ hermes_sub_agent_memory_mode })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ephemeral">临时：任务结束后删除</SelectItem>
                      <SelectItem value="isolated">独立：保留独立记忆</SelectItem>
                      <SelectItem value="inherit_readonly">只读继承父 Agent 上下文</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">{message}</span>
            <button className="btn btnPrimary" type="button" disabled={disabled || loading || saving || !profileId} onClick={save}>
              {saving ? "保存中..." : "保存执行模式"}
            </button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">浏览器绑定</CardTitle>
              <CardDescription>
                为此 Agent 指定 Windows Connector、浏览器和 Profile。Chrome、Edge、iXBrowser 共用同一 Browser Adapter。
              </CardDescription>
            </div>
            {selectedResourceId && <Badge variant="secondary">Windows Connector</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label>Connector</Label>
              <Select
                value={selectedNodeId}
                onValueChange={value => {
                  setSelectedNodeId(value);
                  setSelectedBrowser("");
                  setSelectedResourceId("");
                }}
                disabled={disabled || bindingLoading || nodes.length === 0}
              >
                <SelectTrigger><SelectValue placeholder="选择 Windows Connector" /></SelectTrigger>
                <SelectContent>
                  {nodes.map(node => (
                    <SelectItem key={node.id} value={node.id}>
                      {node.name || node.id}{node.transport === "remote" ? " · 远程" : " · 本机"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Browser</Label>
              <Select
                value={selectedBrowser}
                onValueChange={value => {
                  setSelectedBrowser(value);
                  setSelectedResourceId("");
                }}
                disabled={disabled || bindingLoading || browserNames.length === 0}
              >
                <SelectTrigger><SelectValue placeholder="选择 Chrome / Edge / iXBrowser" /></SelectTrigger>
                <SelectContent>
                  {browserNames.map(name => <SelectItem key={name} value={name}>{name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Profile</Label>
              <Select
                value={selectedResourceId}
                onValueChange={setSelectedResourceId}
                disabled={disabled || bindingLoading || profileResources.length === 0}
              >
                <SelectTrigger><SelectValue placeholder="选择浏览器 Profile" /></SelectTrigger>
                <SelectContent>
                  {profileResources.map(resource => (
                    <SelectItem key={resource.id} value={resource.id}>
                      {resource.account_name || resource.title || resource.browser_profile || "Default"}
                      {resource.limited ? " · UIA" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {browserResources.length === 0 && (
            <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
              未发现可绑定的浏览器 Profile。请先在目标电脑启动浏览器并启用 remote debugging，然后重新进入此编辑页。
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">{bindingMessage}</span>
            <div className="flex gap-2">
              <button className="btn" type="button" disabled={disabled || bindingLoading || !profileId} onClick={clearBrowserBinding}>
                使用默认浏览器
              </button>
              <button className="btn btnPrimary" type="button" disabled={disabled || bindingLoading || !profileId || !selectedNodeId || !selectedResourceId} onClick={saveBrowserBinding}>
                {bindingLoading ? "保存中..." : "保存浏览器绑定"}
              </button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
