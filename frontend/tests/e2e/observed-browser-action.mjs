/** Attach both rejection handlers immediately: a blocked click must not leave
 * its network observer unhandled and bypass the harness failure diagnostics. */
export async function observedBrowserAction(observe, action) {
  const response = observe();
  const [result] = await Promise.all([response, Promise.resolve().then(action)]);
  return result;
}
