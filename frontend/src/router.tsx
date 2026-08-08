import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, useParams } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { hasSectorResearchWorkspace } from "@/data/sectorResearch";

const DailyReview = lazy(() => import("@/pages/DailyReview").then((m) => ({ default: m.DailyReview })));
const Intel = lazy(() => import("@/pages/Intel").then((m) => ({ default: m.Intel })));
const Sectors = lazy(() => import("@/pages/Sectors").then((m) => ({ default: m.Sectors })));
const SectorDetail = lazy(() => import("@/pages/SectorDetail").then((m) => ({ default: m.SectorDetail })));
const SectorResearchPage = lazy(() => import("@/pages/SectorResearchPage").then((m) => ({ default: m.SectorResearchPage })));
const Portfolio = lazy(() => import("@/pages/Portfolio").then((m) => ({ default: m.Portfolio })));
const DecisionCockpit = lazy(() => import("@/pages/DecisionCockpit").then((m) => ({ default: m.DecisionCockpit })));
const StockWorkspace = lazy(() => import("@/pages/StockWorkspace").then((m) => ({ default: m.StockWorkspace })));
const ScreenerWorkspace = lazy(() => import("@/pages/ScreenerWorkspace").then((m) => ({ default: m.ScreenerWorkspace })));
const MarketHistory = lazy(() => import("@/pages/MarketHistory").then((m) => ({ default: m.MarketHistory })));
const Watchlist = lazy(() => import("@/pages/Watchlist").then((m) => ({ default: m.Watchlist })));
const MyReports = lazy(() => import("@/pages/MyReports").then((m) => ({ default: m.MyReports })));
const Notes = lazy(() => import("@/pages/Notes").then((m) => ({ default: m.Notes })));
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));
const ThesisList = lazy(() => import("@/pages/ThesisList").then((m) => ({ default: m.ThesisList })));
const ThesisNew = lazy(() => import("@/pages/ThesisNew").then((m) => ({ default: m.ThesisNew })));
const ThesisDetail = lazy(() => import("@/pages/ThesisDetail").then((m) => ({ default: m.ThesisDetail })));
const ThesisRevision = lazy(() => import("@/pages/ThesisRevision").then((m) => ({ default: m.ThesisRevision })));
const EvidenceList = lazy(() => import("@/pages/EvidenceList").then((m) => ({ default: m.EvidenceList })));
const EvidenceNew = lazy(() => import("@/pages/EvidenceNew").then((m) => ({ default: m.EvidenceNew })));
const EvidenceDetail = lazy(() => import("@/pages/EvidenceDetail").then((m) => ({ default: m.EvidenceDetail })));
const DataHealth = lazy(() => import("@/pages/DataHealth").then((m) => ({ default: m.DataHealth })));
const Trades = lazy(() => import("@/pages/Trades").then((m) => ({ default: m.Trades })));
const DecisionFeedback = lazy(() => import("@/pages/DecisionFeedback").then((m) => ({ default: m.DecisionFeedback })));
const DecisionEvidence = lazy(() => import("@/pages/DecisionEvidence").then((m) => ({ default: m.default })));
const SignalLedger = lazy(() => import("@/pages/SignalLedger").then((m) => ({ default: m.default })));
const AccountPolicy = lazy(() => import("@/pages/AccountPolicy").then((m) => ({ default: m.default })));
const DecisionPerformance = lazy(() => import("@/pages/DecisionPerformance").then((m) => ({ default: m.default })));
const PerformanceAttribution = lazy(() => import("@/pages/PerformanceAttribution").then((m) => ({ default: m.default })));

function PageFallback() {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="animate-fade-up space-y-6">
      <span className="sr-only">页面加载中</span>
      <div className="space-y-2">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-4 w-72" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[1, 2, 3, 4].map((i) => <div key={i} className="card-surface h-20" />)}
      </div>
      <div className="card-surface h-44" />
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
      { path: "/market-history", element: withSuspense(<MarketHistory />) },
      { path: "/intel", element: withSuspense(<Intel />) },
      { path: "/sectors", element: withSuspense(<Sectors />) },
      { path: "/sectors/:key/:tag", element: <SectorResearchTagRoute /> },
      { path: "/sectors/:key", element: withSuspense(<SectorDetail />) },
      { path: "/portfolio", element: withSuspense(<Portfolio />) },
      { path: "/trades", element: withSuspense(<Trades />) },
      { path: "/decision-feedback", element: withSuspense(<DecisionFeedback />) },
      { path: "/decision-evidence", element: withSuspense(<DecisionEvidence />) },
      { path: "/signal-ledger", element: withSuspense(<SignalLedger />) },
      { path: "/account-policy", element: withSuspense(<AccountPolicy />) },
      { path: "/decision-performance", element: withSuspense(<DecisionPerformance />) },
      { path: "/performance-attribution", element: withSuspense(<PerformanceAttribution />) },
      { path: "/cockpit", element: withSuspense(<DecisionCockpit />) },
      { path: "/stock-data", element: withSuspense(<StockWorkspace />) },
      { path: "/screener", element: withSuspense(<ScreenerWorkspace />) },
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
