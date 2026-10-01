# 独立桌面版（Linux / Windows）

桌面版使用真正的 Electron 应用窗口，安装包包含前端、Python 后端、Node 与 Codex 本地运行时。
使用者不需要自行安装 Python、Node、npm、Git、PowerShell 7，也不需要启动终端或打开 localhost 网页。
原来的 Web / 源码启动入口保持可用。

## 目标平台与安装

当前打包目标是 **x64**：

- Linux：Ubuntu 22.04+ 桌面系统是构建基线；提供 `.deb` 和 `.tar.gz`。其他发行版需具备兼容的 glibc、GTK/NSS/音频等 Electron 系统库，不能把一个 Linux 构建视为所有发行版都已验证
- Windows：Windows 10/11 x64；提供按用户安装的 NSIS `.exe`，可选择安装目录
- ARM、32 位、macOS 暂不提供构建产物

Linux 推荐通过软件安装器打开 `.deb`，或 `sudo apt install ./Vibe-Research-版本-linux-amd64.deb`。
安装器会检查系统库；缺少系统依赖时仍需要系统软件源或事先准备好的离线依赖。
压缩包需完整解压后运行 `vibe-research`，不能只移动其中单个可执行文件。
安装 `.deb` 后可从系统应用菜单打开 Vibe Research；压缩包版从解压目录启动。

Windows 双击安装包，按向导安装，然后从开始菜单或桌面快捷方式打开。
当前安装包**未做商业代码签名**，Windows 可能显示发布者未知或信誉提示；请先核实来源和校验和，遵循本机组织策略。
本项目不要求关闭系统防护，也不提供绕过提示的自动操作。

Linux 必须以普通桌面用户运行，保留 Chromium 沙箱。若系统限制用户命名空间/沙箱，
请使用受支持的系统安装方式或由管理员检查兼容性；不要添加关闭沙箱的启动参数。
本版本未提供 AppImage，以免依赖会注入关闭沙箱参数的启动包装器。

## 离线与在线边界

安装包完整包含应用运行时，首次启动不会执行 pip/npm 安装。
本地记录和已保存的数据可以离线访问。实时行情、新闻、外部研报、模型 API 和 Codex 登录/推理需要网络，
以及用户自己的相应账户或配置；安装包不包含账户、模型密钥或预登录状态。

桌面版自动启动本机服务。关闭最后一个窗口会停止它拥有的服务进程，重复启动只会聚焦已有窗口。
启动失败会显示原生错误提示并清理已启动的服务，不扫描/终止其他应用占用的端口。

## 数据与升级

桌面版专用数据根目录：

- Linux：`${XDG_CONFIG_HOME:-~/.config}/Vibe Research/`
- Windows：`%APPDATA%\Vibe Research\`

`research-data/` 保存后端数据、研报、缓存和隔离的 Codex 认证目录；浏览器持久化状态也在同一应用目录下。
Linux 数据目录使用仅当前用户可访问的权限；Windows 使用当前用户 AppData 的继承权限。
密钥和私人资料不进入安装目录或发行包。当前版本没有系统钥匙串加密承诺，请保护操作系统账户及备份。

桌面浏览器存储与原来的 Chrome/Firefox/Web 入口分开，**不会自动迁移旧 localStorage 或 `~/.vibe-research`**。
如需迁移，请在原入口使用现有备份/导出功能，再在桌面入口手动导入；先保留原始备份，确认恢复范围。
安装升级不删除用户数据，Windows 卸载也默认保留用户数据。没有自动升级/自动同步。
高级隔离测试可用 `--user-data-dir=/绝对路径` 启动一个独立配置目录，不应指向已有无关应用目录。

## 构建与验证（开发者）

必须在对应的原生操作系统分别构建；不把 Linux Python/二进制复制成 Windows 发行包。
构建机需要 Git、Node 24.19.0、npm、Linux Python 3.11 或 Windows Python 3.12，并能访问官方依赖源。
构建阶段需要联网下载锁定依赖，与最终用户安装阶段不同。

```sh
cd desktop
npm ci
npm run install:electron
npm test
python -m unittest discover -s build -p "test_*.py"
node build/stage.mjs --python python
npm run dist
```

输出在 `desktop/release/`，不自动发布。Python staging 使用平台对应的现有 lock；
Electron、electron-builder 和 Playwright 使用 desktop/package-lock.json；Node 复制构建机的指定版本。
构建输入只采集受版本控制的白名单，拒绝敏感路径/符号链接，并使用隔离的前端构建环境，不读取 `.env`。

`.github/workflows/desktop.yml` 在 Linux 和 Windows 原生 runner 分别执行：

1. 无 UI 的协议、数据隔离、鉴权和进程生命周期测试
2. 平台原生 Python/Node/前端打包、离线依赖自检（含 NumPy 运算和内存 DuckDB）与安装文件生成
3. **解包后桌面可执行文件**的真实窗口 fixture smoke：沙箱、页面装载/刷新、私有 API 桥、单实例、
   localStorage 持久化、正常退出和主进程崩溃后的服务清理

窗口 smoke 使用独立临时配置、禁用后台提供商抓取/调度，并拦截页面数据 API；不调用真实模型。
它证明打包窗口与基础运行时契约，不等同于完整真实用户业务验收，也不等同于安装向导的人工验收。
`.deb` / NSIS 实际安装、卸载、升级及更广泛发行版/显示服务器组合仍需在相应目标机器验证。
窗口测试应在受支持的原生桌面或对应操作系统 CI runner 上运行。

技术参考：[Electron 安全](https://www.electronjs.org/docs/latest/tutorial/security)、
[沙箱](https://www.electronjs.org/docs/latest/tutorial/sandbox)、
[electron-builder NSIS](https://www.electron.build/docs/nsis/)。
