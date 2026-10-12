import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { CampaignAIDraftButton } from "../../../src/components/campaign/CampaignAIDraftButton";
import { saveLlm } from "../../../src/lib/llm";
function Fixture() {
  const [campaign, setCampaign] = useState("campaign-one");
  const [context, setContext] = useState("thesis-one");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <main><h1>真实 AI 草稿确认组件 · 合成资料</h1>
    <CampaignAIDraftButton campaignId={campaign} contextIdentity={context} disabled={false} onResult={value => setResult(value.draft_id)} onError={setError} onBusyChange={setBusy} />
    <button onClick={() => { setCampaign("campaign-two"); setContext("thesis-two"); }}>切换投资计划</button>
    <button onClick={() => saveLlm({ provider: "api-compatible", model: "changed-model", baseURL: "https://model.example/v1", apiKey: "synthetic" })}>切换模型</button>
    <output data-testid="busy">{String(busy)}</output><output data-testid="result">{result}</output><p role="alert">{error}</p>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
