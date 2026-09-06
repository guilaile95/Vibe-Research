import type { ResearchBriefModel } from "@/lib/researchBrief";

const codeCls = "rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]";

const STANCE_LABELS: Record<string, string> = {
  support: "支持",
  oppose: "反对",
  neutral: "中立",
};

function stateBadgeCls(kind: ResearchBriefModel["effectiveState"]["kind"]): string {
  if (kind === "terminal") return "rounded bg-destructive/15 px-1.5 py-0.5 text-[11px] font-medium text-destructive";
  if (kind === "caution") return "rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-700";
  if (kind === "positive") return "rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700";
  return "rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground";
}

function EvidenceList({
  items,
  empty,
  showStance = false,
}: {
  items: ResearchBriefModel["evidence"]["supporting"];
  empty: string;
  showStance?: boolean;
}) {
  if (items.length === 0) {
    return empty ? <p className="mt-1 text-muted-foreground">{empty}</p> : null;
  }
  return (
    <ul className="mt-1 space-y-1.5">
      {items.map((item) => (
        <li key={item.evidenceId} className="rounded bg-muted/40 px-2 py-1.5" data-testid={`research-brief-evidence-${item.stance}`}>
          <p className="font-medium">
            {showStance && <span className="mr-1 text-muted-foreground">[{STANCE_LABELS[item.stance] || item.stance}]</span>}
            {item.claim}
          </p>
          <p className="mt-0.5 text-muted-foreground">
            {item.classification} · 置信度 {item.confidence}
            {" · 来源："}
            {item.sourceUrl ? (
              <a href={item.sourceUrl} className="underline" target="_blank" rel="noreferrer">{item.sourceTitle || item.sourceUrl}</a>
            ) : (
              item.sourceTitle || "未知"
            )}
            {item.sourceDate ? ` · ${item.sourceDate}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function ResearchBrief({
  model,
  bindingThesisId,
  boundThesisId,
}: {
  model: ResearchBriefModel;
  bindingThesisId: string;
  boundThesisId: string;
}) {
  const latestUpdate = model.confirmedUpdates[model.confirmedUpdates.length - 1] ?? null;
  return (
    <section
      className="rounded-lg border border-border/60 bg-background/35 p-4 space-y-4"
      data-testid="research-brief"
      data-decision-context={model.contextState}
      data-context-binding={bindingThesisId}
      data-context-bound-thesis={boundThesisId}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">研究摘要</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            只读整理当前 Campaign 的已确认研究。打开或展开本摘要不会改写 Thesis、Decision 或交易。
          </p>
        </div>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-700">只读 · backend authority</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">Campaign</span>
        <span className={codeCls}>{model.campaignId || "缺少 campaign_id"}</span>
        {model.contextState === "loading" && <span className="text-muted-foreground">正在读取上下文…</span>}
      </div>

      {model.effectiveState.terminal && (
        <div
          role="alert"
          data-testid="research-brief-terminal-state"
          className="rounded border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive"
        >
          当前确认状态：{model.effectiveState.label} — 最初冻结观点已被后续确认变更推翻，不能作为当前研究结论使用。
        </div>
      )}

      <section data-testid="research-brief-subject">
        <h3 className="text-xs font-semibold">研究哪个标的、采用什么策略、当前处于什么确认状态？</h3>
        <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-5">
          <div><p className="text-muted-foreground">证券</p><p className="mt-1 font-medium" data-context-security>{model.securityCode}</p></div>
          <div><p className="text-muted-foreground">策略</p><p className="mt-1 font-medium" data-context-strategy>{model.strategyLabel}{model.strategyCode ? `（${model.strategyCode}）` : ""}</p></div>
          <div><p className="text-muted-foreground">Current Thesis</p><p className="mt-1 font-medium" data-context-thesis-status>{model.thesisVersionText}</p></div>
          <div><p className="text-muted-foreground">当前确认状态</p><p className="mt-1 font-medium" data-context-effective-state>{model.effectiveState.label}</p></div>
          <div><p className="text-muted-foreground">预期周期</p><p className="mt-1 font-medium" data-context-horizon>{model.horizonText}</p></div>
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{model.effectiveState.note}</p>
        {model.horizonSource === "CURRENT_THESIS" && (
          <p className="mt-1 text-xs leading-5 text-success" data-horizon-source="CURRENT_THESIS">
            来源：Current Thesis。预期周期已从已确认冻结快照读取，不是本页表单里的临时填写。
          </p>
        )}
        {model.horizonSource === "MANUAL_FALLBACK" && (
          <p className="mt-1 text-xs leading-5 text-warning" role="status" data-horizon-source="MANUAL_FALLBACK">
            已确认 Thesis 当前不能提供合法周期。摘要不会猜测；下方表单仍需手工填写。
          </p>
        )}
      </section>

      <section data-testid="research-brief-view">
        <h3 className="text-xs font-semibold">最初冻结的观点是什么？（历史原貌）</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.confirmed.note}</p>
        {model.confirmed.title && <p className="mt-2 text-sm font-medium">{model.confirmed.title}</p>}
        {model.confirmed.summary && <p className="mt-1 text-xs">{model.confirmed.summary}</p>}
        {model.confirmed.claims.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
            {model.confirmed.claims.map((claim) => <li key={claim}>{claim}</li>)}
          </ul>
        )}
      </section>

      <section data-testid="research-brief-updates">
        <h3 className="text-xs font-semibold">冻结后有哪些已确认变更？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.updatesNote}</p>
        {model.confirmedUpdates.length > 0 && (
          <ul className="mt-2 space-y-1.5 text-xs">
            {model.confirmedUpdates.map((update) => (
              <li key={update.deltaId} className="rounded bg-muted/40 px-2 py-1.5" data-testid="research-brief-update-item">
                <p>
                  <span className={stateBadgeCls(update.stateKind)}>{update.stateLabel}</span>
                  {" · 确认时间："}{update.confirmedAt || "未知"}
                  {" · 基线版本：v"}{update.baseRevision ?? "?"}
                </p>
                <p className="mt-0.5">{update.reason}</p>
                {update.evidence.length > 0 ? (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-muted-foreground">已确认依据（{update.evidence.length}）</summary>
                    <EvidenceList items={update.evidence} empty="" showStance />
                  </details>
                ) : (
                  <p className="mt-1 text-muted-foreground">该变更没有关联证据快照；不能据此判断变更依据。</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section data-testid="research-brief-changes">
        <h3 className="text-xs font-semibold">自上次正式检查以来，哪些内容发生了变化？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.changes.note}</p>
        {model.changes.baselineText && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            {model.changes.baselineText}
            {model.changes.fetchedAt ? ` · 读取时间 ${model.changes.fetchedAt}` : ""}
            {model.changes.observationCount !== null ? ` · 后续观察 ${model.changes.observationCount} 次` : ""}
          </p>
        )}
        {model.changes.items.length > 0 && (
          <ul className="mt-2 space-y-1.5 text-xs">
            {model.changes.items.map((item) => (
              <li key={`${item.kind}:${item.recordKey || item.claim}`} className="rounded bg-muted/40 px-2 py-1.5">
                <span className="font-medium">{item.label}</span>
                {item.classificationLabel && <span className="ml-1 text-muted-foreground">分类：{item.classificationLabel}</span>}
                <p className="mt-0.5">{item.claim}</p>
                <p className="mt-0.5 text-muted-foreground">来源：{item.source}{item.detail ? ` · ${item.detail}` : ""}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section data-testid="research-brief-evidence">
        <h3 className="text-xs font-semibold">有哪些支持与反对依据，来源是什么？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.evidence.note}</p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-[11px] font-medium">支持（最初冻结快照）</p>
            <EvidenceList items={model.evidence.supporting} empty="确认版本没有支持立场记录。" />
          </div>
          <div>
            <p className="text-[11px] font-medium">反对（最初冻结快照；已确认变更的依据见上节）</p>
            <EvidenceList items={model.evidence.opposing} empty="没有反对记录 ≠ 没有反对证据。" />
          </div>
        </div>
        {latestUpdate && latestUpdate.evidence.some((item) => item.stance === "oppose") && (
          <p className="mt-2 text-[11px] text-warning" data-testid="research-brief-update-opposing-hint">
            注意：已确认变更中包含反对当前观点的依据，请展开上节「已确认依据」核对原文与来源。
          </p>
        )}
      </section>

      <section data-testid="research-brief-invalidation">
        <h3 className="text-xs font-semibold">出现什么条件，需要改变当前判断？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.invalidation.note}</p>
        {model.invalidation.conditions.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
            {model.invalidation.conditions.map((item) => <li key={item}>{item}</li>)}
          </ul>
        )}
      </section>

      <section data-testid="research-brief-verification">
        <h3 className="text-xs font-semibold">原研究记录了哪些待核验节点，现在是什么状态？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.verification.catalystsNote}</p>
        {model.verification.catalysts.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
            {model.verification.catalysts.map((item) => (
              <li key={item} data-verification-catalyst>
                {item}
                <span className="ml-1 text-muted-foreground">（尚未核验：摘要未发现与该节点已建立的证据关联）</span>
              </li>
            ))}
          </ul>
        )}
        {model.verification.calendarState && (
          <p className="mt-2 text-xs" data-verification-calendar-state={model.verification.calendarState}>
            {model.verification.calendarLine}
          </p>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          「预计发生」≠「已实际发生」，「已实际披露」≠「业绩符合预期」；已确认支持 / 削弱 / 证伪只看上方「已确认变更」。预约日已过只代表延迟信号，不是违规或延期认定。
        </p>
      </section>

      <section data-testid="research-brief-freshness">
        <h3 className="text-xs font-semibold">材料对应什么时间，还有哪些数据缺口？</h3>
        <p className="mt-2 text-xs">冻结时间：{model.freshness.frozenAt || "未知"}</p>
        {model.freshness.gaps.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground" data-testid="research-brief-gaps">
            {model.freshness.gaps.map((gap) => <li key={gap}>{gap}</li>)}
          </ul>
        )}
      </section>
    </section>
  );
}
