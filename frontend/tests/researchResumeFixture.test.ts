import assert from 'node:assert/strict';
import test from 'node:test';
import { canonicalJson, researchContentHash, RESEARCH_BACKUP_SCHEMA, validateResearchChains } from '../src/lib/researchWorkflow.ts';
import { createResearchWorkflowStore } from '../src/lib/researchWorkflowStore.ts';
import { reportPageMaterials } from '../src/lib/researchCheck.ts';
import { resumeContextFixture, originalReport, researchCheckPageReadReply } from './e2e/research-check-loop.fixture.mjs';

test('resume fixture is a complete native-store snapshot after attaching real-shaped current material receipts', async () => {
  const materials = await reportPageMaterials(originalReport, researchCheckPageReadReply({ report_id: originalReport.id, selected_report_ids: [originalReport.id], expected_file_sha256: originalReport.file_sha256, page_from: 1, page_to: 1 }).data, '600519', 1, 1);
  const fixture = resumeContextFixture(Date.now() + 1);
  for (const round of fixture.rounds.filter(round => round.securityCode === '600519')) round.materials = materials;
  assert.doesNotThrow(() => validateResearchChains(fixture.questions, fixture.rounds));
  const data = { ...fixture, operations: [], legacySources: [] };
  const manifest = { sha256: await researchContentHash(canonicalJson(data)), questionIds: data.questions.map(question => question.id).sort(), roundIds: data.rounds.map(round => round.id).sort() };
  // The original complete snapshot/backup preflight must pass before the intentionally absent native storage boundary.
  const store = createResearchWorkflowStore();
  await assert.rejects(store.importBackup(JSON.stringify({ schemaVersion: RESEARCH_BACKUP_SCHEMA, exportedAt: new Date().toISOString(), data, manifest }), 'fixture-preflight'), error => error.code === 'UNAVAILABLE');
  const bad = structuredClone(fixture);
  bad.rounds[0].createdAt = materials[0].capturedAt - 1;
  assert.throws(() => validateResearchChains(bad.questions, bad.rounds));
});
