import { reportPageReasons } from "@/lib/reportPageLabels";
import type { ReportPageContextMeta } from "@/lib/api/types";

const labels = { readable: "纳入上下文", omitted: "预算省略", invalid: "无效页", unreadable: "正文不可用", error: "读取失败" };
export function ReportPageContextView({ value }: { value: ReportPageContextMeta }) {
  const truncated = value.items.filter(item => item.truncated);
  const missing = value.items.filter(item => item.status !== "readable");
  return <div data-testid="chat-page-coverage" className="mb-2 space-y-1">
    <p className="font-medium">指定页上下文 · 第 {value.page_from}–{value.page_to} 页</p>
    <p>请求 {value.requested.length} 页 · 纳入 {value.coverage.readable.length} 页 · {value.returned_chars} 个 Unicode 字符</p>
    <p>{Object.entries(value.coverage).map(([status, pages]) => `${labels[status as keyof typeof labels]} ${pages.length} 页`).join(" · ")}</p>
    <p>页内截断：{truncated.length ? `有（${truncated.map(item => `第 ${item.page} 页 ${item.returned_chars}/${item.indexed_chars} 字符`).join("；")}）` : "无"}</p>
    <p>只代表提供了这些索引文本，不保证模型关注全部内容；未请求页未纳入，不代表读取了报告全文或已验证结论。</p>
    <p className="break-all">report_id={value.report_id} · 当时来源 SHA256：{value.expected_file_sha256}</p>
    <p>历史回答保留当时版本；再次提问会重新校验来源，文件变化时须重新选择。</p>
    {missing.length > 0 && <details><summary className="cursor-pointer">未纳入 {missing.length} 页 · 查看范围</summary>
      {missing.map(item => <p key={item.page}>第 {item.page} 页：{labels[item.status]}（{reportPageReasons[item.reason] ?? "未提供该页正文"}）</p>)}
    </details>}
  </div>;
}
