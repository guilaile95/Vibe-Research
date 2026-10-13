export const reportPageReasons: Record<string, string> = {
  FILE_CHANGED: "文件版本已变化，请刷新资料列表并重建索引后重试",
  FILE_CHANGED_DURING_READ: "读取期间源文件变化，本次正文已丢弃",
  INDEX_SOURCE_MISMATCH: "索引与源文件版本不一致，请重新索引",
  NOT_INDEXED: "尚未索引", NO_INDEXED_PAGE_TEXT: "该页没有已提取的正文，可能为空页或图片页",
  NO_EXTRACTABLE_TEXT: "索引没有可提取的正文", PAGE_NUMBERS_UNAVAILABLE: "此资料没有可用的物理页码",
  EMPTY_OR_PLACEHOLDER_TEXT: "仅有空白或占位文本", PAGE_OUT_OF_RANGE: "超出报告页数",
  PAGE_BUDGET: "超过返回页数限制", CHAR_BUDGET: "超过总字符限制", CHAR_TRUNCATED: "正文已按字符预算截断",
  INDEXED_TEXT: "已返回该页全部索引文本", REPORT_NOT_SELECTED: "报告不在所选资料中",
  REPORT_NOT_FOUND: "报告不存在", INDEX_READ_FAILED: "正文索引读取失败",
  INDEX_EXTRACTION_FAILED: "正文提取失败", SOURCE_UNAVAILABLE: "源文件不可用",
};
