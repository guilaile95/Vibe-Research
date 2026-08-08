import "./types";

declare module "./types" {
  interface TechnicalIndicatorLatest {
    kdj_k: number | null;
    kdj_d: number | null;
    kdj_j: number | null;
  }

  interface TechnicalIndicatorSeriesPoint {
    kdj_k: number | null;
    kdj_d: number | null;
    kdj_j: number | null;
  }
}

export {};
