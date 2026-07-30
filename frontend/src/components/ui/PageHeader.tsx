import { type ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4 animate-fade-up">
      <div className="min-w-0 max-w-full">
        <h1 className="font-display text-[1.75rem] font-bold leading-tight tracking-tight text-foreground">
          {title}
        </h1>
        {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && (
        <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
