import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  type AgentExecutionConfig,
  defaultExecution,
  getAgentExecution,
  saveAgentExecution,
} from "../api/executionInstances";

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

  useEffect(() => {
    setValue(defaultExecution(profileId));
    if (!profileId) return;
    setLoading(true);
    getAgentExecution(apiBaseUrl, profileId)
      .then(setValue)
      .catch(() => setValue(defaultExecution(profileId)))
      .finally(() => setLoading(false));
  }, [apiBaseUrl, profileId]);

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

  return (
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
        <RadioGroup
          value={value.execution_mode}
          onValueChange={(execution_mode: "native" | "hermes") => patch({ execution_mode })}
          disabled={disabled || loading}
          className="grid gap-3 md:grid-cols-2"
        >
          <Label className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
            <RadioGroupItem value="native" className="mt-1" />
            <span>
              <span className="block font-medium">原生 Agent</span>
              <span className="mt-1 block text-sm text-muted-foreground">使用 OpenAkita 原有执行方式。</span>
            </span>
          </Label>
          <Label className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
            <RadioGroupItem value="hermes" className="mt-1" />
            <span>
              <span className="block font-medium">Hermes Agent</span>
              <span className="mt-1 block text-sm text-muted-foreground">使用 Hermes 的记忆、工具与子 Agent 能力，模型仍由当前 Agent 单独配置。</span>
            </span>
          </Label>
        </RadioGroup>

        {value.execution_mode === "hermes" && (
          <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
            <div className="space-y-2">
              <Label>Hermes 模式</Label>
              <RadioGroup
                value={value.hermes_instance_mode}
                onValueChange={(hermes_instance_mode: "shared" | "dedicated") => patch({ hermes_instance_mode })}
                className="grid gap-3 md:grid-cols-2"
              >
                <Label className="flex cursor-pointer items-start gap-3 rounded-lg border bg-background p-4">
                  <RadioGroupItem value="shared" className="mt-1" />
                  <span>
                    <span className="flex items-center gap-2 font-medium">共享实例 <Badge variant="outline">推荐</Badge></span>
                    <span className="mt-1 block text-sm text-muted-foreground">系统自动分配共享 Hermes；记忆、会话和工作目录按 Agent 隔离。</span>
                  </span>
                </Label>
                <Label className="flex cursor-pointer items-start gap-3 rounded-lg border bg-background p-4">
                  <RadioGroupItem value="dedicated" className="mt-1" />
                  <span>
                    <span className="block font-medium">独立实例</span>
                    <span className="mt-1 block text-sm text-muted-foreground">保存后自动创建该 Agent 专属的 Hermes 容器和数据卷。</span>
                  </span>
                </Label>
              </RadioGroup>
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
  );
}
