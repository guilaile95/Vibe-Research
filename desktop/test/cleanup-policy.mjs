// Pure policy: these functions never execute commands or mutate files themselves.
export function uncertainProcessFailure(error) {
  return !Number.isInteger(error?.status) || error.status === 125 || !!error.signal || error.code === 'ENOBUFS';
}
export async function cleanupInOrder(actions, isUncertain) {
  const errors = [];
  for (const action of actions) {
    if (isUncertain()) return { errors, uncertain: true };
    try { await action(); } catch (error) { errors.push(error); }
    if (isUncertain()) return { errors, uncertain: true };
  }
  return { errors, uncertain: isUncertain() };
}
