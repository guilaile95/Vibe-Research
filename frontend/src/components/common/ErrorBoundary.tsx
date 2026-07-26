import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error?: Error; }

/**
 * 错误边界：捕获子树渲染异常。
 * - 默认 fallback 带「重试」按钮（重置错误状态），适用于懒加载 chunk 加载失败等瞬时错误。
 * - 也支持外部传入自定义 fallback（不强制重试）。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  retry = () => this.setState({ hasError: false, error: undefined });

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;
      return (
        <div className="m-4 flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">{this.state.error?.message || "加载出错"}</span>
          <button
            onClick={this.retry}
            className="inline-flex items-center gap-1 rounded-md bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/20"
          >
            <RotateCcw className="h-3 w-3" /> 重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
