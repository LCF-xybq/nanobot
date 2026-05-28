import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AlgorithmInfo, DataFile, TaskInfo } from "@/lib/algo-api";
import {
  fetchDataFiles,
  fetchTaskStatus,
  startService,
  stopService,
} from "@/lib/algo-api";

interface AlgorithmRunnerProps {
  algorithms: AlgorithmInfo[];
  token: string;
}

const STAGE_LABELS: Record<string, string> = {
  download: "下载",
  distortion_correction: "畸变校正",
  slicing: "切片",
  inference: "推理",
  stitching: "拼接",
  statistics: "统计",
  nms: "NMS 去重",
  upload: "上传",
  done: "完成",
};

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function AlgorithmRunner({ algorithms, token }: AlgorithmRunnerProps) {
  const [selectedAlgo, setSelectedAlgo] = useState<AlgorithmInfo | null>(null);
  const [files, setFiles] = useState<DataFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [starting, setStarting] = useState(false);
  const [activeTask, setActiveTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load data files when algorithm selected
  useEffect(() => {
    if (!selectedAlgo) {
      setFiles([]);
      setSelectedFile("");
      return;
    }
    let cancelled = false;
    setLoadingFiles(true);
    setError(null);
    fetchDataFiles(token, selectedAlgo.name)
      .then((data) => {
        if (!cancelled) setFiles(data);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingFiles(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAlgo, token]);

  // Poll active task status
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!activeTask || !["PENDING", "RUNNING", "RETRYING"].includes(activeTask.status)) {
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await fetchTaskStatus(token, activeTask.task_id);
        setActiveTask(updated);
        if (!["PENDING", "RUNNING", "RETRYING"].includes(updated.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // Polling error — keep current state
      }
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [activeTask, token]);

  const handleStart = useCallback(async () => {
    if (!selectedAlgo || !selectedFile) return;
    setStarting(true);
    setError(null);
    try {
      const result = await startService(token, selectedAlgo.name, selectedFile);
      setActiveTask({
        task_id: result.task_id,
        service_name: result.service_name,
        status: result.status,
        progress: null,
        start_time: Date.now() / 1000,
        end_time: null,
        elapsed_time: null,
        error_message: null,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setStarting(false);
    }
  }, [selectedAlgo, selectedFile, token]);

  const handleStop = useCallback(async () => {
    if (!selectedAlgo) return;
    try {
      await stopService(token, selectedAlgo.name);
    } catch {
      // Ignore stop errors
    }
  }, [selectedAlgo, token]);

  const isRunning =
    activeTask && ["PENDING", "RUNNING", "RETRYING"].includes(activeTask.status);

  return (
    <div className="space-y-4">
      {/* Application tabs */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          选择应用
        </label>
        <div className="flex gap-2">
          {algorithms.map((algo) => (
            <button
              key={algo.name}
              type="button"
              onClick={() => {
                setSelectedAlgo(algo);
                setActiveTask(null);
                setError(null);
              }}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                selectedAlgo?.name === algo.name
                  ? "border-primary/50 bg-primary/10 text-primary font-medium"
                  : "border-border/50 hover:bg-accent/50",
              )}
            >
              {algo.display_name}
            </button>
          ))}
        </div>
        {selectedAlgo && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            {selectedAlgo.description}
          </p>
        )}
      </div>

      {/* Selected algorithm steps */}
      {selectedAlgo && selectedAlgo.steps && selectedAlgo.steps.length > 0 && (
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            已选算法
          </label>
          <div className="flex flex-wrap gap-1.5">
            {selectedAlgo.steps.map((step) => (
              <span
                key={step.name}
                className="rounded-md border border-primary/20 bg-primary/5 px-2 py-0.5 text-xs text-primary"
              >
                {step.display_name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* File selector */}
      {selectedAlgo && (
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            选择数据文件
          </label>
          {loadingFiles ? (
            <div className="text-sm text-muted-foreground">加载中...</div>
          ) : files.length === 0 ? (
            <div className="text-sm text-muted-foreground">暂无可用数据文件</div>
          ) : (
            <select
              value={selectedFile}
              onChange={(e) => setSelectedFile(e.target.value)}
              className="w-full rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm"
            >
              <option value="">— 请选择文件 —</option>
              {files.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} ({(f.size / 1024 / 1024).toFixed(1)} MB)
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Action buttons */}
      {selectedAlgo && (
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={!selectedFile || starting || !!isRunning}
            onClick={handleStart}
          >
            {starting ? "启动中..." : "启动算法"}
          </Button>
          {isRunning && (
            <Button size="sm" variant="destructive" onClick={handleStop}>
              停止
            </Button>
          )}
        </div>
      )}

      {/* Progress */}
      {activeTask && (
        <div className="space-y-2 rounded-lg border border-border/50 p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              {isRunning ? "运行中" : activeTask.status === "SUCCESS" ? "已完成" : activeTask.status}
            </span>
            <span className="text-muted-foreground">
              {activeTask.progress
                ? `${activeTask.progress.percent.toFixed(0)}%`
                : "0%"}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                activeTask.status === "SUCCESS"
                  ? "bg-green-500"
                  : activeTask.status === "FAILED"
                    ? "bg-red-500"
                    : "bg-primary",
              )}
              style={{
                width: `${activeTask.progress?.percent ?? 0}%`,
              }}
            />
          </div>
          {activeTask.progress && activeTask.progress.stage !== "done" && (
            <p className="text-xs text-muted-foreground">
              阶段: {stageLabel(activeTask.progress.stage)}
            </p>
          )}
          {activeTask.error_message && (
            <p className="text-xs text-destructive">{activeTask.error_message}</p>
          )}
        </div>
      )}
    </div>
  );
}
