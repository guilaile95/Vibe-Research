import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, useParams } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { hasSectorResearchWorkspace } from "@/data/sectorResearch";

/** 页面级懒加载：保持 named export 映射为 default 供 React.lazy */
const DailyReview = lazy(() =>
  import("@/pages/DailyReview").then((m) => ({ default: m.DailyReview })),
);
const Intel = lazy(() =>
  import("@/pages/Intel").then((m) => ({ default: m.Intel })),
);
const Sectors = lazy(() =>
  import("@/pages/Sectors").then((m) => ({ default: m.Sectors })),
);
const SectorDetail = lazy(() =>
  import("@/pages/SectorDetail").then((m) => ({ default: m.SectorDetail })),
);
const SectorResearchPage = lazy(() =>
  import("@/pages/SectorResearchPage").then((m) => ({
    default: m.SectorResearchPage,
  })),
);
const Portfolio = lazy(() =>
  import("@/pages/Portfolio").then((m) => ({ default: m.Portfolio })),
);
const DecisionCockpit = lazy(() =>
  import("@/pages/DecisionCockpit").then((m) => ({
    default: m.DecisionCockpit,
  })),
);
const StockData = lazy(() =>
  import("@/pages/StockData").then((m) => ({ default: m.StockData })),
);
const Watchlist = lazy(() =>
  import("@/pages/Watchlist").then((m) => ({ default: m.Watchlist })),
);
const MyReports = lazy(() =>
  import("@/pages/MyReports").then((m) => ({ default: m.MyReports })),
);
const Notes = lazy(() =>
  import("@/pages/Notes").then((m) => ({ default: m.Notes })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);

function PageFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center p-6 text-sm text-slate-500">
      加载中…
    </div>
  );
}

function withSuspense(node: ReactNode) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageFallback />}>{node}</Suspense>
    </ErrorBoundary>
  );
}

/**
 * /sectors/:key/:tag — 仅已注册研究工作台的板块；
 * 未注册 key 回退到 /sectors/:key（通用详情或 404）。
 * hasSectorResearchWorkspace 保持同步 import，避免路由守卫异步抖动。
 */
function SectorResearchTagRoute() {
  const { key } = useParams();
  if (!hasSectorResearchWorkspace(key)) {
    return <Navigate to={key ? `/sectors/${key}` : "/sectors"} replace />;
  }
  return withSuspense(<SectorResearchPage />);
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: withSuspense(<DailyReview />) },
      { path: "/intel", element: withSuspense(<Intel />) },
      { path: "/sectors", element: withSuspense(<Sectors />) },
      // 更具体的 :key/:tag 必须排在 :key 之前
      { path: "/sectors/:key/:tag", element: <SectorResearchTagRoute /> },
      { path: "/sectors/:key", element: withSuspense(<SectorDetail />) },
      { path: "/portfolio", element: withSuspense(<Portfolio />) },
      { path: "/cockpit", element: withSuspense(<DecisionCockpit />) },
      { path: "/stock-data", element: withSuspense(<StockData />) },
      { path: "/watchlist", element: withSuspense(<Watchlist />) },
      { path: "/my-reports", element: withSuspense(<MyReports />) },
      { path: "/notes", element: withSuspense(<Notes />) },
      { path: "/settings", element: withSuspense(<Settings />) },
    ],
  },
]);
