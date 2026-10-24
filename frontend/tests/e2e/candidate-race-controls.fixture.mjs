import assert from 'node:assert/strict';

// Shared by production-browser acceptance and the actual-component lifecycle
// harness. Parent traversal is deliberate: a has-filter scoped to the label must
// not start another search for the outer campaign panel inside that label.
export function candidateRaceLocators(panel) {
  const strategy = panel.getByRole('radio', { name: 'SWING · 波段', exact: true });
  return { strategy, label: strategy.locator('..'), create: panel.getByTestId('create-candidate-campaign') };
}

export async function selectCandidateRaceStrategy(panel) {
  await panel.getByText('暂无候选投资计划', { exact: true }).waitFor();
  const { create, strategy, label } = candidateRaceLocators(panel);
  assert.equal(await create.isDisabled(), true, 'creation requires an explicit strategy');
  assert.equal(await label.evaluate(element => element.tagName), 'LABEL');
  await label.click();
  assert.equal(await strategy.isChecked(), true);
  assert.equal(await create.isDisabled(), false);
}

export async function assertEmptyCandidateRace(panel, code) {
  assert.equal(await panel.getByText('暂无候选投资计划', { exact: true }).count(), 1);
  assert.doesNotMatch(await panel.innerText(), /Late synthetic create failure/);
  assert.equal(await panel.getAttribute('data-security-code'), code);
}
