import { type ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0 max-w-full">
        <h1 className="text-2xl font-extrabold tracking-tight text-glow">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && (
        <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
