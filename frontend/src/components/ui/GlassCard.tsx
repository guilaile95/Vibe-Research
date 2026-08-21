import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  onClick?: () => void;
}

export function GlassCard({ children, className, glow, onClick, ...rest }: Props) {
  return (
    <div
      {...rest}
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
