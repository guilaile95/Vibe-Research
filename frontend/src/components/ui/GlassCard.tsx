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
        "card-surface p-5",
        glow && "glass-glow",
        onClick && "cursor-pointer transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-hover",
        className,
      )}
    >
      {children}
    </div>
  );
}
