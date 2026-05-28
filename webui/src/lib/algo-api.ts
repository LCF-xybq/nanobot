/**
 * API client for the agricultural algorithm service.
 * All requests use GET because the websockets HTTP parser only handles GET.
 * Parameters are passed via query string.
 */

export interface AlgorithmInfo {
  name: string;
  display_name: string;
  description: string;
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  algorithms: AlgorithmInfo[];
  has_algorithms: boolean;
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

class AlgoApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "AlgoApiError";
  }
}

async function algoGet<T>(path: string, token: string): Promise<T> {
  const res = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new AlgoApiError(
      res.status,
      (body as Record<string, string>).error ?? `HTTP ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

export async function fetchScenarios(token: string): Promise<Scenario[]> {
  const data = await algoGet<{ scenarios: Scenario[] }>(
    "/api/algo/scenarios",
    token,
  );
  return data.scenarios;
}

export async function fetchServices(
  token: string,
): Promise<Record<string, { name: string; description: string }>> {
  return algoGet("/api/algo/services", token);
}

export async function fetchTasks(token: string): Promise<TaskInfo[]> {
  const data = await algoGet<{ tasks: TaskInfo[] }>("/api/algo/tasks", token);
  return data.tasks ?? [];
}

export async function fetchTasksByService(
  token: string,
  serviceName: string,
): Promise<TaskInfo[]> {
  const data = await algoGet<{ tasks: TaskInfo[] }>(
    `/api/algo/tasks/${encodeURIComponent(serviceName)}`,
    token,
  );
  return data.tasks ?? [];
}

export async function fetchServiceStatus(
  token: string,
  serviceName: string,
): Promise<TaskInfo> {
  return algoGet(`/api/algo/status/${encodeURIComponent(serviceName)}`, token);
}

export async function fetchTaskStatus(
  token: string,
  taskId: string,
): Promise<TaskInfo> {
  return algoGet(`/api/algo/task/${encodeURIComponent(taskId)}`, token);
}

export async function startService(
  token: string,
  serviceName: string,
  filename: string,
): Promise<{ task_id: string; status: string; service_name: string }> {
  return algoGet(
    `/api/algo/start/${encodeURIComponent(serviceName)}?filename=${encodeURIComponent(filename)}`,
    token,
  );
}

export async function stopService(
  token: string,
  serviceName: string,
): Promise<{ status: string; service_name: string; task_id: string }> {
  return algoGet(`/api/algo/stop/${encodeURIComponent(serviceName)}`, token);
}

export async function fetchDataFiles(
  token: string,
  algoName: string,
): Promise<DataFile[]> {
  const data = await algoGet<{ data: DataFile[]; count: number }>(
    `/api/algo/data?algo_name=${encodeURIComponent(algoName)}`,
    token,
  );
  return data.data ?? [];
}
