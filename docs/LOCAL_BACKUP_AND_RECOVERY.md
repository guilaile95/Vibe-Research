# 本地备份与恢复

## 边界

完整数据包覆盖已声明的 Vibe 本地持久化位置，不是整机备份。

归档是未加密 ZIP，可能包含持仓、交易、研究和账户相关私人数据。SHA-256 用于检查归档内部完整性，不提供加密或外部数字签名。归档必须保存在受保护的私人位置，不得提交到 Git。

浏览器 localStorage 不在数据包中，包括 `vr-notes`、`vr-askai-chat:*`、`vr-llm` 和 `vr-access-key`。Cookie、Token、密码和浏览器 Profile 也不会被扫描。

### 浏览器中的研究记录

“研究记录”页面提供独立的“导出备份 / 导入备份”功能，用于保护 `vr-notes`：

- 导出文件只包含研究记录，不包含 `vr-llm`、`vr-access-key`、`vr-askai-chat:*` 或其他凭据与对话；
- 导入采用合并模式，已有相同记录 ID 的内容不会被覆盖；
- 研究记录最多保留 200 条，超过上限的较旧导入记录会被跳过；
- 已有 200 条时，新建保存会明确提示先导出备份并手动清理，不自动删除最旧记录；
- 该 JSON 文件不属于 `vibe_data_backup` 生成的完整数据包，换设备或清理浏览器 Profile 前需要单独导出并妥善保存。

模型密钥和后端访问密钥有意保持在普通备份边界外；不要把它们手工加入研究记录备份。

## 创建完整数据包

必须先通过启动窗口的 `Ctrl+C` 正常关闭 Vibe，并等待前后端退出。备份工具不会停止进程；端口、进程或源文件状态无法证明静默时，会返回：

```text
BACKUP_REFUSED_ACTIVE_OR_UNCERTAIN_WRITER
```

Windows 先启动 PowerShell 7：

```text
pwsh.exe -NoLogo -NoProfile
```

以下命令必须从仓库的 `backend` 目录执行。把示例仓库路径和备份目录替换为本机实际位置：

```powershell
Set-Location 'C:\path\to\Vibe-Research\backend'
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path

# 目录必须已经存在，并且位于所有被备份的数据根目录之外。
$BackupDir = 'D:\Private\VibeBackups'
$Archive = Join-Path $BackupDir (
    'vibe-full-{0}.zip' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
)

& $Python -m vibe_data_backup snapshot --output $Archive
if ($LASTEXITCODE -ne 0) {
    throw 'Vibe snapshot failed; do not treat the archive as a recovery point.'
}
```

输出文件不得已经存在；工具不会覆盖 archive，也不会创建其父目录。archive 不得放在任何被备份的数据目录内。

## 验证 archive

```powershell
& $Python -m vibe_data_backup verify --archive $Archive
if ($LASTEXITCODE -ne 0) {
    throw 'Vibe archive verification failed.'
}
```

只有退出码为 `0` 且 JSON 输出的 `status` 为 `OK`，才能继续恢复演练。`verify` 检查归档结构、逻辑资产白名单、manifest 和文件 SHA-256；它不代替 SQLite `quick_check`，也不验证业务内容是否正确。

## 恢复到临时 staging

恢复只能进入新建的临时 staging 路径。不要把正式 `VR_DATA_DIR`、reports、Fact Lake 或任何正式数据库路径作为 `--target`，也不要用 restore 直接覆盖正式文件。

```powershell
$Staging = Join-Path $env:TEMP (
    'vibe-restore-drill-{0}' -f [guid]::NewGuid().ToString('N')
)

if (Test-Path -LiteralPath $Staging) {
    throw 'Staging path must not already exist.'
}

& $Python -m vibe_data_backup restore --archive $Archive --target $Staging
if ($LASTEXITCODE -ne 0) {
    throw 'Vibe restore drill failed; staging may contain partial output.'
}
```

`restore` 只接受不存在或为空的目标，先完整验证 archive，再写入 staging。执行中发生磁盘或权限错误时，staging 可能留下部分文件；工具不会自动删除它们。不要把这种目录当成成功恢复点，应换一个新的空 staging 路径重试。

## SQLite quick_check

以下检查只读取 staging 中扩展名为 `.db`、`.sqlite` 或 `.sqlite3` 的数据库；不导入 Vibe 业务模块，也不输出表内容：

```powershell
@'
from pathlib import Path
import sqlite3
import sys

root = Path(sys.argv[1]).resolve()
databases = sorted(
    path
    for path in root.rglob("*")
    if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
)
failed = []

for path in databases:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("PRAGMA quick_check").fetchall()
    finally:
        connection.close()

    status = "ok" if rows == [("ok",)] else "FAILED"
    print(f"{path.relative_to(root)} = {status}")
    if status != "ok":
        failed.append(path)

raise SystemExit(1 if failed else 0)
'@ | & $Python - $Staging

if ($LASTEXITCODE -ne 0) {
    throw 'At least one restored SQLite database failed quick_check.'
}
```

成功恢复和 `quick_check=ok` 只证明 staging 副本通过相应结构检查，不证明业务内容正确、备份足够新或已经完成正式切换。

## 逻辑分区

| staging 分区 | 对应资产 |
| --- | --- |
| `data/` | `VR_DATA_DIR`；未设置时为 `%USERPROFILE%\.vibe-research` |
| `shared-review/` | shared daily-review DB 及归档时存在的 SQLite sidecar |
| `reports/` | `VR_REPORTS_DIR` 或现有默认 reports 目录 |
| `fact-lake/` | 已配置且存在的 `VR_FACT_LAKE_ROOT` |
| `research-data/` | `VIBE_RESEARCH_RESEARCH_DATA_DIR`；默认来源为 data root 下的 `research_data_plane` |
| `external-db/` | 位于 data root 外的已配置 `VIBE_RESEARCH_*_DB` / `VIBE_NATIVE_INTEL_DB` |

manifest 使用逻辑相对路径，不记录源机器绝对路径。资产状态含义：

- `PRESENT`：使用默认位置或位于 data root 内；
- `EXTERNAL_OVERRIDE_INCLUDED`：显式配置且位于 data root 外；
- `ABSENT_OPTIONAL`：可选资产不存在，因此未归档。

把 staging 数据重新放回正式位置是独立的人工恢复操作。必须保持 Vibe 关闭，重新核对目标路径和环境变量；本工具不会迁移、合并或安全覆盖现有正式目录。


## Research Data Plane：恢复后仍能重放吗

完整数据包会递归收集已声明的 Research Data Plane 目录；具体 staging 位置应按
归档 manifest 中 `research_data_plane` 资产的 `archive_prefix` 核对，通常为
`research-data/`，与其他资产共用根目录时可能使用其分区。不要猜测源机器的绝对路径。

[固定数据代际与重放回执](research/RDP_SNAPSHOT_REPLAY_20261009.md) 依赖
`snapshots/` 中的不可变元数据和 `artifacts/` 中对应的 Parquet 文件。
只保存 `manifest.json`、截图或 `replay_receipt` 都不能备份历史数据；归档早于该代际时，
也不能靠回执补出缺失文件。保存回执时需保留原查询参数，并妥善保护其中的研究信息。

恢复演练仍只针对 staging，保持正式服务关闭，不覆盖正式目录：

1. 完成本页的 archive 验证和 staging 恢复，核对该资产不是 `ABSENT_OPTIONAL`
2. 使用保存回执对应的同一种查询，以 staging 内的 RDP 分区作为显式 `root`，
   传入保存的 `snapshot_id` 和原有效查询参数；不要省略 ID 后改查当前代际
3. 在相同引擎合同和依赖环境下比较返回的 `replay_receipt`；分页回执仅覆盖原有
   页大小、offset 与筛选条件，不是整个数据集的校验结果
4. 未找到代际、文件损坏或回执不一致时保留失败结果，停止正式切换，不回退成“最新数据重放成功”

已归档的 pinned 查询不需要当前 `manifest.json`，也不会创建新归档。
旧数据的无 ID 当前读取则可能触发归档，因此不能把它当作无副作用的恢复核验。
ZIP SHA-256、SQLite `quick_check` 与 RDP 重放分别验证不同层次；
即便全部通过，也不证明历史时点的公开可得性、来源许可或投资结论。
