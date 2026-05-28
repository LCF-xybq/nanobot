import { cn } from "@/lib/utils";
import type { TaskInfo } from "@/lib/agri-api";

interface TaskHistoryProps {
  tasks: TaskInfo[];
}

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-muted text-muted-foreground",
  RUNNING: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  SUCCESS: "bg-green-500/10 text-green-600 dark:text-green-400",
  FAILED: "bg-red-500/10 text-red-600 dark:text-red-400",
  TIMEOUT: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  STOPPED: "bg-muted text-muted-foreground",
  RETRYING: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400",
};

function formatElapsed(seconds: number | null): string {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function formatTime(ts: number | null): string {
  if (ts == null) return "-";
  return new Date(ts * 1000).toLocaleTimeString();
}

export function TaskHistory({ tasks }: TaskHistoryProps) {
  if (tasks.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        暂无任务记录
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="pb-2 pr-3 font-medium">应用</th>
            <th className="pb-2 pr-3 font-medium">状态</th>
            <th className="pb-2 pr-3 font-medium">进度</th>
            <th className="pb-2 pr-3 font-medium">开始</th>
            <th className="pb-2 font-medium">耗时</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_id} className="border-b border-border/40">
              <td className="py-2 pr-3 font-medium">{task.service_name}</td>
              <td className="py-2 pr-3">
                <span
                  className={cn(
                    "inline-block rounded-full px-2 py-0.5 text-[10px] font-medium",
                    STATUS_COLORS[task.status] ?? "bg-muted text-muted-foreground",
                  )}
                >
                  {task.status}
                </span>
              </td>
              <td className="py-2 pr-3">
                {task.progress ? `${task.progress.percent.toFixed(0)}%` : "-"}
              </td>
              <td className="py-2 pr-3 text-muted-foreground">
                {formatTime(task.start_time)}
              </td>
              <td className="py-2 text-muted-foreground">
                {formatElapsed(task.elapsed_time)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
