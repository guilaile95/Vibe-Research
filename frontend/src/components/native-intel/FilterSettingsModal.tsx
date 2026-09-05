import { useEffect, useState } from "react";
import {
  SlidersHorizontal,
  Sparkles,
  Tag,
  Plus,
  Trash2,
  Loader2,
  X,
  Check,
} from "lucide-react";
import {
  api,
  ApiError,
  type FilterProfile,
  type FilterMethod,
  type InterestTag,
  type KeywordGroup,
} from "@/lib/api";
import { toast } from "sonner";
import { loadLlm } from "@/lib/llm";

interface FilterSettingsModalProps {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}

export function FilterSettingsModal({ open, onClose, onSaved }: FilterSettingsModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [updatingTags, setUpdatingTags] = useState(false);
  const [classifying, setClassifying] = useState(false);

  const [profile, setProfile] = useState<FilterProfile | null>(null);

  const [method, setMethod] = useState<FilterMethod>("keyword");
  const [interestsText, setInterestsText] = useState("");
  const [minScore, setMinScore] = useState(0.7);
  const [globalExcludes, setGlobalExcludes] = useState<string[]>([]);
  const [filterTerms, setFilterTerms] = useState<string[]>([]);
  const [groups, setGroups] = useState<KeywordGroup[]>([]);
  const [tags, setTags] = useState<InterestTag[]>([]);

  useEffect(() => {
    if (!open) {
      setLoading(true);
      return;
    }
    let mounted = true;
    setLoading(true);
    api
      .nativeIntelFilterProfile()
      .then((res) => {
        if (!mounted) return;
        setProfile(res);
        setMethod(res.method || "keyword");
        setInterestsText(res.interests_text || "");
        setMinScore(res.min_score ?? 0.7);
        setGlobalExcludes(res.keyword_rules?.global_excludes || []);
        setFilterTerms(res.keyword_rules?.filter_terms || []);
        setGroups(
          (res.keyword_rules?.groups || []).map((g) => ({
            name: g.name || "",
            includes: g.includes || [],
            required: g.required || [],
            excludes: g.excludes || [],
            max_count: g.max_count ?? null,
          }))
        );
        setTags(res.tags || []);
      })
      .catch((err) => {
        toast.error(err instanceof ApiError ? err.message : "读取筛选配置失败");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      const isInterestsChanged =
        method === "ai" &&
        interestsText.trim() !== (profile?.interests_text || "").trim();

      if (isInterestsChanged) {
        const llm = loadLlm();
        if (!llm) {
          toast.error("尚未接入 AI，请先到「接入 AI」配置。");
          setSaving(false);
          return;
        }
        const res = await api.applyNativeIntelInterestUpdate({
          profile_id: profile?.profile_id || "default",
          interests_text: interestsText,
          ai_config: llm,
          min_score: minScore,
        });
        setProfile(res.profile);
        setTags(res.profile.tags || []);
        toast.success(
          `兴趣偏好已更新（${res.decision === "INCREMENTAL" ? "增量更新" : "全量重算"}）`
        );
      } else {
        const updated = await api.updateNativeIntelFilterProfile({
          name: profile?.name || "默认关注",
          method,
          interests_text: interestsText,
          min_score: minScore,
          keyword_rules: {
            global_excludes: globalExcludes,
            filter_terms: filterTerms,
            groups,
          },
          tags,
        });
        setProfile(updated);
        toast.success("筛选偏好已保存");
      }
      if (onSaved) onSaved();
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存筛选配置失败");
    } finally {
      setSaving(false);
    }
  };

  const handleExtractTags = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    if (!interestsText.trim()) {
      toast.error("请先填写个人兴趣描述");
      return;
    }
    setExtracting(true);
    try {
      const res = await api.extractNativeIntelFilterTags(interestsText, llm);
      setTags(res.tags || []);
      toast.success(`成功提取 ${res.tags.length} 个结构化标签`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "AI 提取标签失败");
    } finally {
      setExtracting(false);
    }
  };

  const handleUpdateTags = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    if (!interestsText.trim()) {
      toast.error("请先填写新的兴趣描述");
      return;
    }
    setUpdatingTags(true);
    try {
      const res = await api.applyNativeIntelInterestUpdate({
        profile_id: profile?.profile_id || "default",
        interests_text: interestsText,
        ai_config: llm,
        min_score: minScore,
      });
      setProfile(res.profile);
      setTags(res.profile.tags || []);
      const modeText = res.decision === "INCREMENTAL" ? "增量更新" : "全量重算";
      toast.success(
        `增量更新完成（${modeText}，变动率 ${Math.round(res.change_ratio * 100)}%，保留 ${res.keep?.length ?? 0}，新增 ${res.add?.length ?? 0}，移除 ${res.remove?.length ?? 0}）`
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "增量更新标签失败");
    } finally {
      setUpdatingTags(false);
    }
  };

  const handleSaveAndClassify = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    setClassifying(true);
    try {
      let canonicalProfile: FilterProfile;
      const isInterestsChanged =
        interestsText.trim() !== (profile?.interests_text || "").trim();

      if (isInterestsChanged) {
        const updateRes = await api.applyNativeIntelInterestUpdate({
          profile_id: profile?.profile_id || "default",
          interests_text: interestsText,
          ai_config: llm,
          min_score: minScore,
        });
        canonicalProfile = updateRes.profile;
        setProfile(canonicalProfile);
        setTags(canonicalProfile.tags || []);
      } else {
        canonicalProfile = await api.updateNativeIntelFilterProfile({
          name: profile?.name || "默认关注",
          method,
          interests_text: interestsText,
          min_score: minScore,
          keyword_rules: {
            global_excludes: globalExcludes,
            filter_terms: filterTerms,
            groups,
          },
          tags,
        });
        setProfile(canonicalProfile);
      }

      if (!canonicalProfile?.tags || canonicalProfile.tags.length === 0) {
        toast.error("请先提取或配置分类标签");
        setClassifying(false);
        return;
      }

      const res = await api.classifyNativeIntelItems({
        profile_id: canonicalProfile.profile_id || "default",
        limit: 100,
        ai_config: llm,
      });
      toast.success(`AI 批量分类完成：新分类 ${res.newly_classified ?? 0} 条，共计 ${res.classified ?? 0} 条`);
      if (onSaved) onSaved();
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存并执行分类失败");
    } finally {
      setClassifying(false);
    }
  };

  const addGroup = () => {
    setGroups([...groups, { name: "新分组", includes: [""], required: [], excludes: [], max_count: null }]);
  };

  const updateGroupName = (idx: number, name: string) => {
    const updated = [...groups];
    updated[idx].name = name;
    setGroups(updated);
  };

  const updateGroupIncludes = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].includes = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupRequired = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].required = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupExcludes = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].excludes = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupMaxCount = (idx: number, val: string) => {
    const updated = [...groups];
    const trimmed = val.trim();
    const num = trimmed === "" ? null : parseInt(trimmed, 10);
    updated[idx].max_count = num != null && !isNaN(num) ? num : null;
    setGroups(updated);
  };

  const removeGroup = (idx: number) => {
    setGroups(groups.filter((_, i) => i !== idx));
  };

  const removeTag = (idx: number) => {
    setTags(tags.filter((_, i) => i !== idx));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
      data-testid="filter-settings-modal"
    >
      <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-5 shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border pb-3 shrink-0">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            <h3 className="font-semibold text-base text-foreground">资讯兴趣与筛选设置</h3>
            <span className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary font-mono">
              TREND-PARITY Wave 2
            </span>
          </div>
          <button
            type="button"
            data-testid="close-filter-settings-modal"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
        <div className="my-4 overflow-y-auto space-y-5 flex-1 pr-1">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              读取偏好配置中…
            </div>
          ) : (
            <>
              {/* 模式选择 */}
              <div>
                <label className="block text-xs font-semibold text-foreground mb-2">筛选引擎模式</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    data-testid="filter-mode-select-keyword"
                    onClick={() => setMethod("keyword")}
                    className={`rounded-lg border p-3 text-left transition-all ${
                      method === "keyword"
                        ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary"
                        : "border-border bg-background/50 text-muted-foreground hover:border-border/80"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sm">关键词 / 正则过滤</span>
                      {method === "keyword" && <Check className="h-4 w-4 text-primary" />}
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      本地极速匹配，支持分组包含、排除词及 /regex/ 正则表达式
                    </p>
                  </button>

                  <button
                    type="button"
                    data-testid="filter-mode-select-ai"
                    onClick={() => setMethod("ai")}
                    className={`rounded-lg border p-3 text-left transition-all ${
                      method === "ai"
                        ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary"
                        : "border-border bg-background/50 text-muted-foreground hover:border-border/80"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sm flex items-center gap-1.5">
                        <Sparkles className="h-3.5 w-3.5 text-amber-500" />
                        AI 智能语义过滤
                      </span>
                      {method === "ai" && <Check className="h-4 w-4 text-primary" />}
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      自然语言兴趣描述，自动提取多标签并按相关度阈值过滤
                    </p>
                  </button>
                </div>
              </div>

              {/* 关键词模式配置 */}
              {method === "keyword" && (
                <div className="space-y-4 rounded-lg border border-border/60 bg-background/40 p-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        全局排除词（[GLOBAL_FILTER]，命中即排除）
                      </label>
                      <input
                        type="text"
                        data-testid="filter-input-global-excludes"
                        placeholder="逗号分隔，如：震惊, /赌博|博彩/, 辟谣"
                        value={globalExcludes.join(", ")}
                        onChange={(e) =>
                          setGlobalExcludes(
                            e.target.value
                              .split(/[,，]/)
                              .map((s) => s.trim())
                              .filter(Boolean)
                          )
                        }
                        className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:border-primary focus:outline-none font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        全局过滤词（!过滤词 filter_terms，命中即排除）
                      </label>
                      <input
                        type="text"
                        data-testid="filter-input-filter-terms"
                        placeholder="逗号分隔，如：广告, 推广, /辟谣/"
                        value={filterTerms.join(", ")}
                        onChange={(e) =>
                          setFilterTerms(
                            e.target.value
                              .split(/[,，]/)
                              .map((s) => s.trim())
                              .filter(Boolean)
                          )
                        }
                        className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:border-primary focus:outline-none font-mono"
                      />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">兴趣分组列表</span>
                      <button
                        type="button"
                        onClick={addGroup}
                        className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-medium"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        添加分组
                      </button>
                    </div>

                    {groups.map((grp, idx) => (
                      <div
                        key={idx}
                        className="rounded-md border border-border/50 bg-card/60 p-3 space-y-2 text-xs"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <input
                            type="text"
                            placeholder="分组名称，如：半导体与算力"
                            value={grp.name}
                            onChange={(e) => updateGroupName(idx, e.target.value)}
                            className="flex-1 font-semibold text-foreground bg-transparent border-b border-border/60 pb-0.5 focus:border-primary focus:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => removeGroup(idx)}
                            className="text-muted-foreground hover:text-destructive p-1"
                            title="删除分组"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          <div>
                            <span className="text-[11px] text-muted-foreground">普通包含词 (满足任一 OR):</span>
                            <input
                              type="text"
                              data-testid={`filter-group-includes-${idx}`}
                              placeholder="如：芯片, 半导体, /gpu|npu/"
                              value={grp.includes.join(", ")}
                              onChange={(e) => updateGroupIncludes(idx, e.target.value)}
                              className="mt-0.5 w-full rounded border border-border/60 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                            />
                          </div>

                          <div>
                            <span className="text-[11px] text-muted-foreground">必须包含词 (+必须词 AND，缺一不可):</span>
                            <input
                              type="text"
                              data-testid={`filter-group-required-${idx}`}
                              placeholder="如：GPU, 算力"
                              value={grp.required?.join(", ") || ""}
                              onChange={(e) => updateGroupRequired(idx, e.target.value)}
                              className="mt-0.5 w-full rounded border border-border/60 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          <div>
                            <span className="text-[11px] text-muted-foreground">分组专属排除词:</span>
                            <input
                              type="text"
                              data-testid={`filter-group-excludes-${idx}`}
                              placeholder="如：玩具芯片"
                              value={grp.excludes.join(", ")}
                              onChange={(e) => updateGroupExcludes(idx, e.target.value)}
                              className="mt-0.5 w-full rounded border border-border/60 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                            />
                          </div>

                          <div>
                            <span className="text-[11px] text-muted-foreground">该组最大条数上限 (@N，留空不限):</span>
                            <input
                              type="number"
                              min={1}
                              max={100}
                              data-testid={`filter-group-max-count-${idx}`}
                              placeholder="留空不限，如：5"
                              value={grp.max_count ?? ""}
                              onChange={(e) => updateGroupMaxCount(idx, e.target.value)}
                              className="mt-0.5 w-full rounded border border-border/60 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* AI 模式配置 */}
              {method === "ai" && (
                <div className="space-y-4 rounded-lg border border-border/60 bg-background/40 p-4">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-medium text-foreground">
                        个人自然语言兴趣描述
                      </label>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          data-testid="extract-tags-button"
                          onClick={() => void handleExtractTags()}
                          disabled={extracting}
                          className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20 font-medium disabled:opacity-50"
                        >
                          {extracting ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Sparkles className="h-3.5 w-3.5" />
                          )}
                          AI 提取标签
                        </button>
                        {tags.length > 0 && (
                          <button
                            type="button"
                            onClick={() => void handleUpdateTags()}
                            disabled={updatingTags}
                            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground font-medium disabled:opacity-50"
                          >
                            {updatingTags && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                            增量对比更新
                          </button>
                        )}
                      </div>
                    </div>
                    <textarea
                      rows={4}
                      value={interestsText}
                      onChange={(e) => setInterestsText(e.target.value)}
                      placeholder="例如：我主要关注机器人产业链（减速器、伺服电机）、算力芯片与液冷数据中心；重点看可能影响 A 股上市公司的产业动态，不想看娱乐八卦。"
                      className="w-full rounded-md border border-border bg-background p-2.5 text-xs text-foreground focus:border-primary focus:outline-none leading-relaxed"
                    />
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-foreground flex items-center gap-1">
                        <Tag className="h-3.5 w-3.5 text-primary" />
                        结构化分类标签 ({tags.length})
                      </span>
                    </div>

                    {tags.length === 0 ? (
                      <p className="rounded border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
                        尚未提取标签。请在上方输入兴趣描述后点击「AI 提取标签」。
                      </p>
                    ) : (
                      <div className="max-h-48 overflow-y-auto divide-y divide-border/40 rounded border border-border bg-card/50">
                        {tags.map((t, idx) => (
                          <div key={idx} className="flex items-start justify-between p-2 text-xs gap-2">
                            <div>
                              <span className="font-medium text-primary">{t.tag}</span>
                              <p className="text-[11px] text-muted-foreground mt-0.5">{t.description}</p>
                            </div>
                            <button
                              type="button"
                              onClick={() => removeTag(idx)}
                              className="text-muted-foreground hover:text-destructive p-0.5"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="font-medium text-foreground">
                        最低相关度匹配阈值 (min_score)
                      </span>
                      <span className="font-mono font-bold text-primary">
                        {Math.round(minScore * 100)}%
                      </span>
                    </div>
                    <input
                      type="range"
                      data-testid="filter-min-score-slider"
                      min="0.1"
                      max="1.0"
                      step="0.05"
                      value={minScore}
                      onChange={(e) => setMinScore(parseFloat(e.target.value))}
                      className="w-full accent-primary h-1.5 bg-muted rounded-lg cursor-pointer"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                      <span>广覆盖 (50%)</span>
                      <span>默认标准 (70%)</span>
                      <span>高精准 (90%)</span>
                    </div>
                  </div>

                  <div className="pt-1">
                    <button
                      type="button"
                      data-testid="save-and-classify-button"
                      onClick={() => void handleSaveAndClassify()}
                      disabled={classifying || tags.length === 0}
                      className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-background/80 py-2 text-xs font-medium text-foreground hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      {classifying ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Sparkles className="h-4 w-4 text-purple-400" />
                      )}
                      保存并执行 AI 分类
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border pt-3 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            data-testid="save-filter-settings-button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            保存筛选偏好
          </button>
        </div>
      </div>
    </div>
  );
}
