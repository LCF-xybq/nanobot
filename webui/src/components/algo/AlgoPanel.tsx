import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScenarioCard } from "./ScenarioCard";
import { AlgorithmRunner } from "./AlgorithmRunner";
import { TaskHistory } from "./TaskHistory";
import {
  fetchScenarios,
  fetchTasks,
  type Scenario,
  type TaskInfo,
} from "@/lib/algo-api";

interface AlgoPanelProps {
  token: string;
  onBack: () => void;
}

export function AlgoPanel({ token, onBack }: AlgoPanelProps) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selected = scenarios.find((s) => s.id === selectedId) ?? null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchScenarios(token), fetchTasks(token)])
      .then(([sc, ts]) => {
        if (!cancelled) {
          setScenarios(sc);
          setTasks(ts);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const refreshTasks = async () => {
    try {
      const ts = await fetchTasks(token);
      setTasks(ts);
    } catch {
      // Keep stale data
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-muted-foreground">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={onBack}>
          返回
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <Button variant="ghost" size="icon" onClick={onBack} className="h-7 w-7">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-semibold">农业算法</h1>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Left: Scenario list */}
        <div className="w-56 shrink-0 overflow-y-auto border-r p-3">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            场景
          </p>
          <div className="space-y-2">
            {scenarios.map((s) => (
              <ScenarioCard
                key={s.id}
                scenario={s}
                selected={selectedId === s.id}
                onClick={() => setSelectedId(s.id)}
              />
            ))}
          </div>
        </div>

        {/* Right: Detail */}
        <div className="min-w-0 flex-1 overflow-y-auto p-4">
          {!selected ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              请从左侧选择一个场景
            </div>
          ) : (
            <div className="mx-auto max-w-2xl space-y-6">
              {/* Scenario header */}
              <div>
                <h2 className="text-lg font-semibold">{selected.name}</h2>
                <p className="text-sm text-muted-foreground">
                  {selected.description}
                </p>
              </div>

              {selected.has_algorithms ? (
                <>
                  <Separator />
                  <AlgorithmRunner
                    algorithms={selected.algorithms}
                    token={token}
                  />
                </>
              ) : (
                <div className="rounded-lg border border-dashed border-border/60 p-6 text-center text-sm text-muted-foreground">
                  该场景暂无已接入的算法
                </div>
              )}

              <Separator />

              {/* Task history */}
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-medium">任务历史</h3>
                  <Button variant="ghost" size="sm" onClick={refreshTasks}>
                    刷新
                  </Button>
                </div>
                <TaskHistory tasks={tasks} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
