// 安全的 localStorage 读写。
//
// 浏览器在隐私模式、嵌入式 WebView、禁用 cookie、或配额写满时，访问 localStorage
// 会**直接抛异常**（不是返回 null）。如果这个异常发生在组件初始化里，整个页面会白屏——
// 侧栏折叠状态、主题这类外壳级设置尤其致命：一崩就是全站打不开。
//
// 这里统一兜底：存不下就算了，本次会话内功能照常，只是关掉页面后不被记住。

export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存储不可用：本次会话仍可正常使用，只是不持久化 */
  }
}

export function storageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* 同上 */
  }
}

// User-visible save/delete operations must verify persistence instead of silently succeeding.
export function storageGetChecked(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    throw new Error("浏览器无法读取本地存储，请检查存储权限");
  }
}

export function storageSetChecked(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
    if (localStorage.getItem(key) !== value) throw new Error();
  } catch {
    throw new Error("浏览器无法保存数据，请检查存储权限或空间");
  }
}

export function storageRemoveChecked(key: string): void {
  try {
    localStorage.removeItem(key);
    if (localStorage.getItem(key) !== null) throw new Error();
  } catch {
    throw new Error("浏览器无法清除数据，请检查存储权限");
  }
}
