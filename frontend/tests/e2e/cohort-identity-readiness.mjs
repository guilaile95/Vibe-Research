/** Network request admission precedes React's committed loading render. */
export async function waitForCohortLoading(card, table) {
  await card.getByText("正在读取两日名单…", { exact: true }).waitFor({ state: "visible", timeout: 10000 });
  await table.waitFor({ state: "detached", timeout: 10000 });
}

/** A visible table alone could still belong to the previous selected date. */
export async function waitForCohortMembers(card, table, day, previous) {
  await card.getByText(`前一交易日 ${previous} → 所选交易日 ${day}`, { exact: true })
    .waitFor({ state: "visible", timeout: 10000 });
  await table.waitFor({ state: "visible", timeout: 10000 });
}
