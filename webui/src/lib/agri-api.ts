/**
 * API client for the agricultural application service.
 * All requests use GET because the websockets HTTP parser only handles GET.
 * Parameters are passed via query string.
 */

export interface ApplicationStep {
  name: string;
  display_name: string;
}

export interface ApplicationInfo {
  name: string;
  display_name: string;
  description: string;
  steps: ApplicationStep[];
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  applications: ApplicationInfo[];
  has_applications: boolean;
}

export interface DataFile {
  name: string;
  size: number;
  last_modified: string;
}

export interface TaskProgress {
  percent: number;
  stage: string;
  message: string;
  timestamp: number;
}

export interface TaskInfo {
  task_id: string;
  service_name: string;
  status: string;
  progress: TaskProgress | null;
  start_time: number | null;
  end_time: number | null;
  elapsed_time: number | null;
  error_message: string | null;
}

class AgriApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "AgriApiError";
  }
}

async function agriGet<T>(path: string, token: string): Promise<T> {
  const res = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new AgriApiError(
      res.status,
      (body as Record<string, string>).error ?? `HTTP ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

export async function fetchScenarios(token: string): Promise<Scenario[]> {
  const data = await agriGet<{ scenarios: Scenario[] }>(
    "/api/agri/scenarios",
    token,
  );
  return data.scenarios;
}

export async function fetchServices(
  token: string,
): Promise<Record<string, { name: string; description: string }>> {
  return agriGet("/api/agri/services", token);
}

export async function fetchTasks(token: string): Promise<TaskInfo[]> {
  const data = await agriGet<{ tasks: TaskInfo[] }>("/api/agri/tasks", token);
  return data.tasks ?? [];
}

export async function fetchTasksByService(
  token: string,
  serviceName: string,
): Promise<TaskInfo[]> {
  const data = await agriGet<{ tasks: TaskInfo[] }>(
    `/api/agri/tasks/${encodeURIComponent(serviceName)}`,
    token,
  );
  return data.tasks ?? [];
}

export async function fetchServiceStatus(
  token: string,
  serviceName: string,
): Promise<TaskInfo> {
  return agriGet(`/api/agri/status/${encodeURIComponent(serviceName)}`, token);
}

export async function fetchTaskStatus(
  token: string,
  taskId: string,
): Promise<TaskInfo> {
  return agriGet(`/api/agri/task/${encodeURIComponent(taskId)}`, token);
}

export async function startService(
  token: string,
  serviceName: string,
  filename: string,
): Promise<{ task_id: string; status: string; service_name: string }> {
  return agriGet(
    `/api/agri/start/${encodeURIComponent(serviceName)}?filename=${encodeURIComponent(filename)}`,
    token,
  );
}

export async function stopService(
  token: string,
  serviceName: string,
): Promise<{ status: string; service_name: string; task_id: string }> {
  return agriGet(`/api/agri/stop/${encodeURIComponent(serviceName)}`, token);
}

export async function fetchDataFiles(
  token: string,
  agriName: string,
): Promise<DataFile[]> {
  const data = await agriGet<{ data: DataFile[]; count: number }>(
    `/api/agri/data?agri_name=${encodeURIComponent(agriName)}`,
    token,
  );
  return data.data ?? [];
}
