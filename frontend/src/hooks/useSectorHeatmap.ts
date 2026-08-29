// 板块热力图数据获取 Hook。
//
// - 复用 api.marketBoards（同一数据源，不新建第二套板块接口）；
// - top_n 取较大值（50）以覆盖按成交额排序的主要板块；
// - fail-closed：请求错误 / 数据不可用 / 全部成交额缺失均显式表达；
// - 行业 / 概念切换时重新获取，不预取两种模式。

import { useCallback, useEffect, useState } from "react";
import { api, type BoardRankingData, type TimedComponentEnvelope } from "@/lib/api";
import { resolveHeatmapState, type HeatmapState } from "@/lib/sectorHeatmap";

export type HeatmapBoardType = "industry" | "concept";

const HEATMAP_TOP_N = 50;

interface UseSectorHeatmapResult {
  state: HeatmapState;
  boardType: HeatmapBoardType;
  setBoardType: (t: HeatmapBoardType) => void;
  refresh: () => void;
}

export function useSectorHeatmap(initialType: HeatmapBoardType = "industry"): UseSectorHeatmapResult {
  const [boardType, setBoardType] = useState<HeatmapBoardType>(initialType);
  const [envelope, setEnvelope] = useState<TimedComponentEnvelope<BoardRankingData> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    api.marketBoards(boardType, HEATMAP_TOP_N)
      .then((data) => {
        if (!alive) return;
        setEnvelope(data);
      })
      .catch(() => {
        if (!alive) return;
        setError(true);
        setEnvelope(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [boardType, refreshKey]);

  const state = resolveHeatmapState(envelope, loading, error, { maxItems: boardType === "concept" ? 40 : 30 });

  return { state, boardType, setBoardType, refresh };
}
