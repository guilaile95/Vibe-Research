import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ResearchKlineChart } from "../../../src/components/ui/ResearchKlineChart";
import "../../../src/index.css";
const bars = Array.from({ length: 65 }, (_, i) => ({ date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), open: 10, high: 12, low: 9, close: 11, volume: i === 64 ? -1 : i * 1000000000 })).filter((_, i) => i !== 10);
function Fixture() {
  const [code, setCode] = useState("000001");
  const [period, setPeriod] = useState("day");
  const [version, setVersion] = useState(0);
  const [empty, setEmpty] = useState(false);
  return <main className="max-w-3xl p-3">
    <button onClick={() => setCode(code === "000001" ? "000002" : "000001")}>Switch stock</button>
    <button onClick={() => setPeriod(period === "day" ? "week" : "day")}>Switch period</button>
    <button onClick={() => setVersion(version + 1)}>Correct data</button>
    <button onClick={() => setEmpty(!empty)}>Empty data</button>
    <ResearchKlineChart code={code} indicators={null} barPeriod={period} bars={empty ? [] : bars.map((b) => ({...b, volume: b.volume + version}))} />
    <button>After chart</button>
  </main>;
}
createRoot(document.getElementById("root")!).render(<BrowserRouter><Fixture /></BrowserRouter>);
