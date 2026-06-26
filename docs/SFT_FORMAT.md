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
| `messages` | object[] | 完整对话，严格按 OpenAI 原生多轮格式交替（见下） |

## 3. messages 角色

`messages` 数组采用 **OpenAI 原生 tool-calling 格式**。四个角色 `system` / `user` / `assistant` / `tool` 严格交替，**没有两个相同角色连续出现**。

### 3.1 system（第一条，固定 1 条）

```json
{"role": "system", "content": "完整渲染后的 system prompt 文本"}
```

- 分析师：外层 ReAct 壳 + 领域 system_message + tool_names + 日期 + 标的，拼接成的完整文本
- 下游节点（bull/bear/quality_gate/risk_debator）：无独立 system，`content` 为简短角色描述（如"你是多方辩手"）或空串

### 3.2 user（任务输入）

```json
{"role": "user", "content": "300308"}
```

- 分析师：`initial_message`，内容是 ticker 代码
- 下游节点：完整的 user prompt（含拼接的各分析师报告数据）
- 无 `tool_call_id`——那是 `tool` 角色的字段

### 3.3 assistant（模型输出）

assistant message 有两种：

**a) 中间轮（调用工具）**
```json
{"role": "assistant", "content": "", "tool_calls": [
  {"id": "call_abc123", "name": "get_news", "args": {"ticker": "300308", "start_date": "2026-06-01", "end_date": "2026-06-26"}}
]}
```
- `content`：通常为空串（模型直接调工具不输出文本）
- `tool_calls`：工具调用数组，每项含 `id`/`name`/`args`
- 一个 assistant 可含多个 tool_calls（并行调用），下一条是对应数量的 `tool` 消息

**b) 最终轮（最终报告）**
```json
{"role": "assistant", "content": "## 技术分析报告\n最新收盘价...（完整报告）"}
```
- 无 `tool_calls` 字段
- `content` 是 agent 的最终输出（分析师报告 / 辩论论点 / 决策等）

### 3.4 tool（工具执行结果）

```json
{"role": "tool", "tool_call_id": "call_abc123", "content": "date,open,high,low,close\n2026-05-02,..."}
```

- `role`：`"tool"`（OpenAI 原生角色名）
- `content`：工具执行的返回值（字符串）
- `tool_call_id`：对应上一条 assistant 的 `tool_calls[].id`
- 不需要 `tool_name`——通过 `tool_call_id` 追溯到 assistant 的 `tool_calls[].name` 即可获取

## 4. 完整示例（一个分析师的对话）

```json
{"agent_id":"market_analyst","agent_role":"技术分析师","task":{"ticker":"300308","trade_date":"2026-06-26"},"tools":["get_stock_data","get_indicators"],"messages":[
  {"role":"system","content":"You are a helpful AI assistant, collaborating with other assistants. Use the provided tools... You have access to the following tools: get_stock_data, get_indicators.\n你是一位专注于 A 股市场的技术分析师...For your reference, the current date is 2026-06-26. The instrument to analyze is `300308`."},
  {"role":"user","content":"300308"},
  {"role":"assistant","content":"","tool_calls":[{"id":"call_1","name":"get_stock_data","args":{"symbol":"300308","start_date":"2026-05-01","end_date":"2026-06-26"}}]},
  {"role":"tool","tool_call_id":"call_1","content":"date,open,high,low,close,volume\n2026-05-02,..."},
  {"role":"assistant","content":"","tool_calls":[{"id":"call_2","name":"get_indicators","args":{"symbol":"300308","indicator":"rsi","curr_date":"2026-06-26","look_back_days":30}}]},
  {"role":"tool","tool_call_id":"call_2","content":"rsi: 2026-06-26: 65.3..."},
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
3. 之后 `assistant` 和 `tool` 严格交替：`assistant(tool_calls) → tool → assistant(tool_calls) → tool → ...`
4. 最后一条是 `assistant`（最终输出，无 `tool_calls`）
5. 不会出现 `user` 后跟 `user`、`assistant` 后跟 `assistant`
6. `assistant` 带 `tool_calls` 时，下一条必是 `tool`（带匹配的 `tool_call_id`）
7. `tool` 必定紧跟带 `tool_calls` 的 `assistant`，不会独立出现

## 7. 字段约定

- `tool_call_id`：字符串，跨 agent 全局唯一（LangGraph/LLM 生成），用于关联 assistant 的 tool_call 和 tool 消息
- `args`：object，工具参数（原样保留，不序列化为字符串）
- `content`：字符串，纯文本（含 markdown）
- 缺省字段省略（如最终 assistant 不带 `tool_calls`，则不出现该键；`tool` 不带多余字段）

## 8. 采集开关

- 默认开启（生产 SFT 数据）。可通过 config `sft_record: false` 关闭（如纯推理场景不采集）
- 录制对运行无影响：recorder 无配置时 no-op，不影响 agent 执行
- 文件存本地 `~/.tradingagents/sft/`，不入 git（已在 .gitignore）

## 9. 与训练的对接

此格式采用 **OpenAI 原生 tool-calling 消息格式**，可直接喂给主流 SFT 框架：
- **每行 = 一条训练样本**（一个 agent 的完整对话）
- 模型学习：给定 `messages[:-1]`，生成 `messages[-1]`（最后一条 assistant）
- `tool_calls` + `tool` 角色保留完整 tool-use 链，模型学会"何时调工具 → 如何解读结果 → 继续推理"
- 可按 `agent_id` 筛选/平衡样本（如只微调分析师，或按角色配比）
- LlamaFactory、Axolotl、HuggingFace `apply_chat_template` 均可零转换直接加载
