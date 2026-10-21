export function parseTargets(text: string): Record<string, number> {
  const result: Record<string, number> = {};
  for (const line of text.split('\n').filter(x => x.trim())) {
    const parts = line.trim().split(/\s+/);
    if (parts.length !== 2 || !/^(CASH|[0368]\d{5})$/.test(parts[0]) || !/^\d+(\.\d{1,2})?$/.test(parts[1])) throw new Error('每行填写证券代码或 CASH，再填写百分比（最多两位小数）');
    if (Object.prototype.hasOwnProperty.call(result, parts[0])) throw new Error('目标代码不能重复');
    const weight = Number(parts[1]);
    if (weight > 100) throw new Error('目标百分比不能超过 100');
    result[parts[0]] = weight;
  }
  if (!Object.keys(result).length) throw new Error('请明确填写至少一个目标');
  return result;
}
