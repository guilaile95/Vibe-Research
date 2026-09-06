/**
 * 冻结后研究更新（R3）：在已有 frozen Thesis 页面上完成
 * 「选择/新建证据 → 核对内容与本次立场 → 选择既有状态并说明原因 →
 *   预览待确认内容 → 显式确认 → 服务端读回」的闭环。
 *
 * 边界：证据创建与确认 delta 是两个动作；确认前不产生任何写入；
 * 确认后的内容一律来自服务端读回（deltas API），不把本地表单渲染成成功结果。
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Loader2 } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError, api, type CurrentThesisDelta, type EvidenceRecord, type ThesisDeltaState } from "@/lib/api";

const DELTA_STATE_OPTIONS: { value: ThesisDeltaState; label: string }[] = [
  { value: "STRENGTHENED", label: "增强（支持当前观点）" },
  { value: "STABLE", label: "稳定（确认现状不变）" },
  { value: "WEAKENED", label: "削弱（弱化当前观点）" },
  { value: "UNKNOWN", label: "未知（方向无法判断）" },
  { value: "DISPROVEN", label: "已证伪（终态 · 推翻核心假设）" },
  { value: "INVALIDATED", label: "已失效（终态）" },
];

const STANCE_OPTIONS: { value: "support" | "oppose" | "neutral"; label: string }[] = [
  { value: "support", label: "支持（该证据支持当前观点）" },
  { value: "oppose", label: "反对（该证据反对当前观点）" },
  { value: "neutral", label: "中立（与观点方向无关）" },
];

const STANCE_LABELS: Record<string, string> = {
  support: "支持",
  oppose: "反对",
  neutral: "中立",
};

const inputCls = "w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs";

export function ThesisDeltaConfirm({
  thesisId,
  subjectType,
  subjectId,
}: {
  thesisId: string;
  subjectType: string;
  subjectId: string;
}) {
  const [evidenceItems, setEvidenceItems] = useState<EvidenceRecord[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(true);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState("");
  const [stance, setStance] = useState<"" | "support" | "oppose" | "neutral">("");
  const [deltaState, setDeltaState] = useState<"" | ThesisDeltaState>("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [staleEvidence, setStaleEvidence] = useState(false);
  const [readback, setReadback] = useState<CurrentThesisDelta[] | null>(null);
  const epoch = useRef(0);

  useEffect(() => {
    const generation = ++epoch.current;
    let active = true;
    setEvidenceLoading(true);
    setEvidenceError(null);
    api.evidenceList({ subject_type: subjectType, subject_id: subjectId, limit: 200 })
      .then((result) => {
        if (!active || generation !== epoch.current) return;
        setEvidenceItems(result.items.filter((item) => item.deleted === 0));
      })
      .catch((cause) => {
        if (!active || generation !== epoch.current) return;
        setEvidenceError(cause instanceof ApiError ? cause.message : "证据列表读取失败");
      })
      .finally(() => {
        if (active && generation === epoch.current) setEvidenceLoading(false);
      });
    return () => { active = false; };
  }, [subjectType, subjectId]);

  useEffect(() => {
    let active = true;
    api.thesisListDeltas(thesisId)
      .then((result) => { if (active) setReadback(result.items); })
      .catch(() => { if (active) setReadback(null); });
    return () => { active = false; };
  }, [thesisId]);

  const selected = evidenceItems.find((item) => item.id === selectedEvidenceId) ?? null;
  const canSubmit = Boolean(selected && stance && deltaState && reason.trim() && confirmed && !busy);

  const refreshEvidence = async () => {
    const generation = ++epoch.current;
    setEvidenceLoading(true);
    try {
      const result = await api.evidenceList({ subject_type: subjectType, subject_id: subjectId, limit: 200 });
      if (generation !== epoch.current) return;
      setEvidenceItems(result.items.filter((item) => item.deleted === 0));
      setStaleEvidence(false);
    } catch {
      if (generation === epoch.current) setStaleEvidence(true);
    } finally {
      if (generation === epoch.current) setEvidenceLoading(false);
    }
  };

  const submit = async () => {
    if (!selected || !stance || !deltaState || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.thesisCreateDelta(thesisId, {
        delta_state: deltaState,
        reason: reason.trim(),
        new_evidence: [{
          evidence_id: selected.id,
          stance,
          expected_updated_at: selected.updated_at,
        }],
      });
      const list = await api.thesisListDeltas(thesisId);
      setReadback(list.items);
      setStaleEvidence(false);
      setConfirmed(false);
      setSelectedEvidenceId("");
      setStance("");
      setDeltaState("");
      setReason("");
      void created;
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(cause.message);
        // 证据在预览后被修改：保留草稿，要求重新核对证据内容。
        if (cause.status === 409) setStaleEvidence(true);
      } else {
        setError("确认失败：结果未知，请刷新后核对已确认变更，避免盲目重发。");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassCard className="mb-4" data-testid="thesis-delta-confirm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">记录新的研究变化（冻结后确认更新）</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            确认后会追加一条新的不可变确认变更，不改写最初冻结原文。创建证据与确认变更是两个动作：
            证据创建成功不代表研究变化已确认；不点「确认」不会产生任何变更记录。
          </p>
        </div>
        <Link
          to={`/evidence/new?${new URLSearchParams({
            subject_type: subjectType,
            subject_id: subjectId,
            return_to: `/thesis/${thesisId}`,
          }).toString()}`}
          className="rounded-md border border-primary/40 px-2.5 py-1 text-xs text-primary hover:bg-primary/5"
        >
          新建证据记录 →
        </Link>
      </div>

      {evidenceLoading && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在读取本标的证据记录…
        </p>
      )}
      {evidenceError && (
        <p className="mt-3 text-xs text-destructive" role="alert">{evidenceError}</p>
      )}
      {!evidenceLoading && !evidenceError && evidenceItems.length === 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          本标的暂无可选证据记录。先用右上角「新建证据记录」创建，再回来确认研究变化。
        </p>
      )}

      {!evidenceLoading && !evidenceError && evidenceItems.length > 0 && (
        <div className="mt-3 space-y-3 text-xs">
          <label className="block">
            <span className="text-muted-foreground">选择证据（创建/编辑证据后请重新核对内容）</span>
            <select
              aria-label="选择证据"
              value={selectedEvidenceId}
              onChange={(event) => { setSelectedEvidenceId(event.target.value); setStaleEvidence(false); }}
              className={`mt-1 ${inputCls}`}
            >
              <option value="">请选择</option>
              {evidenceItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.claim}（{item.source_title} · {item.source_date ?? "来源日期未知"} · {item.classification}/{item.confidence}）
                </option>
              ))}
            </select>
          </label>

          {selected && (
            <div className="rounded-md border border-border/50 bg-muted/15 p-2.5" data-testid="delta-evidence-summary">
              <p className="font-medium">证据内容（来自全局证据记录，服务端为准）</p>
              <p className="mt-1">{selected.claim}</p>
              <p className="mt-1 text-muted-foreground">
                类型 {selected.evidence_type} · 分类 {selected.classification} · 置信度 {selected.confidence}
                {" · 来源："}
                {selected.source_url
                  ? <a href={selected.source_url} className="underline" target="_blank" rel="noreferrer">{selected.source_title || selected.source_url}</a>
                  : selected.source_title}
                {selected.source_date ? ` · 来源日期 ${selected.source_date}` : " · 来源日期未知"}
                {` · 记录时间 ${selected.accessed_at}`}
              </p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-muted-foreground">该证据对当前观点的立场（显式选择，不从文字推断）</span>
              <select aria-label="本次变更立场" value={stance} onChange={(event) => setStance(event.target.value as typeof stance)} className={`mt-1 ${inputCls}`}>
                <option value="">请选择</option>
                {STANCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-muted-foreground">研究变化状态（沿用既有状态集合）</span>
              <select aria-label="研究变化状态" value={deltaState} onChange={(event) => setDeltaState(event.target.value as typeof deltaState)} className={`mt-1 ${inputCls}`}>
                <option value="">请选择</option>
                {DELTA_STATE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
          </div>

          <label className="block">
            <span className="text-muted-foreground">变更原因（为什么这条证据值得确认）</span>
            <textarea
              aria-label="变更原因"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={`mt-1 ${inputCls}`}
            />
          </label>

          {selected && stance && deltaState && reason.trim() && (
            <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5" data-testid="delta-preview">
              <p className="font-medium">预览：以下内容将在你确认后追加为新的确认变更</p>
              <p className="mt-1">
                状态 {deltaState} · 立场 {STANCE_LABELS[stance]} · 依据证据「{selected.claim}」
              </p>
              <p className="mt-1">原因：{reason.trim()}</p>
              <p className="mt-1 text-muted-foreground">
                确认后会以服务端当前证据内容生成不可变快照；若证据在确认前被修改，将要求你重新核对。
                最初冻结原文与已存在的正式决定都不会被改写。
              </p>
            </div>
          )}

          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              className="mt-0.5"
              aria-label="我已核对证据内容与本次立场，确认追加这条研究变化"
            />
            <span className="text-muted-foreground">
              我已核对证据内容、来源与本次立场，确认追加这条研究变化（追加后不可撤销）。
            </span>
          </label>

          {staleEvidence && (
            <p className="text-xs text-warning" role="status">
              证据内容可能已在预览后发生变化，草稿已保留：请重新选择证据核对内容与来源后再确认。
              <button type="button" onClick={() => void refreshEvidence()} className="ml-1 underline">
                重新读取证据
              </button>
            </p>
          )}
          {error && (
            <p className="flex items-start gap-1.5 text-xs text-destructive" role="alert">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </p>
          )}

          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSubmit}
            data-testid="confirm-thesis-delta"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            确认追加研究变化
          </button>
        </div>
      )}

      {readback !== null && (
        <div className="mt-4 border-t border-border/50 pt-3" data-testid="delta-readback">
          <p className="text-xs font-medium">已确认变更（服务端读回，共 {readback.length} 条）</p>
          {readback.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">还没有已确认变更；上方确认成功后会出现在这里。</p>
          ) : (
            <ul className="mt-2 space-y-1.5 text-xs">
              {readback.map((item) => (
                <li key={item.delta_id} className="rounded bg-muted/30 px-2 py-1.5">
                  <p>
                    #{item.delta_sequence} · {item.delta_state} · 确认时间 {item.confirmed_at ?? "未知"}
                  </p>
                  <p className="mt-0.5">{item.reason}</p>
                  {item.evidence_links.map((link) => (
                    <p key={link.evidence_id} className="mt-0.5 text-muted-foreground">
                      [{STANCE_LABELS[link.stance] || link.stance}] {link.claim} · {link.classification}/{link.confidence} · {link.source_title || link.source_url || "来源未知"}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </GlassCard>
  );
}
