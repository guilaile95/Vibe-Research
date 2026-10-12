import { useState } from "react";
import { createRoot } from "react-dom/client";
import { SealQualityCard } from "@/components/dailyReview/SealQualityCard";
import "../../../src/index.css";

function SyntheticParent() {
  const [date, setDate] = useState<string | null>("2026-07-30");
  const [shown, setShown] = useState(true);
  return <main className="mx-auto max-w-6xl space-y-4 p-4">
    <h1>合成场景：真实封板质量组件</h1>
    <nav className="flex flex-wrap gap-4" aria-label="合成日期控制">
      <button onClick={() => setDate("2026-07-30")}>2026-07-30</button>
      <button onClick={() => setDate("2026-07-29")}>2026-07-29</button>
      <button onClick={() => setDate(null)}>清空日期</button>
      <button onClick={() => setShown((value) => !value)}>切换显示</button>
    </nav>
    {shown ? <SealQualityCard tradeDate={date} /> : null}
  </main>;
}

createRoot(document.getElementById("root")!).render(<SyntheticParent />);
