import assert from 'node:assert/strict';
import test from 'node:test';
import { validateResearchChains } from '../src/lib/researchWorkflow.ts';
import { reportPageMaterials } from '../src/lib/researchCheck.ts';
import { resumeContextFixture, originalReport, researchCheckPageReadReply } from './e2e/research-check-loop.fixture.mjs';

test('resume fixture is a complete native-store snapshot after attaching real-shaped current material receipts', async () => {
  const materials = await reportPageMaterials(originalReport, researchCheckPageReadReply({ report_id: originalReport.id, selected_report_ids: [originalReport.id], expected_file_sha256: originalReport.file_sha256, page_from: 1, page_to: 1 }).data, '600519', 1, 1);
  const fixture = resumeContextFixture(Date.now() + 1);
  for (const round of fixture.rounds.filter(round => round.securityCode === '600519')) round.materials = materials;
  assert.doesNotThrow(() => validateResearchChains(fixture.questions, fixture.rounds));
  const bad = structuredClone(fixture);
  bad.rounds[0].createdAt = materials[0].capturedAt - 1;
  assert.throws(() => validateResearchChains(bad.questions, bad.rounds));
});
