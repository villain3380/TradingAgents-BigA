# SFT 数据格式规范

本文件定义 TradingAgents-BigA 的 SFT（监督微调）训练数据采集格式。所有 agent（分析师 + 辩论 + 风控 + 决策）的完整交互按此格式录制为 jsonl，供后续微调使用。

## 1. 文件组织

- **路径**：`~/.tradingagents/sft/{ticker}_{date}_{timestamp}.jsonl`
  - `ticker`：股票代码（如 `300308`）
  - `date`：分析日期（如 `2026-06-26`）
  - `timestamp`：任务启动时间戳（如 `20260626_153022`），防同票同日多次分析覆盖
- **粒度**：**一次分析任务（propagate）= 1 个 jsonl 文件**
- **行数**：每行 1 个 agent 的完整对话，行数 = 本次跑的 agent 数（选中分析师 + 6 个下游流式节点）
- **编码**：UTF-8，`ensure_ascii=False`（中文不转义）

## 2. 每行格式（一个 agent 的一次对话）

每行是一个 JSON object：

```json
{
  "agent_id": "market_analyst",
  "agent_role": "技术分析师",
  "task": {"ticker": "300308", "trade_date": "2026-06-26"},
  "tools": ["get_stock_data", "get_indicators"],
  "messages": [ ... ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | string | agent 标识。分析师=`market_analyst`/`news_analyst`/...（节点名）；下游=`bull`/`bear`/`quality_gate`/`aggressive`/`conservative`/`neutral` |
| `agent_role` | string | 角色中文名（如"技术分析师"/"多方辩手"），便于人读 |
| `task` | object | 任务上下文 `{"ticker", "trade_date"}` |
| `tools` | string[] | 该 agent 可用的工具名列表。下游节点无工具，为 `[]` |
| `messages` | object[] | 完整对话，严格"一问一答"交替（见下） |

## 3. messages 角色（核心：一问一答交替）

`messages` 数组严格按 `system → user → assistant → user → assistant → ...` 交替。**没有两个相同角色连续出现**。

### 3.1 system（第一条，固定 1 条）

```json
{"role": "system", "content": "完整渲染后的 system prompt 文本"}
```

- 分析师：外层 ReAct 壳 + 领域 system_message + tool_names + 日期 + 标的，拼接成的完整文本
- 下游节点（bull/bear/quality_gate/risk_debator）：无独立 system，`content` 为简短角色描述（如"你是多方辩手"）或空串

### 3.2 user（一问一答的"问"）

user message 有两种来源，**统一用 `role: "user"`**：

**a) 初始 user message（第一条 user）**
```json
{"role": "user", "content": "300308"}
```
- 分析师：`initial_message`，内容是 ticker 代码
- 下游节点：完整的 user prompt（含拼接的各分析师报告数据）

**b) tool_result（工具调用结果，本质也是 user）**
```json
{"role": "user", "content": "工具返回的数据文本...", "tool_call_id": "call_abc123", "tool_name": "get_news"}
```
- `content`：工具执行的返回值（字符串）
- `tool_call_id`：对应上一条 assistant 的 tool_call 的 id
- `tool_name`：工具名

> **为什么 tool_result 是 user？** 因为在 LLM 的对话上下文里，tool_result 是塞回给 assistant（模型）的——从模型视角它是一条"输入"。OpenAI/Anthropic 的消息格式里 tool result 也属于"给模型的输入"侧。SFT 训练时模型学的是"给定 user(含tool_result) → 生成 assistant"，所以 tool_result 归 user。用 `tool_call_id` + `tool_name` 额外字段标记它的来源，训练框架可据此还原。

### 3.3 assistant（一问一答的"答"）

assistant message 有两种：

**a) 中间轮（调用工具）**
```json
{"role": "assistant", "content": "", "tool_calls": [
  {"id": "call_abc123", "name": "get_news", "args": {"ticker": "300308", "start_date": "2026-06-01", "end_date": "2026-06-26"}}
]}
```
- `content`：通常为空串（模型直接调工具不输出文本）
- `tool_calls`：工具调用数组，每项含 `id`/`name`/`args`
- 一个 assistant 可含多个 tool_calls（并行调用），下一条 user 是对应数量的 tool_result

**b) 最终轮（最终报告）**
```json
{"role": "assistant", "content": "## 技术分析报告\n最新收盘价...（完整报告）"}
```
- 无 `tool_calls`（或 `tool_calls: []`）
- `content` 是 agent 的最终输出（分析师报告 / 辩论论点 / 决策等）

## 4. 完整示例（一个分析师的对话）

```json
{"agent_id":"market_analyst","agent_role":"技术分析师","task":{"ticker":"300308","trade_date":"2026-06-26"},"tools":["get_stock_data","get_indicators"],"messages":[
  {"role":"system","content":"You are a helpful AI assistant, collaborating with other assistants. Use the provided tools... You have access to the following tools: get_stock_data, get_indicators.\n你是一位专注于 A 股市场的技术分析师...For your reference, the current date is 2026-06-26. The instrument to analyze is `300308`."},
  {"role":"user","content":"300308"},
  {"role":"assistant","content":"","tool_calls":[{"id":"call_1","name":"get_stock_data","args":{"symbol":"300308","start_date":"2026-05-01","end_date":"2026-06-26"}}]},
  {"role":"user","content":"date,open,high,low,close,volume\n2026-05-02,...","tool_call_id":"call_1","tool_name":"get_stock_data"},
  {"role":"assistant","content":"","tool_calls":[{"id":"call_2","name":"get_indicators","args":{"symbol":"300308","indicator":"rsi","curr_date":"2026-06-26","look_back_days":30}}]},
  {"role":"user","content":"rsi: 2026-06-26: 65.3...","tool_call_id":"call_2","tool_name":"get_indicators"},
  {"role":"assistant","content":"## 技术分析报告\n\n最新收盘价...（完整报告）"}
]}
```

## 5. 下游节点示例（单轮，无工具）

下游节点（bull/bear/quality_gate/risk_debator）是单轮：user prompt（含报告数据）→ assistant 回复。

```json
{"agent_id":"bull","agent_role":"多方辩手","task":{"ticker":"300308","trade_date":"2026-06-26"},"tools":[],"messages":[
  {"role":"system","content":"你是多方辩手，基于分析师报告构建看多论点。"},
  {"role":"user","content":"You are a Bull Analyst advocating... Market research report: ...（拼接的各分析师报告）"},
  {"role":"assistant","content":"Bull Analyst: 基于技术面和基本面...（多方论点）"}
]}
```

## 6. 交替规则总结

`messages` 数组必须满足：

1. 第一条是 `system`（且唯一）
2. 第二条是 `user`（初始 message）
3. 之后 `assistant` 和 `user` 严格交替
4. `assistant` 带 `tool_calls` 时，下一条 `user` 必是 `tool_result`（带 `tool_call_id`）
5. 最后一条是 `assistant`（最终输出，无 `tool_calls`）
6. 不会出现 `user` 后跟 `user`、`assistant` 后跟 `assistant`

## 7. 字段约定

- `tool_call_id`：字符串，跨 agent 全局唯一（LangGraph/LLM 生成），用于关联 assistant 的 tool_call 和 user 的 tool_result
- `args`：object，工具参数（原样保留，不序列化为字符串）
- `content`：字符串，纯文本（含 markdown）
- 缺省字段省略（如最终 assistant 不带 `tool_calls`，则不出现该键）

## 8. 采集开关

- 默认开启（生产 SFT 数据）。可通过 config `sft_record: false` 关闭（如纯推理场景不采集）
- 录制对运行无影响：recorder 无配置时 no-op，不影响 agent 执行
- 文件存本地 `~/.tradingagents/sft/`，不入 git（已在 .gitignore）

## 9. 与训练的对接

此格式可直接喂给主流 SFT 框架：
- **每行 = 一条训练样本**（一个 agent 的完整对话）
- 模型学习：给定 `messages[:-1]`（system + user/assistant 交替到倒数第二条），生成 `messages[-1]`（最后一条 assistant）
- `tool_calls` 字段保留，训练模型学工具调用；`tool_result` 作为 user 喂入，训练模型学"基于工具结果继续推理"
- 可按 `agent_id` 筛选/平衡样本（如只微调分析师，或按角色配比）
