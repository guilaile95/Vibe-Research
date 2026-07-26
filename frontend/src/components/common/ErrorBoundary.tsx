import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCcw, RefreshCw } from "lucide-react";
import { classifyError } from "./errorBoundaryUtils";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error?: Error; rebuildKey: number; }

/**
 * 错误边界：捕获子树渲染异常。
 *
 * 行为：
 * - chunk 加载错误（ChunkLoadError / 动态 import 失败）
 *   → 显示错误 +「重新加载页面」（window.location.reload）
 * - 普通渲染错误
 *   → 显示错误 +「重试重新挂载」（key++ remount 子树，不保证一定恢复）
 * - 支持外部自定义 fallback。
 *
 * 说明：React.lazy 会缓存已拒绝的 import Promise，单纯 remount 无法重新请求
 * 已失败的 JS chunk；chunk 类错误必须 reload。普通渲染错误 remount 只是清掉
 * 出错子树的 state 再挂一次，不声称能修复 lazy 失败。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, rebuildKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  retry = () => {
    if (classifyError(this.state.error) === "chunk") {
      window.location.reload();
      return;
    }
    // 普通渲染错误：递增 key 强制 remount 子树（不保证恢复）
    this.setState((prev) => ({
      hasError: false,
      error: undefined,
      rebuildKey: prev.rebuildKey + 1,
    }));
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;

      const isChunk = classifyError(this.state.error) === "chunk";

      return (
        <div className="m-4 flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">
            {isChunk
              ? "页面加载失败（网络或资源版本异常）"
              : this.state.error?.message || "加载出错"}
          </span>
          <button
            onClick={this.retry}
            className="inline-flex items-center gap-1 rounded-md bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/20"
          >
            {isChunk ? (
              <><RefreshCw className="h-3 w-3" /> 重新加载页面</>
            ) : (
              <><RotateCcw className="h-3 w-3" /> 重试重新挂载</>
            )}
          </button>
        </div>
      );
    }

    // rebuildKey 递增后 React unmount + remount 子树，用于普通渲染错误的重试。
    // 这不会让已拒绝的 React.lazy import 重新拉 chunk。
    return <div key={this.state.rebuildKey}>{this.props.children}</div>;
  }
}
