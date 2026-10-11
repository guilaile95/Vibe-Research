// Test-only parent adapter. All request ownership and rendering remain production code.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ResearchContinuityCard } from '../../../src/components/campaign/ResearchContinuityCard';
import '../../../src/index.css';
import { continuity } from '../research-continuity.fixture.mjs';
function Adapter() {
  const [props, setProps] = useState<any>({ campaignId: 'A', prefetched: continuity('A') });
  const [mounted, setMounted] = useState(true);
  Object.assign(window, { continuityFixture: { setProps, setMounted } });
  return <main className="mx-auto max-w-3xl p-4"><h1>Synthetic continuity component acceptance</h1>{mounted && <ResearchContinuityCard {...props} />}</main>;
}
createRoot(document.getElementById('root')!).render(<Adapter />);
