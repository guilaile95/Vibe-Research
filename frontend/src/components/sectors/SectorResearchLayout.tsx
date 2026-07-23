import { Link, Navigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  getSectorResearchWorkspace,
  getTagBySlug,
  resolveTagSlug,
} from "@/data/sectorResearch";
import { SectorResearchContent } from "./SectorResearchContent";
import { cn } from "@/lib/utils";

/**
 * 统一板块研究工作台壳：
 * 返回 · 标题 · 定位 · Tag 导航（真实 URL）· 内容区 · 来源区
 */
export function SectorResearchLayout() {
  const { key, tag: tagParam } = useParams();
  const workspace = getSectorResearchWorkspace(key);

  if (!workspace) {
    return (
      <div className="py-20 text-center text-muted-foreground">
        未找到该研究工作台。
        <Link to="/sectors" className="text-primary">
          返回板块中心
        </Link>
      </div>
    );
  }

  // /sectors/pcb → 默认 Tag；非法 Tag → 回退默认 Tag（可分享 URL 安全）
  if (!tagParam || !getTagBySlug(workspace, tagParam)) {
    const safe = resolveTagSlug(workspace, tagParam);
    return <Navigate to={`/sectors/${workspace.key}/${safe}`} replace />;
  }

  const activeTag = getTagBySlug(workspace, tagParam)!;

  const aiContext = [
    `板块：${workspace.fullName}`,
    `定位：${workspace.tagline}`,
    `研究栏目：${workspace.tags.map((t) => t.label).join("、")}`,
    `当前栏目：${activeTag.label}`,
    `内容状态：${activeTag.status === "placeholder" ? "框架占位，尚无正式研究正文" : activeTag.status}`,
    "说明：仅根据当前页面已展示的栏目名称与占位说明回答，不要编造未展示的数字、研报结论或产业判断。",
  ].join("\n");

  return (
    <div className="min-w-0">
      <Link
        to="/sectors"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 板块中心
      </Link>

      <PageHeader
        title={workspace.fullName}
        subtitle={workspace.tagline}
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
        {workspace.tags.map((t) => {
          const active = t.slug === activeTag.slug;
          return (
            <Link
              key={t.slug}
              to={`/sectors/${workspace.key}/${t.slug}`}
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

      <SectorResearchContent tag={activeTag} sources={workspace.sources} />
    </div>
  );
}
