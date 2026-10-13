import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { LocalReportOcr } from '@/components/reports/LocalReportOcr';
import { ReportPageReader } from '@/components/reports/ReportPageReader';
import { ResearchShareCard } from '@/components/stock/ResearchShareCard';
import type { Valuation } from '@/lib/api';
import '@/index.css';
const report = { id: 'synthetic', name: 'Synthetic scan', ext: '.pdf', industry: '', size: 1000, ts: 1, file_sha256: 'a'.repeat(64) };
function App() {
  const [count, setCount] = useState(0);
  const [show, setShow] = useState(true);
  const [hash, setHash] = useState('a'.repeat(64));
  const valuation = { code: '600000', name: 'PRIVATE_NAME', price: 11.25, quote_source: 'tencent', quote_trade_date: '2026-10-09', pe_ttm: null, mcap_yi: 1400, fixture: true,
    account: 'SECRET_ACCOUNT', api_key: 'SECRET_KEY', path: '/home/private', journal: 'SECRET_JOURNAL' } as unknown as Valuation;
  return <main className="mx-auto max-w-3xl space-y-4 p-4"><h1>Synthetic acceptance only</h1>
    <button onClick={() => setShow(!show)}>切换资料面板</button><p data-testid="index-refresh-count">刷新次数 {count}</p>
    <button onClick={() => setHash(value => value === 'a'.repeat(64) ? 'b'.repeat(64) : 'a'.repeat(64))}>切换原文件版本</button>
    <section data-testid="primary-ocr">{show && <LocalReportOcr report={{ ...report, file_sha256: hash }} onIndexed={async () => setCount(n => n + 1)} />}</section>
    <section data-testid="legacy-ocr"><LocalReportOcr report={{ ...report, id: 'legacy', file_sha256: undefined }} onIndexed={async () => setCount(n => n + 1)} /></section>
    <ReportPageReader reports={[report]} />
    <ResearchShareCard valuation={valuation} />
  </main>;
}
createRoot(document.getElementById('root')!).render(<MemoryRouter><App /></MemoryRouter>);
