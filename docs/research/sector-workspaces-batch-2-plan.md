# Sector Research Workspaces Batch 2 Plan

## Candidate Sector Inventory

From sectors.json, 15 unbuilt sectors have tag plans in sectorTagPlans.ts:
1. semiconductor (半导体国产替代)
2. ai-hardware (AI 硬件)
3. business-space (商业航天)
4. low-altitude (低空经济)
5. smart-driving (智能驾驶)
6. solid-state-battery (固态电池)
7. energy-storage (储能)
8. power-grid (电网与特高压)
9. defense (军工)
10. fusion (可控核聚变)
11. resources (资源卡口)
12. innovative-drug (创新药)
13. ai-pharma (生物医药)
14. ai-application (AI 应用)
15. data-element (数据要素)

## Selected 4 Sectors

### 1. semiconductor (半导体国产替代)
- **Key**: semiconductor
- **Connection**: Directly complements AI computing (芯片), HBM (先进封装), PCB equipment flow
- **A-share Coverage**: Very strong — equipment (北方华创/中微), materials (沪硅/安集), EDA, manufacturing
- **Reliability**: Company filings from major A-share equipment and materials makers
- **Tags**: overview, process, value, breakthrough, industry, pricing

### 2. smart-driving (智能驾驶)
- **Key**: smart-driving
- **Connection**: Independent from existing sectors, major auto tech theme
- **A-share Coverage**: Strong — 德赛西威, 中科创达, 经纬恒润, 伯特利
- **Reliability**: Company filings from listed ADAS/execution suppliers
- **Tags**: overview, architecture, value, next-gen, industry, pricing

### 3. solid-state-battery (固态电池)
- **Key**: solid-state-battery
- **Connection**: Independent battery technology transition
- **A-share Coverage**: Strong — 宁德时代, 当升科技, 天赐材料, 上海洗霸
- **Reliability**: Company filings, research papers on sulfide/oxide/polymer routes
- **Tags**: overview, chemistry, value, manufacturing, industry, pricing

### 4. low-altitude (低空经济)
- **Key**: low-altitude
- **Connection**: Policy-driven independent sector
- **A-share Coverage**: Emerging — 亿航智能, 中直股份, 莱斯信息, 中信海直
- **Reliability**: Chinese govt policy docs, company filings
- **Tags**: overview, architecture, value, airworthiness, industry, pricing

## Excluded Sectors and Reasons
- ai-hardware: Overlaps with ai-computing and smart-driving; end devices less distinct
- business-space: Still limited A-share pure-play coverage
- energy-storage: Overlaps with solid-state-battery on battery materials
- defense: Less A-share research accessibility
- fusion: Too early, limited company filings
- resources: Relatively niche
- innovative-drug/ai-pharma: Need biomedical domain depth outside scope
- ai-application: Software services harder to pin to specific company filings
- data-element/power-grid: Good but lower market urgency

## Source Strategy
- Each sector: 7 SourceRef entries (company_filings + official policies + industry data)
- All announcement IDs verified via cninfo API (akshare stock_zh_a_disclosure_report_cninfo)
- One standard/official source per sector
- One industry/databook source where available
