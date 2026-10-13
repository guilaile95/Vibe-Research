import { request } from "./api";

export const RELEASE_REPOSITORY = "guilaile95/Vibe-Research";
export type ContactStatus = { source: "environment" | "saved" | "none"; configured: boolean; revision: string; editable: boolean };
export type UpdateStatus = { repository: string; current: string; mode: "manual_only"; status: "not_checked" | "unavailable" | "release_not_found" | "current_unknown" | "update_available" | "current" | "ahead"; checked_at: string | null; latest: { version: string; url: string; published_at: string } | null };
export type PlatformSettings = { schema: "platform_settings.v1"; sec_contact: ContactStatus; update: UpdateStatus; platforms: { windows: "existing_launcher"; linux: "existing_user_space_launcher"; macos: "unsupported_launcher" }; sec_provider: "not_connected"; can_check_update: boolean };
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("响应未确认");
  return value as Record<string, unknown>;
};
const validDate = (value: unknown) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().replace(".000Z", "Z") === value;
const semverPattern = /^(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})$/;
const semver = (value: string) => value === value.trim() && semverPattern.test(value);
export function parseContact(value: unknown): ContactStatus {
  const v = object(value);
  if (!["environment", "saved", "none"].includes(v.source as string) || typeof v.configured !== "boolean" || typeof v.editable !== "boolean" || typeof v.revision !== "string" || v.revision !== v.revision.trim() || !/^(?:absent|environment|[a-f0-9]{32})$/.test(v.revision)
    || (v.source === "environment" && (v.revision !== "environment" || v.editable)) || (v.source !== "environment" && v.revision === "environment") || (v.source === "saved" && (!v.configured || v.revision === "absent")) || (v.source === "none" && v.configured)) throw new Error("响应未确认");
  return { source: v.source as ContactStatus["source"], configured: v.configured, revision: v.revision, editable: v.editable };
}
export function parseUpdate(value: unknown): UpdateStatus {
  const v = object(value);
  const statuses = ["not_checked", "unavailable", "release_not_found", "current_unknown", "update_available", "current", "ahead"];
  if (v.repository !== RELEASE_REPOSITORY || v.mode !== "manual_only" || typeof v.current !== "string" || !(semver(v.current) || v.current === "unknown") || !statuses.includes(v.status as string) || (v.checked_at !== null && (!validDate(v.checked_at) || Date.parse(v.checked_at as string) > Date.now() + 60000))) throw new Error("响应未确认");
  if ((v.status === "not_checked") !== (v.checked_at === null)) throw new Error("响应未确认");
  let latest: UpdateStatus["latest"] = null;
  if (v.latest !== null) {
    const l = object(v.latest);
    if (typeof l.version !== "string" || !semver(l.version) || typeof l.url !== "string" || ![`https://github.com/${RELEASE_REPOSITORY}/releases/tag/${l.version}`, `https://github.com/${RELEASE_REPOSITORY}/releases/tag/v${l.version}`].includes(l.url) || !validDate(l.published_at) || Date.parse(l.published_at as string) > Date.parse(v.checked_at as string)) throw new Error("响应未确认");
    latest = { version: l.version, url: l.url, published_at: l.published_at as string };
  }
  if (["current_unknown", "update_available", "current", "ahead"].includes(v.status as string) !== Boolean(latest)) throw new Error("响应未确认");
  if (latest) {
    const a = latest.version.split(".").map(Number), b = v.current.split(".").map(Number);
    const cmp = a.findIndex((n, i) => n !== b[i]);
    const expected = v.current === "unknown" ? "current_unknown" : cmp < 0 ? "current" : a[cmp] > b[cmp] ? "update_available" : "ahead";
    if (v.status !== expected) throw new Error("响应未确认");
  }
  return { repository: RELEASE_REPOSITORY, current: v.current, mode: "manual_only", status: v.status as UpdateStatus["status"], checked_at: v.checked_at as string | null, latest };
}
export function parsePlatformSettings(value: unknown): PlatformSettings {
  const v = object(value), p = object(v.platforms);
  if (v.schema !== "platform_settings.v1" || v.sec_provider !== "not_connected" || typeof v.can_check_update !== "boolean" || p.windows !== "existing_launcher" || p.linux !== "existing_user_space_launcher" || p.macos !== "unsupported_launcher") throw new Error("响应未确认");
  return { schema: "platform_settings.v1", sec_contact: parseContact(v.sec_contact), update: parseUpdate(v.update), platforms: { windows: "existing_launcher", linux: "existing_user_space_launcher", macos: "unsupported_launcher" }, sec_provider: "not_connected", can_check_update: v.can_check_update };
}
export const platformSettingsApi = {
  read: async () => parsePlatformSettings(await request<unknown>("/settings/platform", "GET", undefined, { signal: AbortSignal.timeout(10000) })),
  save: async (contact: string, revision: string) => parseContact(await request<unknown>("/settings/platform/sec-contact", "PUT", { contact, revision }, { signal: AbortSignal.timeout(10000) })),
  check: async () => parseUpdate(await request<unknown>("/settings/platform/check-update", "POST", undefined, { signal: AbortSignal.timeout(15000) })),
};
