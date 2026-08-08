import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  glow?: boolean;
}

export function GlassCard({ children, className, glow, onClick, ...props }: Props) {
  return (
    <div
      {...props}
      onClick={onClick}
      className={cn(
        "card-surface p-4 sm:p-5",
        glow && "bg-card/90",
        onClick && "cursor-pointer transition-colors duration-150 hover:bg-muted/90",
        className,
      )}
    >
      {children}
    </div>
  );
}
