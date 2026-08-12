import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  glow?: boolean;
}

export function GlassCard({ children, className, glow, onClick, onKeyDown, role, tabIndex, ...props }: Props) {
  const interactive = Boolean(onClick);

  return (
    <div
      {...props}
      onClick={onClick}
      role={interactive ? role ?? "button" : role}
      tabIndex={interactive ? tabIndex ?? 0 : tabIndex}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented || !interactive || (event.key !== "Enter" && event.key !== " ")) return;
        event.preventDefault();
        event.currentTarget.click();
      }}
      className={cn(
        "card-surface p-4 sm:p-5",
        glow && "bg-card/90",
        interactive && "cursor-pointer transition-colors duration-150 hover:bg-muted/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
        className,
      )}
    >
      {children}
    </div>
  );
}
