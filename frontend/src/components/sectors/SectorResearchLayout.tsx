import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  getSectorMeta,
  getTagBySlug,
  loadSectorResearchWorkspace,
  resolveSectorTagMeta,
  type SectorResearchWorkspace,
} from "@/data/sectorResearch";
import { SectorResearchContent } from "./SectorResearchContent";
import { SectorReportDiscoveryPanel } from "./SectorReportDiscoveryPanel";
import { SectorResearchLiveData } from "./SectorResearchLiveData";
import { SectorMarketContext } from "./SectorMarketContext";
import { cn } from "@/lib/utils";

/**
 * 统一板块研究工作台壳：
 * 返回 · 标题 · 定位 · Tag 导航（真实 URL）· 内容区 · 来源区
 *
 * 同步层（getSectorMeta）仅渲染外壳（标题 / Tag 导航 / AI 上下文 / 最新资料），
 * 不进首屏 bundle；研究正文块（含来源池）在 useEffect 内按需动态加载，进入具体板块
 * 时才拉取该板块内容。加载期间内容区显示骨架，不阻塞外壳、导航与「最新资料」。
 */
export function SectorResearchLayout() {
  const { key, tag: tagParam } = useParams();
  const meta = getSectorMeta(key);

  const [workspace, setWorkspace] = useState<SectorResearchWorkspace | null>(null);
  const [contentLoading, setContentLoading] = useState(true);

  useEffect(() => {
    if (!meta) return;
    let alive = true;
    setContentLoading(true);
    loadSectorResearchWorkspace(key)
      .then((ws) => {
        if (alive) setWorkspace(ws ?? null);
      })
      .finally(() => {
        if (alive) setContentLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [key, meta]);

  if (!meta) {
    return (
      <div className="py-20 text-center text-muted-foreground">
        未找到该研究工作台。
        <Link to="/sectors" className="text-primary">
          返回板块中心
        </Link>
      </div>
    );
  }

  // /sectors/pcb → 默认 Tag；非法 Tag → 回退默认 Tag（可分享 URL 安全）。
  // 仅依赖同步元数据即可判断，无需等待正文块加载。
  const resolved = resolveSectorTagMeta(meta.key, tagParam);
  if (!resolved || resolved.redirected) {
    const safe = resolved?.tagSlug ?? meta.defaultTag;
    return <Navigate to={`/sectors/${meta.key}/${safe}`} replace />;
  }

  const activeMetaTag = meta.tags.find((t) => t.slug === resolved.tagSlug);

  const aiContext = [
    `板块：${meta.fullName}`,
    `定位：${meta.tagline}`,
    `研究栏目：${meta.tags.map((t) => t.label).join("、")}`,
    `当前栏目：${activeMetaTag?.label ?? resolved.tagSlug}`,
    `内容状态：${activeMetaTag?.status === "placeholder" ? "框架占位，尚无正式研究正文" : activeMetaTag?.status ?? "draft"}`,
    "说明：仅根据当前页面已展示的栏目名称与占位说明回答，不要编造未展示的数字、研报结论或产业判断。",
  ].join("\n");

  // 正文块 + 来源池：等待按需加载完成；外壳（标题/导航/最新资料）始终同步渲染。
  const activeTag = workspace ? getTagBySlug(workspace, resolved.tagSlug) : undefined;
  const sources = workspace?.sources ?? [];

  return (
    <div className="min-w-0">
      <Link
        to="/sectors"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 板块中心
      </Link>

      <PageHeader
        title={meta.fullName}
        subtitle={meta.tagline}
        actions={
          <AskAiButton
            context={aiContext}
            label="问 AI"
            suggestions={[
              "这个板块研究框架包含哪些栏目",
              "当前栏目还缺什么内容",
              "后续填充时应注意哪些证据纪律",
            ]}
          />
        }
      />

      {/* Tag 导航：真实路由，可前进后退与刷新；窄屏容器内横向滚动 */}
      <nav
        aria-label="研究栏目"
        className="-mx-1 mb-5 flex gap-2 overflow-x-auto px-1 pb-1"
      >
        {meta.tags.map((t) => {
          const active = t.slug === resolved.tagSlug;
          return (
            <Link
              key={t.slug}
              to={`/sectors/${meta.key}/${t.slug}`}
              aria-current={active ? "page" : undefined}
              data-active={active ? "true" : "false"}
              className={cn(
                "shrink-0 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "border-primary/50 bg-primary/15 text-primary shadow-glow"
                  : "border-border/60 bg-muted/20 text-muted-foreground hover:border-primary/30 hover:text-foreground",
              )}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>

      <SectorMarketContext sectorKey={meta.key} />

      {contentLoading || !activeTag ? (
        <div className="flex min-h-[12rem] items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载研究内容…
        </div>
      ) : (
        <SectorResearchContent tag={activeTag} sources={sources} />
      )}

      <div className="mt-8 space-y-4">
        <h2 className="text-sm font-semibold">最新资料</h2>
        <SectorReportDiscoveryPanel sectorKey={meta.key} />
        <SectorResearchLiveData sectorKey={meta.key} />
      </div>
    </div>
  );
}
