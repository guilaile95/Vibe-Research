// Real production components; only navigation, identities and market data are synthetic.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ReverseDcfCard } from '../../../src/components/research/ReverseDcfCard';
import { FilingEvidenceCard } from '../../../src/components/research/FilingEvidenceCard';
import { AnnouncementGroupsCard } from '../../../src/components/research/AnnouncementGroupsCard';
import { PredictionJournal } from '../../../src/components/personal-review/PredictionJournal';
import { PortfolioAllocationCard } from '../../../src/components/portfolio/PortfolioAllocationCard';
import { ResearchKlineChart } from '../../../src/components/ui/ResearchKlineChart';
import { registerAnnotationContext } from '../../../src/lib/researchAnnotations';
import type { EvidenceRecord } from '../../../src/lib/api';
import '../../../src/index.css';
const bars = registerAnnotationContext([
  { date: '2026-01-05', open: 10, high: 12, low: 9, close: 11, volume: 100 },
  { date: '2026-01-06', open: 11, high: 13, low: 10, close: 12, volume: 200 },
], { code: '000001', bar_period: 'day', snapshot_id: 'a'.repeat(64), token: 'b'.repeat(64), expires_at: '2099-01-01T00:00:00Z', points: [
  ['2026-01-05', '10', '12', '9', '11', '100'], ['2026-01-06', '11', '13', '10', '12', '200'],
] });
function Fixture() {
  const [view, setView] = useState('dcf');
  const [code, setCode] = useState('000001');
  const evidence = { id: code === '000001' ? 'anchor' : 'other', edit_token: 'v1', subject_type: 'stock', subject_id: code, evidence_type: 'financial_filing', source_title: 'Synthetic filing', claim: 'Synthetic claim', source_date: '2026-01-01', source_url: null, updated_at: '2026-01-01T00:00:00Z' } as EvidenceRecord;
  return <main className="max-w-3xl p-3 space-y-3">
    <p>SYNTHETIC COMPONENT ACCEPTANCE · no live providers or application-route coverage</p>
    <nav className="flex flex-wrap gap-3">{['dcf', 'filing', 'annotation', 'prediction', 'allocation', 'groups'].map(name => <button key={name} onClick={() => setView(name)}>{name}</button>)}<button onClick={() => setCode(code === '000001' ? '000002' : '000001')}>Switch subject</button></nav>
    {view === 'dcf' && <ReverseDcfCard subject={{ market: 'A', symbol: code }} />}
    {view === 'filing' && <FilingEvidenceCard key={code} evidence={evidence} />}
    {view === 'groups' && <AnnouncementGroupsCard key={code} evidence={evidence} />}
    {view === 'annotation' && <ResearchKlineChart code={code} bars={bars} indicators={null} barPeriod="day" />}
    {view === 'prediction' && <PredictionJournal />}
    {view === 'allocation' && <PortfolioAllocationCard />}
  </main>;
}
createRoot(document.getElementById('root')!).render(<BrowserRouter><Fixture /></BrowserRouter>);
