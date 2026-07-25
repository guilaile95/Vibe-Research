import { createBrowserRouter, Navigate, useParams } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { DailyReview } from "@/pages/DailyReview";
import { Intel } from "@/pages/Intel";
import { Sectors } from "@/pages/Sectors";
import { SectorDetail } from "@/pages/SectorDetail";
import { SectorResearchPage } from "@/pages/SectorResearchPage";
import { Portfolio } from "@/pages/Portfolio";
import { DecisionCockpit } from "@/pages/DecisionCockpit";
import { StockData } from "@/pages/StockData";
import { Watchlist } from "@/pages/Watchlist";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { Settings } from "@/pages/Settings";
import { hasSectorResearchWorkspace } from "@/data/sectorResearch";

/**
 * /sectors/:key/:tag — 仅已注册研究工作台的板块；
 * 未注册 key 回退到 /sectors/:key（通用详情或 404）。
 */
function SectorResearchTagRoute() {
  const { key } = useParams();
  if (!hasSectorResearchWorkspace(key)) {
    return <Navigate to={key ? `/sectors/${key}` : "/sectors"} replace />;
  }
  return <SectorResearchPage />;
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/intel", element: <Intel /> },
      { path: "/sectors", element: <Sectors /> },
      // 更具体的 :key/:tag 必须排在 :key 之前
      { path: "/sectors/:key/:tag", element: <SectorResearchTagRoute /> },
      { path: "/sectors/:key", element: <SectorDetail /> },
      { path: "/portfolio", element: <Portfolio /> },
      { path: "/cockpit", element: <DecisionCockpit /> },
      { path: "/stock-data", element: <StockData /> },
      { path: "/watchlist", element: <Watchlist /> },
      { path: "/my-reports", element: <MyReports /> },
      { path: "/notes", element: <Notes /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);
