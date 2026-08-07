import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  onClick?: () => void;
}

export function GlassCard({ children, className, glow, onClick }: Props) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "card-surface p-4",
        glow && "border-primary/25",
        onClick &&
          "cursor-pointer transition-colors duration-150 hover:border-border hover:bg-muted/20",
        className,
      )}
    >
      {children}
    </div>
  );
}
