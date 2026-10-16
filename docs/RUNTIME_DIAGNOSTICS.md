# 脱敏运行自检

在应用「设置」→「本机后端运行信息」点击 **导出脱敏自检报告**，即可下载
`vibe-runtime-diagnostics.json`。使用已经保存的后端访问密钥鉴权；不会保存或修改当前设置草稿。
失败时先检查后端是否可连接、是否已保存正确的后端访问密钥，再重试。

此动作仅执行只读元数据检查，不启动服务、不请求数据源、不调用模型、不发起 Codex CLI 登录或状态探测。
报告没有环境变量值、凭据、账户资料、目录路径或原始错误。

## 如何读报告

- `startup`：复用 `/api/runtime-info` 的启动时软件版本、Git SHA 和源码状态。不是现在磁盘上最新源码的证明；`modified` 表示 SHA 只是提交基线，`unknown` 表示未取得证据
- `agent_runtime`：后端有效目标端口，以及后端进程环境中声明的 Runtime 端口与来源。`PORT_MISMATCH` 表示两者不同；`INVALID_CONFIGURATION` 表示格式不适用于本机 Runtime；`DYNAMIC_PORT_UNVERIFIED` 表示声明端口为 0，实际监听端口未知
- `PORTS_MATCH` 仅表示本进程所见配置一致，不证明另一个终端启动的 Runtime 使用相同环境或正在监听。`availability: NOT_EVALUATED` 不等于不可用，也不等于已连接
- `configuration_presence`：固定名单中的环境变量名是否存在，空值也算存在；不读取或验证密钥值
- `directories`：数据及研报目录是否存在、类型是否正确、操作系统权限检查是否通过。只读取目录元数据，不列出或读取目录内文件，不创建目录或执行试写；`ACCESS_CHECK_OK` 不保证后续真实写入成功，符号链接/联接本身不继续检查
- `source_capabilities`：内置能力、环境配置名存在和未检查的私有设置分开标记。所有实际源验证均为 `NOT_EVALUATED`；安装了代码或存在变量名不代表认证有效、数据源在线或响应满足业务契约

对端口不匹配，核对后端 `VR_AGENT_RUNTIME_URL` 与 Runtime 启动终端的
`VR_AGENT_RUNTIME_PORT`；两者默认端口为 8911。报告不自动改配置或重启服务。
若需要实际连接验证，在知晓该动作会访问服务后，另行使用现有 AI 连接检查或数据健康入口。

## API 合同

- `GET /api/runtime-diagnostics`：`{"data": ...}`，模式 `READ_ONLY_NO_PROBES`
- `GET /api/runtime-diagnostics/export`：同一脱敏数据，JSON 下载附件
- 两者复用现有私有 API 鉴权、Host/Origin 边界并返回 `Cache-Control: no-store`
- 原有 `/api/runtime-info` 保持兼容；它包含本机目录，仅本机查看，脱敏导出不复制这些字段

本功能不提供自动修复或实时可用性结论。导出的报告会包含软件版本、SHA、端口和配置名存在情况；分享前自行审阅。
