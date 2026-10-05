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
 * 同步元数据仅提供路由外壳；展示文案、正文和 AI 上下文以当前板块的
 * 按需加载内容为准。加载期间保留 slug 导航与「最新资料」。
 */
export function SectorResearchLayout() {
  const { key, tag: tagParam } = useParams();
  const meta = getSectorMeta(key);

  const [content, setContent] = useState<
    | { key: string; status: "loading" | "error" }
    | { key: string; status: "ready"; workspace: SectorResearchWorkspace }
    | null
  >(null);

  useEffect(() => {
    if (!meta) return;
    let alive = true;
    const requestedKey = meta.key;
    setContent({ key: requestedKey, status: "loading" });
    void loadSectorResearchWorkspace(requestedKey)
      .then((ws) => {
        if (alive) setContent(ws?.key === requestedKey
          ? { key: requestedKey, status: "ready", workspace: ws }
          : { key: requestedKey, status: "error" });
      })
      .catch(() => {
        if (alive) setContent({ key: requestedKey, status: "error" });
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

  // Reject previous-board data during render, before the new effect starts.
  const current = content?.key === meta.key ? content : null;
  const workspace = current?.status === "ready" && current.workspace.key === meta.key
    ? current.workspace : undefined;
  const display = workspace ?? meta;
  const tags = workspace?.tags ?? meta.tags.map((t) => ({ slug: t.slug, label: t.slug }));
  const activeTag = workspace ? getTagBySlug(workspace, resolved.tagSlug) : undefined;
  const sources = workspace?.sources ?? [];

  const aiContext = activeTag ? [
    `板块：${display.fullName}`,
    `定位：${display.tagline}`,
    `研究栏目：${tags.map((t) => t.label).join("、")}`,
    `当前栏目：${activeTag.label}`,
    `内容状态：${activeTag.status === "placeholder" ? "框架占位，尚无正式研究正文" : activeTag.status}`,
    "说明：仅根据当前页面已展示的栏目名称与占位说明回答，不要编造未展示的数字、研报结论或产业判断。",
  ].join("\n") : "";

  return (
    <div className="min-w-0">
      <Link
        to="/sectors"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 板块中心
      </Link>

      <PageHeader
        title={display.fullName}
        subtitle={display.tagline}
        actions={
          activeTag && <AskAiButton
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
        {tags.map((t) => {
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

      {!current || current.status === "loading" ? (
        <div className="flex min-h-[12rem] items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载研究内容…
        </div>
      ) : !activeTag ? (
        <div role="alert" className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
          <p>研究内容加载失败，请刷新页面重试。</p>
          <button type="button" onClick={() => window.location.reload()} className="mt-2 text-primary">刷新页面</button>
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
