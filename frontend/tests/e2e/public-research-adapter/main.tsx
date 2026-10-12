import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Intel } from "@/pages/Intel";
import "../../../src/index.css";
createRoot(document.getElementById("root")!).render(<BrowserRouter><main className="mx-auto max-w-6xl p-4"><Intel /></main></BrowserRouter>);
