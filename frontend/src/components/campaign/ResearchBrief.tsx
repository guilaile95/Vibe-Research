import type { ResearchBriefModel } from "@/lib/researchBrief";

const codeCls = "rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]";

function EvidenceList({
  items,
  empty,
}: {
  items: ResearchBriefModel["evidence"]["supporting"];
  empty: string;
}) {
  if (items.length === 0) {
    return <p className="mt-1 text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="mt-1 space-y-1.5">
      {items.map((item) => (
        <li key={item.evidenceId} className="rounded bg-muted/40 px-2 py-1.5" data-testid={`research-brief-evidence-${item.stance}`}>
          <p className="font-medium">{item.claim}</p>
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
            只读整理当前 Campaign 的已确认研究。打开或刷新本页不会改写 Thesis、Decision 或交易。
          </p>
        </div>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-700">只读 · backend authority</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">Campaign</span>
        <span className={codeCls}>{model.campaignId || "缺少 campaign_id"}</span>
        {model.contextState === "loading" && <span className="text-muted-foreground">正在读取上下文…</span>}
      </div>

      <section data-testid="research-brief-subject">
        <h3 className="text-xs font-semibold">研究哪个标的、采用什么策略、预期周期多长？</h3>
        <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-5">
          <div><p className="text-muted-foreground">证券</p><p className="mt-1 font-medium" data-context-security>{model.securityCode}</p></div>
          <div><p className="text-muted-foreground">策略</p><p className="mt-1 font-medium" data-context-strategy>{model.strategyLabel}{model.strategyCode ? `（${model.strategyCode}）` : ""}</p></div>
          <div><p className="text-muted-foreground">Current Thesis</p><p className="mt-1 font-medium" data-context-thesis-status>{model.thesisVersionText}</p></div>
          <div><p className="text-muted-foreground">确认版本</p><p className="mt-1 font-medium" data-context-frozen-revision>{model.thesisVersionText}</p></div>
          <div><p className="text-muted-foreground">预期周期</p><p className="mt-1 font-medium" data-context-horizon>{model.horizonText}</p></div>
        </div>
        {model.horizonSource === "CURRENT_THESIS" ? (
          <p className="mt-2 text-xs leading-5 text-success" data-horizon-source="CURRENT_THESIS">
            预期周期来自已确认 Current Thesis，不是本页表单里的临时填写。
          </p>
        ) : model.horizonSource === "MANUAL_FALLBACK" ? (
          <p className="mt-2 text-xs leading-5 text-warning" role="status" data-horizon-source="MANUAL_FALLBACK">
            已确认 Thesis 当前不能提供合法周期。摘要不会猜测；下方表单仍需手工填写。
          </p>
        ) : (
          <p className="mt-2 text-xs leading-5 text-muted-foreground">证券、策略与 Thesis 版本均由 backend 按当前 Campaign 读取。</p>
        )}
      </section>

      <section data-testid="research-brief-view">
        <h3 className="text-xs font-semibold">当前已确认的研究观点是什么？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.confirmed.note}</p>
        {model.confirmed.title && <p className="mt-2 text-sm font-medium">{model.confirmed.title}</p>}
        {model.confirmed.summary && <p className="mt-1 text-xs">{model.confirmed.summary}</p>}
        {model.confirmed.claims.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
            {model.confirmed.claims.map((claim) => <li key={claim}>{claim}</li>)}
          </ul>
        )}
      </section>

      <section data-testid="research-brief-changes">
        <h3 className="text-xs font-semibold">自上次正式检查以来，哪些内容发生了变化？</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">{model.changes.note}</p>
        {model.changes.items.length > 0 && (
          <ul className="mt-2 space-y-1.5 text-xs">
            {model.changes.items.map((item) => (
              <li key={`${item.kind}:${item.claim}`} className="rounded bg-muted/40 px-2 py-1.5">
                <span className="font-medium">{item.label}</span>
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
            <p className="text-[11px] font-medium">支持</p>
            <EvidenceList items={model.evidence.supporting} empty="确认版本没有支持立场记录。" />
          </div>
          <div>
            <p className="text-[11px] font-medium">反对</p>
            <EvidenceList items={model.evidence.opposing} empty="没有反对记录 ≠ 没有反对证据。" />
          </div>
        </div>
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

      <section data-testid="research-brief-freshness">
        <h3 className="text-xs font-semibold">材料对应什么时间，还有哪些数据缺口或待核验节点？</h3>
        <p className="mt-2 text-xs">冻结时间：{model.freshness.frozenAt || "未知"}</p>
        <p className="mt-1 text-xs">{model.freshness.calendarText}</p>
        {model.freshness.gaps.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground" data-testid="research-brief-gaps">
            {model.freshness.gaps.map((gap) => <li key={gap}>{gap}</li>)}
          </ul>
        )}
      </section>
    </section>
  );
}
