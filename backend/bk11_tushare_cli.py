"""BK-11 Tushare ingestion CLI（显式生产入口，v0.2）。

用法：

    python -m bk11_tushare_cli ingest --trade-date YYYY-MM-DD

约束：

- Token 只从环境变量 ``TUSHARE_TOKEN`` 读取（不接受 --token）；
- 不接受 --db-path / --source-url / --force / 日期范围；
- 每次只处理一个交易日，必须显式传入；
- 输出结构化 JSON，不含 Token / URL / 路径 / 原始响应行；
- exit code：0 成功；2 参数错误；10 凭据缺失；11 权限不足；
  12 来源不可用；13 合同失败；14 存储失败。
"""

from __future__ import annotations

import argparse
import json
import sys

import bk11_tushare_ingestion_service as service
import tushare_pro_client as tpc

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CREDENTIAL_MISSING = 10
EXIT_PERMISSION_DENIED = 11
EXIT_SOURCE_UNAVAILABLE = 12
EXIT_CONTRACT_FAILED = 13
EXIT_STORAGE_FAILED = 14
EXIT_ERROR = 15


def _exit_code_for(reason_code: str | None) -> int:
    if reason_code == "DEDUPED":
        return EXIT_OK
    if reason_code == "CREDENTIAL_MISSING":
        return EXIT_CREDENTIAL_MISSING
    if reason_code == "PERMISSION_DENIED":
        return EXIT_PERMISSION_DENIED
    if reason_code == "SOURCE_UNAVAILABLE":
        return EXIT_SOURCE_UNAVAILABLE
    if reason_code == "CONTRACT_FAILED" or reason_code == "ENVELOPE_VALIDATION_FAILED":
        return EXIT_CONTRACT_FAILED
    if reason_code in ("STORAGE_FAILED", "NORMAL_CONFLICT",
                       "PARTIAL_CONFLICT", "SCHEMA_CONFLICT_V01"):
        return EXIT_STORAGE_FAILED
    return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bk11_tushare_cli",
        description="BK-11 Tushare 生产 ingestion（显式单交易日）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="执行单交易日 ingestion")
    ingest.add_argument(
        "--trade-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="目标交易日（必须为离线日历中已确认结束的交易日）",
    )
    args = parser.parse_args(argv)
    if args.command != "ingest":
        parser.error("仅支持 ingest 命令")

    try:
        result = service.ingest_trade_date(args.trade_date)
    except (tpc.TushareCredentialMissing,):
        result = {
            "schema_version": service.SCHEMA_VERSION,
            "action": "ingest",
            "trade_date": args.trade_date,
            "status": "error",
            "saved": False,
            "deduped": False,
            "upgraded": False,
            "blocked": True,
            "reason_code": "CREDENTIAL_MISSING",
            "limitations": ["TUSHARE_TOKEN 未配置"],
            "snapshot": None,
        }
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception:
        result = {
            "schema_version": service.SCHEMA_VERSION,
            "action": "ingest",
            "trade_date": args.trade_date,
            "status": "error",
            "saved": False,
            "deduped": False,
            "upgraded": False,
            "blocked": True,
            "reason_code": "INTERNAL_ERROR",
            "limitations": ["ingestion 内部错误"],
            "snapshot": None,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return _exit_code_for(result.get("reason_code")) if not result.get("saved") \
        else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
