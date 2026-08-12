import { lazy, Suspense } from "react";

const MarkdownContent = lazy(() => import("@/components/ui/MarkdownContent"));

interface LazyMarkdownContentProps {
  content: string;
  className?: string;
}

export function LazyMarkdownContent({ content, className }: LazyMarkdownContentProps) {
  if (!content) return null;
  return (
    <Suspense fallback={<div role="status" aria-label="正在渲染内容" className="skeleton h-24" />}>
      <MarkdownContent content={content} className={className} />
    </Suspense>
  );
}
