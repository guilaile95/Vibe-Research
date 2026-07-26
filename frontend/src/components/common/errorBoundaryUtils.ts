/**
 * 错误分类：chunk/import 失败必须整页 reload；
 * 普通渲染错误可尝试 remount（不保证恢复，尤其不会让已拒绝的 React.lazy 重新拉 chunk）。
 */
export type ErrorBoundaryKind = "chunk" | "render";

const CHUNK_PATTERNS: RegExp[] = [
  /Loading chunk.*failed/i,
  /Failed to fetch dynamically imported module/i,
  /Failed to fetch (dynamically )?import/i,
  /Importing a module script failed/i,
  /Loading chunk failed/i,
];

export function classifyError(error?: Error | null): ErrorBoundaryKind {
  if (!error) return "render";
  if (error.name === "ChunkLoadError") return "chunk";
  const msg = error.message || "";
  for (const re of CHUNK_PATTERNS) {
    if (re.test(msg)) return "chunk";
  }
  return "render";
}

export function isChunkLoadError(error?: Error | null): boolean {
  return classifyError(error) === "chunk";
}
