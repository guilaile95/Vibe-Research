import { Eye, EyeOff } from "lucide-react";
import { usePrivacyMode } from "@/hooks/usePrivacyMode";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

export function PrivacyModeButton({ className }: Props) {
  const { enabled, toggle } = usePrivacyMode();
  const label = enabled ? "关闭隐私模式" : "开启隐私模式";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      aria-pressed={enabled}
      title={label}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors",
        "hover:bg-muted hover:text-foreground",
        enabled && "bg-muted text-foreground",
        className,
      )}
    >
      {enabled ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
    </button>
  );
}
