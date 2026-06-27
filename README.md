<h1 align="center">TradingAgents-BigA</h1>

<p align="center">
  基于 <a href="https://github.com/TauricResearch/TradingAgents">TauricResearch/TradingAgents</a>（88K ⭐）和 <a href="https://github.com/simonlin1212/TradingAgents-astock">simonlin1212/TradingAgents-astock（1.4K ⭐）<br>
  全 Apache 2.0 开源
</p>

<p align="center">
  <b>⚠️ 免责声明：本项目仅供学习研究与技术演示，不构成任何投资建议。投资决策请咨询持牌专业机构。</b>
</p>

<p align="center">
  <a href="https://github.com/villain3380/TradingAgents-BigA/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/villain3380/TradingAgents-BigA?style=social"/></a>
  <a href="https://github.com/villain3380/TradingAgents-BigA/network/members"><img alt="Forks" src="https://img.shields.io/github/forks/villain3380/TradingAgents-BigA?style=social"/></a>
  <a href="https://arxiv.org/abs/2412.20138"><img alt="论文" src="https://img.shields.io/badge/论文-arXiv_2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue"/></a>
  <a href="./CHANGES_FROM_UPSTREAM.md"><img alt="改动记录" src="https://img.shields.io/badge/改动记录-CHANGES-orange"/></a>
</p>

---

## 目录

- [目录](#目录)
- [架构概览](#架构概览)
- [7 个 Analyst 角色（A 股适配）](#7-个-analyst-角色a-股适配)
- [数据源](#数据源)
- [快速开始](#快速开始)
  - [环境准备](#环境准备)
  - [启动](#启动)
- [项目结构](#项目结构)
- [致谢](#致谢)
- [许可证](#许可证)
- [免责声明](#免责声明)

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    7 Analyst 研报生成                      │
│  Market → Social → News → Fundamentals                   │
│  → Policy → Hot Money → Lockup                           │
│         （每个 Analyst 带工具循环）                          │
├─────────────────────────────────────────────────────────┤
│               Bull vs Bear 投研辩论                       │
│         Bull Researcher ←→ Bear Researcher               │
│               （最多 N 轮辩论）                             │
├─────────────────────────────────────────────────────────┤
│              Research Manager 综合研判                     │
│         （深度思考 LLM，输出投资计划）                       │
├─────────────────────────────────────────────────────────┤
│                  Trader 交易方案                          │
│         （A 股约束：T+1/涨跌停/手数）                       │
├─────────────────────────────────────────────────────────┤
│        Aggressive ←→ Conservative ←→ Neutral             │
│               三方风险辩论                                 │
├─────────────────────────────────────────────────────────┤
│            Portfolio Manager 最终决策                      │
│     （深度思考 LLM，输出 Buy/Hold/Sell + 仓位）             │
└─────────────────────────────────────────────────────────┘
```

**双 LLM 设计**：
- `quick_think_llm`：所有 Analyst、Researcher、Trader、Risk Debater
- `deep_think_llm`：Research Manager 和 Portfolio Manager（需要综合全局信息做决策）

---

## 7 个 Analyst 角色（A 股适配）

| 角色 | 职责 | 数据工具 |
|------|------|---------|
| 🏪 市场分析师 | K 线形态、技术指标、量价分析 | `get_stock_data`, `get_indicators` |
| 💬 舆情分析师 | 社交媒体情绪、散户讨论热度 | `get_news` |
| 📰 新闻分析师 | 行业新闻、公告、宏观事件 | `get_news`, `get_global_news`, `get_insider_transactions` |
| 📊 基本面分析师 | 财报三表、盈利能力、估值 | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` |
| 🏛️ 政策分析师 | 监管政策、产业政策、窗口指导   | `get_news`, `get_global_news`                              |
| 🔥 游资追踪师  | 龙虎榜、大单流向、主力资金动态  | `get_stock_data`, `get_news`, `get_insider_transactions`   |
| 🔓 解禁监控师  | 限售股解禁、大股东减持、股权质押 | `get_insider_transactions`, `get_news`, `get_fundamentals` |

所有 7 个 Analyst 的报告会流入后续的 Bull/Bear 辩论和三方风险辩论，确保 A 股特色因素贯穿整条决策链。

---

## 数据源

全部免费，无需 API Key，无积分墙：

| 来源 | 协议 | 提供内容 |
|------|------|---------|
| **mootdx** | TCP 7709 | OHLCV K 线、财务快照、F10 文本 |
| **腾讯财经** | HTTP (`qt.gtimg.cn`) | PE / PB / 市值 / 换手率（实时） |
| **东方财富** | HTTP (datacenter / push2) | 龙虎榜、限售解禁、板块行情、个股信息 |
| **新浪财经** | HTTP | K 线历史、财报三表 |
| **同花顺** | HTTP (10jqka) | EPS 一致预期 |
| **财联社** | HTTP (cls.cn) | 全球财经快讯 |
| **百度股市通** | HTTP (finance.pae.baidu) | 概念板块分类、资金流向 |

> 完全不依赖 Tushare（积分墙）、Alpha Vantage（海外 API）、Yahoo Finance（不支持 A 股）。

---

> **数据源优先级 & 东财防封（v0.2.11）**：行情 / K线 / 市值 / 财务能从 mootdx（通达信 TCP，不封 IP）或腾讯拿到的，一律走它们；东财只用于它独有的数据（龙虎榜 / 解禁 / 资金流 / 板块 / 个股新闻等）。所有东财请求统一走内置节流入口 `_em_get()`：串行限流（默认间隔 ≥1s + 0.1~0.5s 随机抖动）+ 复用 Keep-Alive 会话，多 Agent 跑批量分析不再触发临时封 IP（东财风控实测：每秒 >5 / 并发 ≥10 / 1 分钟 ≥200 触发封禁）。批量场景可设环境变量 `EM_MIN_INTERVAL=1.5~2` 进一步降速。**仅东财限流，mootdx / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 不受影响。**

## 快速开始

### 环境准备

```bash
# Python >= 3.10
git clone https://github.com/simonlin1212/TradingAgents-BigA.git
cd TradingAgents-BigA
pip install -e .

# 如需使用 Google Gemini 模型（可选）：
pip install -e ".[google]"
```

> **装完即可用，无需 Docker。** 安装后直接跑 `streamlit run web/app.py`（Web UI）或 `tradingagents`（CLI）即可，详见下方「Web UI」「CLI 方式」两节。Docker 仅是可选的部署方式，本地开发不需要。

---

### 启动

```bash
tradingagents-api
cd frontend && npm run dev
```

浏览器开 `http://localhost:5173`：左侧配置侧栏（可折叠）+ 中间 7 分析师卡片（固定高度内部滚动，点开 Modal 放大看 markdown 报告）+ 右侧实时统计/进度/下载。

> 需要 `pip install -e ".[api]"` 装 FastAPI 依赖；前端 `npm install` 在 `frontend/` 下。

---

## 项目结构

```
TradingAgents-BigA/
├── tradingagents/
│   ├── agents/
│   │   ├── analysts/          # 7 个分析师（含 registry.py 单一事实源）
│   │   │   ├── market_analyst.py
│   │   │   ├── social_media_analyst.py
│   │   │   ├── news_analyst.py
│   │   │   ├── fundamentals_analyst.py
│   │   │   ├── policy_analyst.py        # A 股特化
│   │   │   ├── hot_money_tracker.py     # A 股特化
│   │   │   ├── lockup_watcher.py        # A 股特化
│   │   │   └── registry.py              # AnalystSpec 注册表（加/减分析师只改这里）
│   │   ├── researchers/       # Bull / Bear 研究员
│   │   ├── risk_mgmt/         # 激进 / 保守 / 中立 辩手
│   │   ├── managers/          # Research Manager + Portfolio Manager
│   │   ├── trader/            # Trader（A 股交易约束）
│   │   ├── quality_gate.py    # 数据质量门控（硬检查 + LLM 复审）
│   │   ├── schemas.py         # 结构化输出 Pydantic 模型
│   │   └── utils/             # 状态定义、工具函数、SFT 录制器
│   │       ├── agent_utils.py          # run_react_loop / stream_invoke
│   │       ├── structured.py           # with_structured_output 封装
│   │       ├── sft_recorder.py         # SFT 训练数据采集（JSONL + debug 日志）
│   │       └── *_tools.py              # 各类 @tool 包装
│   ├── dataflows/
│   │   ├── a_stock.py         # A 股数据 vendor（直连 HTTP API，零第三方库）
│   │   ├── interface.py       # 数据接口抽象层 + vendor 路由
│   │   └── ...
│   ├── graph/
│   │   ├── trading_graph.py   # 主入口：TradingAgentsGraph
│   │   ├── setup.py           # LangGraph 拓扑（Send fan-out 并行）
│   │   ├── propagation.py     # 状态初始化与传播
│   │   ├── reflection.py      # 交易反思（沪深 300 基准）
│   │   └── conditional_logic.py
│   ├── llm_clients/           # 多供应商 LLM 客户端（OpenAI/Anthropic/Google/...）
│   ├── default_config.py      # 默认配置（含 sft_record 开关）
│   └── settings.py            # ~/.tradingagents/settings.json 读写
├── web/
│   ├── api/                   # FastAPI + SSE 服务（tradingagents-api）
│   │   ├── server.py          # /api/analyze + SSE 流式
│   │   ├── launch.py          # uvicorn 启动入口
│   │   └── stages.py          # 阶段事件检测
│   ├── pdf_export.py          # PDF 报告生成（CJK 字体自检测）
│   └── stock_display.py       # 股票名→代码解析与展示
├── frontend/                  # TypeScript + React 流式 UI（Vite :5173）
│   └── src/                   # 7 分析师卡片 + 实时统计 + 报告下载
├── cli/                       # 交互式 CLI（tradingagents）
├── data/
│   └── data_viewer.py         # SFT JSONL 数据查看 Web 工具（人工筛选）
├── docs/
│   └── SFT_FORMAT.md          # SFT 训练数据格式规范
├── tests/                     # pytest 测试套件
├── scripts/
│   └── smoke_structured_output.py  # 结构化输出冒烟测试
├── CHANGES_FROM_UPSTREAM.md   # 与上游的完整改动记录
├── CHANGELOG.md               # 版本变更日志
├── NOTICE                     # Apache 2.0 归属声明
├── LICENSE                    # Apache 2.0 许可证
└── pyproject.toml             # 包定义与依赖
```

---

## 致谢

本项目基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 和 [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) 开源项目进行改造。感谢原作者们的出色工作和 Apache 2.0 开源精神。

**原始论文**：[TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138)

---

## 许可证

[Apache License 2.0](./LICENSE)

本项目是 TauricResearch/TradingAgents 的 fork，继承 Apache 2.0 许可证。详见 [NOTICE](./NOTICE)。

---

## 免责声明

> **本项目仅供学习研究与技术演示，不构成任何投资建议。**
>
> - 本系统产出的所有分析报告和交易信号均由 AI 自动生成，可能存在错误或偏差
> - 投资决策请咨询持有中国证监会颁发资质的专业机构
> - 作者不对使用本工具产生的任何投资损失承担责任
> - 股市有风险，投资需谨慎
