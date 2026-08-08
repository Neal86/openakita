import { safeFetch } from "../providers";

export type ExecutionMode = "native" | "hermes";
export type HermesInstanceMode = "shared" | "dedicated";
export type SubAgentMemoryMode = "ephemeral" | "isolated" | "inherit_readonly";

export type AgentExecutionConfig = {
  profile_id: string;
  execution_mode: ExecutionMode;
  hermes_instance_mode: HermesInstanceMode;
  hermes_instance_id?: string | null;
  hermes_allow_sub_agents: boolean;
  hermes_sub_agent_memory_mode: SubAgentMemoryMode;
};

export type ExecutionInstance = {
  id: string;
  name: string;
  mode: HermesInstanceMode;
  agent_profile_id?: string | null;
  container_name: string;
  image: string;
  network: string;
  volume_name: string;
  base_url: string;
  enabled: boolean;
  lifecycle_status: string;
  health_status: string;
  max_concurrency: number;
  current_inflight: number;
  last_success_at?: string | null;
  last_error?: string | null;
  agent_count?: number;
  agents?: AgentExecutionConfig[];
  container?: Record<string, unknown>;
};

export const defaultExecution = (profileId: string): AgentExecutionConfig => ({
  profile_id: profileId,
  execution_mode: "native",
  hermes_instance_mode: "shared",
  hermes_instance_id: null,
  hermes_allow_sub_agents: false,
  hermes_sub_agent_memory_mode: "ephemeral",
});

async function json<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data as { detail?: string }).detail || response.statusText);
  return data as T;
}

export async function getAgentExecution(apiBase: string, profileId: string): Promise<AgentExecutionConfig> {
  const result = await json<{ execution: AgentExecutionConfig }>(await safeFetch(`${apiBase}/api/execution/agents/${encodeURIComponent(profileId)}`));
  return result.execution;
}

export async function saveAgentExecution(apiBase: string, profileId: string, execution: AgentExecutionConfig): Promise<AgentExecutionConfig> {
  const result = await json<{ execution: AgentExecutionConfig }>(await safeFetch(`${apiBase}/api/execution/agents/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(execution),
  }));
  return result.execution;
}

export async function listExecutionInstances(apiBase: string): Promise<{ instances: ExecutionInstance[]; docker_available: boolean }> {
  return json(await safeFetch(`${apiBase}/api/execution/instances`));
}

export async function instanceAction(apiBase: string, instanceId: string, action: "start" | "stop" | "restart" | "test"): Promise<unknown> {
  return json(await safeFetch(`${apiBase}/api/execution/instances/${encodeURIComponent(instanceId)}/${action}`, { method: "POST" }));
}

export async function instanceLogs(apiBase: string, instanceId: string): Promise<string> {
  const result = await json<{ logs: string }>(await safeFetch(`${apiBase}/api/execution/instances/${encodeURIComponent(instanceId)}/logs`));
  return result.logs;
}

export async function deleteExecutionInstance(apiBase: string, instanceId: string, deleteData = false): Promise<void> {
  await json(await safeFetch(`${apiBase}/api/execution/instances/${encodeURIComponent(instanceId)}?delete_data=${deleteData}`, { method: "DELETE" }));
}
