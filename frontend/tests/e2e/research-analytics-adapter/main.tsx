import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { ResearchAnalytics } from "@/pages/ResearchAnalytics";
import { Notes } from "@/pages/Notes";
import "../../../src/index.css";
function AcceptancePages() {
  const [notes, setNotes] = useState(false);
  return <MemoryRouter><nav className="p-4"><button onClick={() => setNotes(false)}>验收：研究计算页面</button><button onClick={() => setNotes(true)}>验收：研究记录页面</button></nav><main className="p-4">{notes ? <Notes /> : <ResearchAnalytics />}</main></MemoryRouter>;
}
createRoot(document.getElementById("root")!).render(<AcceptancePages />);
