import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GlassCard } from "@/components/ui/GlassCard";
import { firstResearchStatus, readFirstResearchLocalState, subscribeFirstResearchState, type CredentialMirrorStatus } from "@/lib/firstResearchStatus";

export function FirstResearchStatusCard({ mirror }: { mirror: CredentialMirrorStatus | null }) {
  const [local, setLocal] = useState(readFirstResearchLocalState);
  useEffect(() => subscribeFirstResearchState(() => setLocal(readFirstResearchLocalState())), []);
  const status = firstResearchStatus(local, mirror);

  return (
    <GlassCard className="mb-4" data-testid="first-research-status">
      <h3 className="text-sm font-semibold">从接入到第一条研究记录</h3>
      <p className="mt-2 text-xs" data-testid="first-research-notes-status">{status.research}</p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-muted-foreground">查看配置状态与能力边界</summary>
        <dl className="mt-2 space-y-2">
          <div><dt className="text-muted-foreground">浏览器配置</dt><dd>{status.browser}</dd></div>
          <div><dt className="text-muted-foreground">后台凭据</dt><dd>{status.mirror}</dd></div>
          <div><dt className="text-muted-foreground">模型调用</dt><dd>{status.model}</dd></div>
        </dl>
        <p className="mt-2 text-muted-foreground">{status.capability}</p>
        <p className="mt-2 text-muted-foreground">后端是否可响应见上方运行信息。记录数量仅说明内容已保存，不验证研究质量或投资结论。</p>
      </details>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-primary">
        <Link to="/stock-data" className="hover:underline">开始个股研究</Link>
        <Link to="/notes" className="hover:underline">打开研究笔记</Link>
      </div>
    </GlassCard>
  );
}
