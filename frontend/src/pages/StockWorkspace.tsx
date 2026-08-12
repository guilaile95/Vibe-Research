import { StockWorkspaceShell } from "@/components/stock/StockWorkspaceShell";
import { StockData } from "@/pages/StockData";

export function StockWorkspace() {
  return (
    <StockWorkspaceShell>
      <StockData />
    </StockWorkspaceShell>
  );
}
