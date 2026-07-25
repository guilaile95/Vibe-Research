/**
 * 板块研究工作台 — 最小类型化内容模型。
 * 内容与页面组件分离；后续按 Tag 增量填充，不引入 CMS/后端库。
 */

export type ResearchTagStatus = "placeholder" | "draft" | "ready";

export type SourceFactLevel = "已确认事实" | "公司口径" | "机构预测" | "产业传闻" | "分析推断";

export type SourceRef = {
  id: string;
  title: string;
  org?: string;
  /** 实际访问日期（合法 ISO 日期） */
  accessedAt?: string;
  /** 来源实际支持的事实范围（非空字符串或字符串数组；不得写入投资结论） */
  supports?: string | string[];
  /** 公开可访问 URL（http/https） */
  url?: string;
  /** 关联的本地研报 id → 页面内链接到 /my-reports?report=<id> */
  myReportId?: string;
  /** 来源类型：report / whitepaper / company_filing / news / standard / other */
  sourceType?: string;
  /** 事实等级 */
  factLevel?: SourceFactLevel;
  publishedAt?: string;
  note?: string;
};

export type ContentBlock =
  | { type: "paragraph"; text: string; sourceIds?: string[] }
  | { type: "bullets"; items: string[]; sourceIds?: string[] }
  | {
      type: "callout";
      text: string;
      tone?: "info" | "warning" | "emphasis";
      sourceIds?: string[];
    }
  | {
      type: "table";
      caption?: string;
      headers: string[];
      rows: string[][];
      sourceIds?: string[];
    }
  | {
      type: "compareTable";
      caption?: string;
      headers: string[];
      rows: string[][];
      sourceIds?: string[];
    }
  | { type: "risk"; items: string[]; sourceIds?: string[] }
  | { type: "placeholder"; text: string };

export type ResearchTag = {
  /** URL 段，稳定英文 slug */
  slug: string;
  /** Tag 导航上显示的短名 */
  label: string;
  /** 内容区标题 */
  title: string;
  status: ResearchTagStatus;
  /** ISO 日期或可读日期；占位时可省略 */
  updatedAt?: string;
  blocks: ContentBlock[];
};

export type SectorResearchWorkspace = {
  key: string;
  label: string;
  fullName: string;
  tagline: string;
  /** 访问 /sectors/:key 时默认进入的 Tag slug */
  defaultTag: string;
  tags: ResearchTag[];
  /** 板块级来源池（可被 block.sourceIds 引用） */
  sources: SourceRef[];
};

export function assertWorkspaceInvariants(ws: SectorResearchWorkspace): void {
  if (!ws.tags.length) {
    throw new Error(`sector research workspace "${ws.key}" has no tags`);
  }
  const slugs = ws.tags.map((t) => t.slug);
  if (new Set(slugs).size !== slugs.length) {
    throw new Error(`sector research workspace "${ws.key}" has duplicate tag slugs`);
  }
  if (!slugs.includes(ws.defaultTag)) {
    throw new Error(
      `sector research workspace "${ws.key}" defaultTag "${ws.defaultTag}" not in tags`,
    );
  }
}

export function getTagBySlug(
  ws: SectorResearchWorkspace,
  slug: string | undefined,
): ResearchTag | undefined {
  if (!slug) return undefined;
  return ws.tags.find((t) => t.slug === slug);
}

export function resolveTagSlug(
  ws: SectorResearchWorkspace,
  slug: string | undefined,
): string {
  if (slug && ws.tags.some((t) => t.slug === slug)) return slug;
  return ws.defaultTag;
}
