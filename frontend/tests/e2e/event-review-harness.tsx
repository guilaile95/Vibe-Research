import React from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { EventResearchReview } from '../../src/components/campaign/EventResearchReview';
const event = {
  event_id:'event-1', security_code:'600519', security_name:null, campaign_ids:['campaign-a','campaign-b'],
  event_type:'PERIODIC_REPORT' as const, event_date:'2026-10-19', date_semantics:'DATE_ONLY', state:'CONFIRMED',
  title:'定期报告', details:{}, source:'fixture', source_record_identity:'period-1', fetched_at:'2026-10-19T00:00:00Z',
  limitations:[], observation_hash:'hash', observation_receipt:'receipt',
};
createRoot(document.getElementById('root')!).render(<MemoryRouter><EventResearchReview event={event} /></MemoryRouter>);
