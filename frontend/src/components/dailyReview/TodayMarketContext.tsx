import { MarketCloud } from "@/components/market/MarketCloud";
import MarketIntelPanel from "@/components/market/MarketIntelPanel";

export function TodayMarketContext() {
  return (
    <div data-testid="today-market-context">
      <MarketCloud />
      <MarketIntelPanel />
    </div>
  );
}
