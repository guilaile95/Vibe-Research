// P1-DF3：Review boundary 结构化输入的纯解析层（无 I/O、无 DOM、无时钟）。
// 只负责把用户在 datetime-local 控件里显式选择的时间转换成 canonical UTC ISO。
// 过去时间等业务校验仍由 backend Preview authority 负责，这里不复制规则；
// 也绝不使用 Date.now() 或 expected_horizon 生成任何默认值。

const BOUNDARY_LOCAL_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/;

export type ParsedReviewBoundary =
  | { status: "VALID"; date: Date; iso: string }
  | { status: "INVALID"; reason: string };

export function parseReviewBoundary(localValue: string): ParsedReviewBoundary {
  const trimmed = localValue.trim();
  if (!trimmed) return { status: "INVALID", reason: "尚未选择 review 时间" };
  if (!BOUNDARY_LOCAL_RE.test(trimmed)) return { status: "INVALID", reason: "时间不完整" };
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return { status: "INVALID", reason: "时间无法解析" };
  const [datePart, timePart] = trimmed.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute, secondRaw] = timePart.split(":").map(Number);
  const second = secondRaw ?? 0;
  // 浏览器会把 2026-02-30 静默滚到 3 月；逐分量比对不存在的时刻以 fail closed。
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
    || date.getHours() !== hour
    || date.getMinutes() !== minute
    || date.getSeconds() !== second
  ) {
    return { status: "INVALID", reason: "时间分量无效" };
  }
  return { status: "VALID", date, iso: date.toISOString() };
}

/** JS getTimezoneOffset()：UTC+8 → -480。 */
export function formatUtcOffsetMinutes(offsetMinutes: number): string {
  const sign = offsetMinutes <= 0 ? "+" : "-";
  const abs = Math.abs(offsetMinutes);
  const hours = String(Math.floor(abs / 60)).padStart(2, "0");
  const minutes = String(abs % 60).padStart(2, "0");
  return `UTC${sign}${hours}:${minutes}`;
}

export function browserTimeZoneName(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UNKNOWN";
  } catch {
    return "UNKNOWN";
  }
}
