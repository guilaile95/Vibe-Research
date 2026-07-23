# Sector research browser acceptance

Date: 2026-07-23T21:23:54.377Z
Browser: local chromium-1228
Isolated VR_DATA_DIR used: yes
Isolated VR_REPORTS_DIR used: yes

## Transport
API transport: real reverse proxy
FastAPI routes: production routes
External IO: test harness stubs
Expired-cache case: harness-directed cache miss for ERR
Worktree files created/deleted: none
Harness load: PYTHONPATH=backend + frontend/tests/e2e; uvicorn harness_app:app (cwd=repo root)

## Covered
- 板块中心进入 PCB
- 板块中心进入 4 个 Batch 1 板块（人形机器人 / AI算力 / HBM / 光互联与CPO）
- 六个 Tag
- 动态数据展开与刷新
- 研报行业/公司/全部发现
- 自定义 days
- 截断数量提示
- 缓存导入与导入错误反馈（ERR 可见行 → harness 定向 miss → 生产 import 400 → 重新发现提示）
- 我的研报定位
- 按时间/产业/机构分类
- 元数据清空
- 前进后退与刷新恢复
- 桌面 1440px 与移动 390px 无整体横向滚动

## Screenshots
- desktop-pcb-overview.png
- desktop-report-discovery.png
- desktop-my-reports.png
- desktop-humanoid-overview.png
- desktop-ai-computing-overview.png
- desktop-hbm-overview.png
- desktop-cpo-overview.png
- mobile-pcb-overview-390.png
- mobile-report-discovery-390.png
- mobile-my-reports-390.png
- mobile-humanoid-overview-390.png
- mobile-ai-computing-overview-390.png
- mobile-hbm-overview-390.png
- mobile-cpo-overview-390.png

## Errors
- none
