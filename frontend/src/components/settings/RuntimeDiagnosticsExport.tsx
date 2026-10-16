import { useEffect, useRef, useState } from "react";
import { get } from "@/lib/api";
import { parseRuntimeDiagnostics } from "@/lib/runtimeDiagnostics";

export function RuntimeDiagnosticsExport() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => {
    pending.current?.abort();
    pending.current = null;
  }, []);

  const download = async () => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setMessage("");
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const raw = await get<unknown>("/runtime-diagnostics/export", { signal: controller.signal });
      if (pending.current !== controller) return;
      if (controller.signal.aborted) throw new Error("cancelled diagnostics");
      const data = parseRuntimeDiagnostics(raw);
      const url = URL.createObjectURL(new Blob([JSON.stringify({ data }, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      try {
        link.href = url;
        link.download = "vibe-runtime-diagnostics.json";
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        URL.revokeObjectURL(url);
      }
      setMessage("已生成脱敏诊断文件；未探测数据源或模型连接");
    } catch {
      if (pending.current === controller) setMessage("诊断导出失败，请检查后端连接及已保存的访问密钥后重试；当前设置未修改");
    } finally {
      clearTimeout(timer);
      if (pending.current === controller) {
        pending.current = null;
        setBusy(false);
      }
    }
  };

  return <div className="mt-3 border-t border-border/50 pt-3 text-xs">
    <button type="button" data-testid="runtime-diagnostics-export" disabled={busy}
      onClick={() => void download()} className="text-primary hover:underline disabled:opacity-50">
      {busy ? "正在导出…" : "导出脱敏自检报告"}
    </button>
    <p className="mt-1 text-muted-foreground">仅检查版本、端口配置和目录权限；不读取凭据或账户资料，不验证服务可用性</p>
    {message && <p role="status" className="mt-1">{message}</p>}
  </div>;
}
