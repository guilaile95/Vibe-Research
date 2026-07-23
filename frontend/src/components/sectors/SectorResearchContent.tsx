import type { ContentBlock, ResearchTag, SourceRef } from "@/data/sectorResearch";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";

function sourceFootnote(ids: string[] | undefined, sources: SourceRef[]): string | null {
  if (!ids?.length) return null;
  const labels = ids.map((id) => {
    const s = sources.find((x) => x.id === id);
    return s ? s.id : id;
  });
  return labels.map((l) => `[${l}]`).join("");
}

function BlockView({ block, sources }: { block: ContentBlock; sources: SourceRef[] }) {
  switch (block.type) {
    case "placeholder":
      return (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <div className="rounded-full border border-dashed border-primary/40 bg-primary/10 px-3 py-1 text-[11px] font-medium text-primary">
            框架占位
          </div>
          <p className="max-w-lg text-sm leading-relaxed text-muted-foreground">{block.text}</p>
        </div>
      );
    case "paragraph": {
      const foot = sourceFootnote(block.sourceIds, sources);
      return (
        <p className="text-sm leading-relaxed text-foreground/90">
          {block.text}
          {foot && <sup className="ml-0.5 text-[10px] text-muted-foreground">{foot}</sup>}
        </p>
      );
    }
    case "bullets": {
      const foot = sourceFootnote(block.sourceIds, sources);
      return (
        <div>
          <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-foreground/90">
            {block.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          {foot && <p className="mt-1 text-[11px] text-muted-foreground">来源 {foot}</p>}
        </div>
      );
    }
    case "callout": {
      const tone = block.tone ?? "info";
      return (
        <div
          className={cn(
            "rounded-xl border px-4 py-3 text-sm leading-relaxed",
            tone === "emphasis" && "border-primary/40 bg-primary/10 text-foreground",
            tone === "warning" && "border-amber-500/40 bg-amber-500/10 text-foreground",
            tone === "info" && "border-border/60 bg-muted/30 text-foreground/90",
          )}
        >
          {block.text}
        </div>
      );
    }
    case "table":
    case "compareTable":
      return (
        <div className="overflow-x-auto">
          {block.caption && (
            <p className="mb-2 text-xs font-medium text-muted-foreground">{block.caption}</p>
          )}
          <table className="w-full min-w-[20rem] border-collapse text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-border/60">
                {block.headers.map((h) => (
                  <th key={h} className="px-2 py-2 font-semibold text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className="border-b border-border/30">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-2 text-foreground/90">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "risk":
      return (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <p className="mb-2 text-xs font-semibold text-amber-600 dark:text-amber-400">风险提示</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90">
            {block.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      );
    default: {
      const _exhaustive: never = block;
      return _exhaustive;
    }
  }
}

type Props = {
  tag: ResearchTag;
  sources: SourceRef[];
};

export function SectorResearchContent({ tag, sources }: Props) {
  const statusLabel =
    tag.status === "placeholder" ? "待填充" : tag.status === "draft" ? "草稿" : "已发布";

  return (
    <GlassCard className="min-w-0">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
        <h2 className="text-base font-bold tracking-tight">{tag.title}</h2>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="rounded-full border border-border/60 px-2 py-0.5">{statusLabel}</span>
          {tag.updatedAt ? (
            <span>更新 {tag.updatedAt}</span>
          ) : (
            <span>内容状态：框架已建立</span>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {tag.blocks.map((block, i) => (
          <BlockView key={i} block={block} sources={sources} />
        ))}
      </div>

      <div className="mt-6 border-t border-border/50 pt-4">
        <h3 className="mb-2 text-xs font-semibold text-muted-foreground">资料来源</h3>
        {sources.length === 0 ? (
          <p className="text-xs leading-relaxed text-muted-foreground/80">
            本轮为框架占位，页面不展示正式研究结论。公开资料底稿见仓库{" "}
            <code className="rounded bg-muted/50 px-1 py-0.5 text-[10px]">
              docs/research/pcb/2026-ai-server-pcb-source-dossier.md
            </code>
            ，后续各 Tag 填充时会在此挂载可核对来源。
          </p>
        ) : (
          <ul className="space-y-1.5 text-xs text-muted-foreground">
            {sources.map((s) => (
              <li key={s.id} className="min-w-0 break-words">
                <span className="font-medium text-foreground/80">[{s.id}]</span> {s.title}
                {s.org ? ` · ${s.org}` : ""}
                {s.publishedAt ? ` · ${s.publishedAt}` : ""}
                {s.url ? (
                  <>
                    {" · "}
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      链接
                    </a>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </GlassCard>
  );
}
