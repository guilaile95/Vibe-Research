import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { platformSettingsApi, type PlatformSettings } from "@/lib/platformSettings";

export function PlatformSettingsCard() {
  const operation = useRef(false);
  const generation = useRef(0);
  const alive = useRef(true);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    alive.current = true;
    const owner = ++generation.current;
    void platformSettingsApi.read().then(value => { if (alive.current && generation.current === owner) { setSettings(value); setReady(true); } }).catch(() => { if (alive.current && generation.current === owner) setMessage("读取设置失败，请重新读取；未使用默认值覆盖设置"); });
    return () => { alive.current = false; ++generation.current; };
  }, []);
  async function refresh() {
    if (operation.current) return;
    operation.current = true;
    const owner = ++generation.current;
    setBusy(true); setReady(false);
    try { const value = await platformSettingsApi.read(); if (!alive.current || generation.current !== owner) return; setSettings(value); setReady(true); setMessage("已重新读取当前状态；输入草稿保留。读取状态不能确认先前草稿已保存"); }
    catch { if (alive.current && generation.current === owner) setMessage("读取设置失败；草稿保留"); }
    finally { operation.current = false; if (alive.current && generation.current === owner) setBusy(false); }
  }
  async function save() {
    if (!ready || operation.current || !dirty || !settings?.sec_contact.editable) return;
    operation.current = true;
    const owner = ++generation.current;
    setBusy(true);
    try {
      const saved = await platformSettingsApi.save(draft, settings.sec_contact.revision);
      const latest = await platformSettingsApi.read();
      if (!alive.current || generation.current !== owner) return;
      if (saved.revision !== latest.sec_contact.revision || saved.revision === settings.sec_contact.revision || saved.configured !== Boolean(draft.trim()) || latest.sec_contact.configured !== saved.configured) throw new Error("未确认");
      setSettings(latest); setDirty(false); setDraft(""); setMessage("本地设置已保存并回读确认；未向 SEC 发送，也未启用取数");
    } catch { if (!alive.current || generation.current !== owner) return; setReady(false); setMessage("保存未确认（可能已写入），草稿保留；请重新读取后再决定是否保存"); }
    finally { operation.current = false; if (alive.current && generation.current === owner) setBusy(false); }
  }
  async function check() {
    if (operation.current || !ready || !settings?.can_check_update) return;
    operation.current = true;
    const owner = ++generation.current;
    setBusy(true);
    try { const update = await platformSettingsApi.check(); if (!alive.current || generation.current !== owner) return; setSettings(value => value ? { ...value, update } : value); setMessage(""); }
    catch { if (!alive.current || generation.current !== owner) return; setSettings(value => value ? { ...value, update: { ...value.update, status: "unavailable", checked_at: null, latest: null } } : value); setMessage("更新检查未确认，请重试；不能据此判断已是最新"); }
    finally { operation.current = false; if (alive.current && generation.current === owner) setBusy(false); }
  }
  const statusText = { not_checked: "尚未检查", unavailable: "检查失败或响应未通过验证", release_not_found: "未取得正式版本（可能无发布或仓库暂不可访问）", current_unknown: "当前版本未知，无法比较", update_available: "有新的正式版本", current: "与最新正式版本号相同", ahead: "当前版本号高于最新正式版本" };
  return <GlassCard className="mb-4" data-testid="platform-settings-card">
    <h3 className="text-sm font-semibold">公开数据身份与软件更新</h3>
    <p className="mt-2 text-xs text-muted-foreground">SEC 联系方式用于未来明确请求 SEC 时的 User-Agent 身份标识。这里只在本机保存、校验格式；当前 SEC 取数未连接，不会发送联系方式。</p>
    <p className="mt-2 text-xs">联系方式：{!ready ? "状态未确认" : settings?.sec_contact.source === "environment" ? "由环境变量管理，页面不可修改" : settings?.sec_contact.configured ? "已配置（不显示姓名和邮箱）" : "未配置"}</p>
    <label className="mt-2 block text-xs" htmlFor="sec-contact-draft">新的英文姓名和邮箱（留空保存可清除）</label>
    <input id="sec-contact-draft" data-testid="sec-contact-draft" autoComplete="off" maxLength={200} value={draft} disabled={!ready || busy || !settings?.sec_contact.editable} onChange={event => { setDraft(event.target.value); setDirty(true); }} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" />
    <div className="mt-2 flex flex-wrap gap-3 text-xs">
      <button type="button" disabled={!ready || busy || !dirty || !settings?.sec_contact.editable} onClick={() => void save()}>保存联系方式</button>
      <button type="button" disabled={busy} onClick={() => void refresh()}>重新读取状态</button>
    </div>
    <p className="mt-4 text-xs">手动更新检查仅联系 GitHub 官方仓库 guilaile95/Vibe-Research；GitHub 可见请求 IP，不发送本地设置或联系方式。不自动下载、安装或运行软件。</p>
    <button type="button" className="mt-2 text-xs" disabled={!ready || busy || !settings?.can_check_update} onClick={() => void check()}>手动检查正式版本</button>
    <p className="mt-2 text-xs">{settings ? statusText[settings.update.status] : "更新状态未知"} · 当前版本：{settings?.update.current ?? "未知"}</p>
    {settings?.update.checked_at && <p className="mt-1 text-xs">检查时间（UTC）：{settings.update.checked_at}</p>}
    {settings?.update.latest && <p className="mt-1 text-xs">官方版本：{settings.update.latest.version} · 发布时间（UTC）：{settings.update.latest.published_at} · <a className="text-primary" href={settings.update.latest.url} target="_blank" rel="noreferrer noopener">查看官方发布说明</a></p>}
    <p className="mt-4 text-xs text-muted-foreground">沿用 Windows 启动器和 Linux 用户态部署入口；macOS 专用启动器未支持。此状态不证明当前设备完成安装或真实跨平台验收。端口、运行目录与访问安全仍由现有运行信息和部署配置管理。</p>
    {dirty && <p className="mt-2 text-xs">有未保存草稿</p>}
    {message && <p role="status" className="mt-2 text-xs">{message}</p>}
  </GlassCard>;
}
