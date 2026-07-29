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
const ThesisList = lazy(() =>
  import("@/pages/ThesisList").then((m) => ({ default: m.ThesisList })),
);
const ThesisNew = lazy(() =>
  import("@/pages/ThesisNew").then((m) => ({ default: m.ThesisNew })),
);
const ThesisDetail = lazy(() =>
  import("@/pages/ThesisDetail").then((m) => ({ default: m.ThesisDetail })),
);
const ThesisRevision = lazy(() =>
  import("@/pages/ThesisRevision").then((m) => ({ default: m.ThesisRevision })),
);
const EvidenceList = lazy(() =>
  import("@/pages/EvidenceList").then((m) => ({ default: m.EvidenceList })),
);
const EvidenceNew = lazy(() =>
  import("@/pages/EvidenceNew").then((m) => ({ default: m.EvidenceNew })),
);
const EvidenceDetail = lazy(() =>
  import("@/pages/EvidenceDetail").then((m) => ({ default: m.EvidenceDetail })),
);
const DataHealth = lazy(() =>
  import("@/pages/DataHealth").then((m) => ({ default: m.DataHealth })),
);
const Trades = lazy(() =>
  import("@/pages/Trades").then((m) => ({ default: m.Trades })),
);
const DecisionFeedback = lazy(() =>
  import("@/pages/DecisionFeedback").then((m) => ({ default: m.DecisionFeedback })),
);
const DecisionEvidence = lazy(() =>
  import("@/pages/DecisionEvidence").then((m) => ({ default: m.default })),
);
const SignalLedger = lazy(() =>
  import("@/pages/SignalLedger").then((m) => ({ default: m.default })),
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
	      { path: "/trades", element: withSuspense(<Trades />) },
	      { path: "/decision-feedback", element: withSuspense(<DecisionFeedback />) },
		      { path: "/decision-evidence", element: withSuspense(<DecisionEvidence />) },
		      { path: "/signal-ledger", element: withSuspense(<SignalLedger />) },
	      { path: "/cockpit", element: withSuspense(<DecisionCockpit />) },
      { path: "/stock-data", element: withSuspense(<StockData />) },
      { path: "/watchlist", element: withSuspense(<Watchlist />) },
      { path: "/my-reports", element: withSuspense(<MyReports />) },
      { path: "/notes", element: withSuspense(<Notes />) },
      { path: "/thesis", element: withSuspense(<ThesisList />) },
      { path: "/thesis/new", element: withSuspense(<ThesisNew />) },
      { path: "/thesis/:id", element: withSuspense(<ThesisDetail />) },
      { path: "/thesis/:id/revision/:rev", element: withSuspense(<ThesisRevision />) },
      { path: "/evidence", element: withSuspense(<EvidenceList />) },
      { path: "/evidence/new", element: withSuspense(<EvidenceNew />) },
      { path: "/evidence/:id", element: withSuspense(<EvidenceDetail />) },
      { path: "/settings", element: withSuspense(<Settings />) },
      { path: "/data-health", element: withSuspense(<DataHealth />) },
    ],
  },
]);
