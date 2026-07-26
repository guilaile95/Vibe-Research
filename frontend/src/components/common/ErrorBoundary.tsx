import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCcw, RefreshCw } from "lucide-react";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error?: Error; rebuildKey: number; }

/**
 * 错误边界：捕获子树渲染异常。
 *
 * 行为：
 * - chunk 加载错误（ChunkLoadError / import promise rejected）
 *   → 显示错误 +「重新加载页面」按钮（window.location.reload）
 * - 普通渲染错误
 *   → 显示错误 +「重试」按钮（remount key++，重新执行 lazy import）
 * - 也支持外部传入自定义 fallback（不强制重试）。
 *
 * 为什么对 chunk 错误用 reload：React.lazy 会缓存已拒绝的 import Promise，
 * 单纯重置 state + remount key 无法让浏览器重新请求 JS chunk，
 * 只有 reload 能强制浏览器重新发起 chunk 请求。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, rebuildKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  private isChunkLoadError(error?: Error): boolean {
    if (!error) return false;
    // Webpack: ChunkLoadError; Vite: 动态 import 失败时 message 含 "Failed to fetch" 或 "Loading chunk"
    return (
      error.name === "ChunkLoadError" ||
      /Loading chunk.*failed/i.test(error.message) ||
      /Failed to fetch (dynamically )?import/i.test(error.message) ||
      /Importing a module script failed/i.test(error.message)
    );
  }

  retry = () => {
    if (this.isChunkLoadError(this.state.error)) {
      window.location.reload();
      return;
    }
    // 对于普通渲染错误 + lazy import 拒绝：remount key 强制重新执行 import factory
    this.setState((prev) => ({
      hasError: false,
      error: undefined,
      rebuildKey: prev.rebuildKey + 1,
    }));
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;

      const isChunk = this.isChunkLoadError(this.state.error);

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
              <><RotateCcw className="h-3 w-3" /> 重试</>
            )}
          </button>
        </div>
      );
    }

    // rebuildKey 递增后 React 会 unmount + remount 子树，
    // 让 React.lazy 的 import factory 有机会重新执行（虽然 lazy 有缓存，
    // 但 remount + ErrorBoundary 重置后子树重建，lazy 组件重新挂载时
    // 会重新走 React.lazy 的 resolve 逻辑）。
    return <div key={this.state.rebuildKey}>{this.props.children}</div>;
  }
}
