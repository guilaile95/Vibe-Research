import { type ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 max-w-full">
        <h1 className="font-display text-[22px] font-semibold leading-8 tracking-[-0.015em] text-foreground">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
