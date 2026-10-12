import { parseLocalReportOcrReceipt, parseLocalReportIdentity, parseLocalOcrCapability } from "@/lib/localReportOcr";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type MyReport } from "@/lib/api";

const uncertainWrites = new Set<string>();
const pendingSourceDigests = new Map<string, string>();

export function LocalReportOcr({ report, onIndexed }: { report: MyReport; onIndexed: () => Promise<unknown> }) {
  const identity = `${report.id}:${report.file_sha256 ?? "legacy"}`;
  const [open, setOpen] = useState(false);
  const [language, setLanguage] = useState<"eng" | "chi_sim+eng">("chi_sim+eng");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(() => uncertainWrites.has(identity));
  const [message, setMessage] = useState("");
  const [capability, setCapability] = useState<{ image: boolean; pdf: boolean; chinese_language_status: string } | null>(null);
  const [capabilityError, setCapabilityError] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const expectedDigest = useRef(pendingSourceDigests.get(identity) ?? report.file_sha256);
  useEffect(() => {
    controller.current = null;
    setBusy(false); setMessage("");
    expectedDigest.current = pendingSourceDigests.get(identity) ?? report.file_sha256;
    setUncertain(uncertainWrites.has(identity));
    return () => {
      generation.current++;
      if (controller.current) uncertainWrites.add(identity);
      controller.current?.abort(); controller.current = null;
    };
  }, [identity]);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController(); let active = true;
    setCapability(null); setCapabilityError(false);
    api.localOcrCapability(abort.signal).then(value => {
      if (!active) return;
      setCapability(parseLocalOcrCapability(value));
    }).catch(() => { if (active) setCapabilityError(true); });
    return () => { active = false; abort.abort(); };
  }, [open, identity]);
  const available = capability && (report.ext === ".pdf" ? capability.pdf : capability.image)
    && (language === "eng" || capability.chinese_language_status === "INSTALLED_QUALITY_NOT_VERIFIED");
  if (![".pdf", ".png", ".jpg", ".jpeg"].includes(report.ext)) return null;
  const cancel = () => { generation.current++; controller.current?.abort(); controller.current = null; setBusy(false); uncertainWrites.add(identity); setUncertain(true); setMessage("已请求取消；未完成结果不会保存。如已完成需重新读取索引核对后再操作"); };
  async function run() {
    if (controller.current || uncertain || !available) return;
    const abort = new AbortController(); controller.current = abort;
    const current = ++generation.current;
    uncertainWrites.add(identity);
    setBusy(true); setMessage("");
    try {
      const digest = report.file_sha256 || parseLocalReportIdentity(await api.ocrReportIdentity(report.id, abort.signal), report.id, report.ext);
      if (generation.current !== current) return;
      if (!/^[0-9a-f]{64}$/.test(digest)) throw new Error("OCR 原文件摘要无效");
      expectedDigest.current = digest; pendingSourceDigests.set(identity, digest);
      const raw = await api.ocrMyReport(report.id, digest, language, abort.signal);
      const result = parseLocalReportOcrReceipt(raw, report.id, digest, language);
      if (generation.current !== current) return;
      uncertainWrites.delete(identity); pendingSourceDigests.delete(identity);
      controller.current = null; setBusy(false);
      setMessage(`已保存 ${result.extraction.pages.length} 页本机 OCR 索引，原文件未修改。识别文字可能出错，引用前请核对原页。`);
      await onIndexed();
    } catch (error) {
      if (generation.current !== current) return;
      setUncertain(true);
      setMessage(error instanceof ApiError ? `${error.message}。仅支持具备资源限制的 Linux 后端及已安装的 Tesseract / Poppler；中文需要 chi_sim。Windows / macOS 尚不支持此受限执行器。` : "OCR 回执无法核验，请重新读取索引状态；不要直接重复识别");
    } finally {
      if (generation.current === current) { controller.current = null; setBusy(false); }
    }
  }
  return <div className="mt-2 text-xs" data-testid="local-report-ocr">
    <button type="button" onClick={() => { if (open) { if (controller.current) cancel(); else { generation.current++; setBusy(false); } } setOpen(!open); }} className="rounded border px-2 py-1">{open ? "收起 OCR" : "本机 OCR"}</button>
    {open && <div className="mt-2 space-y-2 rounded border border-border/50 p-2">
      <p>处理位置是当前 Vibe 后端：通过此应用的 /api 连接。若 Vibe 部署在远端，识别就在远端后端机器执行，不在浏览器设备执行。</p>
      <p>仅支持 Linux 受限执行器；只在当前 Vibe 后端机器运行 Tesseract / Poppler，不上传模型或其他服务。原文件保持不变，成功后替换本地正文索引；最多 8MiB / 12 页 / 90 秒。OCR 不代表事实核验。</p>
      {!capability && <p>{capabilityError ? "本机 OCR 能力无法核验，请收起后重试" : "检查本机识别与语言能力…"}</p>}
      {capability && !(report.ext === ".pdf" ? capability.pdf : capability.image) && <p>当前后端的受限 OCR 执行器或本机依赖不可用；不会改用远程服务。</p>}
      {capability?.chinese_language_status === "CHINESE_LANGUAGE_UNAVAILABLE" && <p className="text-warning">CHINESE_LANGUAGE_UNAVAILABLE：本机缺少简体中文 chi_sim 语言包，无法识别中文研报。不会自动改用英文；英文选项只适合英文资料。</p>}
      {capability?.chinese_language_status === "INSTALLED_QUALITY_NOT_VERIFIED" && <p>已检测到中文语言包；识别质量未核验，请逐页核对原文。</p>}
      <p className="break-all">源 SHA256：{report.file_sha256 || "旧档案缺失；确认时只读计算并绑定原文件版本"}</p>
      <label>识别语言 <select aria-label={`OCR 语言 ${report.id}`} value={language} disabled={busy} onChange={e => setLanguage(e.target.value as typeof language)} className="rounded border bg-background p-1">
        <option value="chi_sim+eng">中文 + 英文（需 chi_sim）</option><option value="eng">英文</option>
      </select></label>
      <div className="flex flex-wrap gap-2"><button type="button" onClick={run} disabled={busy || uncertain || !available} className="rounded border px-2 py-1 disabled:opacity-50">{busy ? "本机识别中…" : "确认本机识别并建立索引"}</button>
        {busy && <button type="button" onClick={cancel} className="rounded border px-2 py-1">取消 OCR</button>}</div>
      {uncertain && <button type="button" disabled={busy} onClick={async () => {
        const readGeneration = ++generation.current;
        setBusy(true);
        try {
          const digest = parseLocalReportIdentity(await api.ocrReportIdentity(report.id), report.id, report.ext);
          if (readGeneration !== generation.current) return;
          if (expectedDigest.current && digest !== expectedDigest.current) throw new Error("原文件已变化");
          const current = await api.myReports();
          if (readGeneration !== generation.current) return;
          const entry = current.find(item => item.id === report.id);
          if (!entry || (entry.file_sha256 ? entry.file_sha256 !== digest : Boolean(report.file_sha256)) || !["SEARCHABLE", "NOT_INDEXED", "OCR_REQUIRED", "ARCHIVED_NOT_SEARCHABLE", "INDEX_ERROR"].includes(entry.text_index_status ?? "")) throw new Error("资料版本已变化，请刷新列表");
          uncertainWrites.delete(identity); pendingSourceDigests.delete(identity); expectedDigest.current = digest; setUncertain(false); setMessage(entry.text_index_error === "LOCAL_OCR_UNVERIFIED" ? "已重新读取：当前索引为未核验 OCR" : "已重新读取当前索引，可再次明确操作");
        } catch { if (readGeneration === generation.current) setMessage("索引状态仍不确定，请刷新列表核对；暂不重复识别"); }
        finally { if (readGeneration === generation.current) setBusy(false); }
      }} className="rounded border px-2 py-1">重新读取索引状态</button>}
      {message && <p role="status" className="break-words">{message}</p>}
    </div>}
  </div>;
}
