import { DecisionPriorityRail } from "@/components/decision/DecisionPriorityRail";
import { DecisionCockpit } from "@/pages/DecisionCockpit";

export function DecisionCockpitWorkspace() {
  return (
    <div className="flex flex-col xl:grid xl:grid-cols-[minmax(0,1fr)_15rem] xl:gap-7">
      <div className="min-w-0">
        <DecisionCockpit />
      </div>
      <DecisionPriorityRail />
    </div>
  );
}
