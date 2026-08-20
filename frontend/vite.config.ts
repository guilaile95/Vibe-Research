import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// 开源版后端接口（可插拔 AI 层 + 数据）走 /api 前缀，默认代理到本地 FastAPI。
// Phase 1 为纯前端空壳，后端未接时前端仍可独立跑（接口调用做了降级）。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // 默认用 127.0.0.1 而非 localhost：部分 macOS/Node 会把 localhost 优先解析到 IPv6 ::1，
  // 而后端常只监听 127.0.0.1:8900（IPv4），导致 /api 代理 ECONNREFUSED（issue #8）。
  const apiTarget = env.VITE_API_URL || "http://127.0.0.1:8900";

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      port: 5899,
      strictPort: true,
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
      },
    },
    preview: {
      port: 5899,
      strictPort: true,
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            const normalized = id.replace(/\\/g, "/");

            // 板块研究数据体量大：按路径拆到独立 chunk（含 Windows 路径）
            if (normalized.includes("/src/data/sectorResearch")) {
              return "sector-research";
            }

            if (!normalized.includes("/node_modules/")) {
              return;
            }

            // echarts + zrender
            if (
              normalized.includes("/echarts/") ||
              normalized.includes("/zrender/")
            ) {
              return "vendor-charts";
            }

            // markdown 渲染栈（react-markdown / remark-gfm 及其常见依赖）
            if (
              /\/node_modules\/(react-markdown|remark-gfm|remark-parse|remark-rehype|remark-stringify|rehype-raw|rehype-sanitize|mdast-|micromark|micromark-|unist-|hast-|vfile|vfile-|unified|bail|trough|extend|is-plain-obj|ccount|devlop|longest-streak|markdown-table|trim-lines|zwitch|decode-named-character-reference|character-entities|property-information|space-separated-tokens|comma-separated-tokens|style-to-object|inline-style-parser|html-url-attributes|mdast-util-|hast-util-|unist-util-)[^/]*\//.test(
                normalized,
              )
            ) {
              return "vendor-markdown";
            }

            if (normalized.includes("/zustand/")) {
              return "vendor-zustand";
            }

            // React 核心 + 路由
            if (
              /\/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(
                normalized,
              )
            ) {
              return "vendor-react";
            }
          },
        },
      },
    },
  };
});
