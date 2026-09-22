import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HeartPulse, RefreshCw, Server } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { readBackendRuntime, type BackendRuntimeCheck } from "@/lib/backendRuntime";

export function BackendRuntimeCard() {
  const [check, setCheck] = useState<BackendRuntimeCheck | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    setCheck(null);
    void readBackendRuntime().then((result) => {
      if (active) setCheck(result);
    });
    return () => { active = false; };
  }, [refresh]);

  const runtime = check?.runtime;
  const version = check?.version && check.version !== "unknown" ? check.version : "未知";

  return (
    <GlassCard className="mb-4" data-testid="backend-runtime-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Server className="h-4 w-4 text-primary" /> 本机后端运行信息
        </h3>
        <button
          type="button"
          onClick={() => setRefresh((value) => value + 1)}
          disabled={!check}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${!check ? "animate-spin" : ""}`} /> 刷新连接
        </button>
      </div>
      <p role="status" className="mt-3 text-sm" data-testid="backend-connection-status">
        后端服务：{!check ? "检查中…" : check.connected ? "已连接（接口可响应）" : "连接未确认，请确认后端已启动后刷新"}
      </p>
      {check && check.infoStatus !== "available" && (
        <p className="mt-2 text-xs text-muted-foreground" data-testid="backend-runtime-fallback">
          {check.infoStatus === "auth_required"
            ? "运行信息访问受限，请检查本页后端访问密钥及服务访问设置，保存后刷新。"
            : check.infoStatus === "unsupported"
              ? "当前后端未提供运行信息接口；更新并重启后端后可查看 SHA 和目录。"
              : "暂时无法读取运行信息，未取得的版本和目录显示为未知。"}
        </p>
      )}
      <dl className="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
        <div><dt className="text-muted-foreground">后端软件版本</dt><dd className="mt-1 font-mono" data-testid="backend-version">{version}</dd></div>
        <div>
          <dt className="text-muted-foreground">启动时源码状态</dt>
          <dd className="mt-1" data-testid="backend-source-state">
            {runtime?.source_state === "clean" ? "无本地改动"
              : runtime?.source_state === "modified" ? "含本地改动，SHA 仅为提交基线" : "未知"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">启动时提交 SHA</dt>
          <dd className="mt-1 break-all font-mono" data-testid="backend-git-sha">{runtime?.git_sha ?? "未知"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">后端代码目录</dt>
          <dd className="mt-1 break-all font-mono" data-testid="backend-source-directory">{runtime?.source_directory ?? "未知"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">进程运行目录</dt>
          <dd className="mt-1 break-all font-mono" data-testid="backend-working-directory">{runtime?.working_directory ?? "未知"}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">版本与目录取自后端启动时快照；更新代码后需重启后端。此处不判断 AI 连接状态，AI 接入仍由下方配置区检查。</p>
      <div className="mt-3 border-t border-border/50 pt-3 text-xs">
        <Link to="/data-health" className="inline-flex items-center gap-1.5 text-primary hover:underline">
          <HeartPulse className="h-3.5 w-3.5" /> 查看行情与数据健康
        </Link>
        <p className="mt-1 text-muted-foreground">服务已连接仅说明后端可响应。行情是否缺失、过期或降级，请查看数据健康。</p>
      </div>
    </GlassCard>
  );
}
