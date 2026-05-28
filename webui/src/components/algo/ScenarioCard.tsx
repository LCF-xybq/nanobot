import { cn } from "@/lib/utils";
import type { Scenario } from "@/lib/algo-api";

interface ScenarioCardProps {
  scenario: Scenario;
  selected: boolean;
  onClick: () => void;
}

export function ScenarioCard({ scenario, selected, onClick }: ScenarioCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected
          ? "border-primary/50 bg-primary/5 text-foreground"
          : "border-border/50 bg-card text-card-foreground hover:bg-accent/50",
        !scenario.has_algorithms && "opacity-50",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{scenario.name}</span>
        {scenario.has_algorithms && (
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            {scenario.algorithms.length} 算法
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
        {scenario.description}
      </p>
    </button>
  );
}
