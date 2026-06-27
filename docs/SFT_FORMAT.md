# SFT 数据格式规范

## 本项目实际输出格式（ShareGPT 风格 JSONL）

`tradingagents/agents/utils/sft_recorder.py` 把每个 agent 的一次完整对话写成一行的 JSONL 记录，文件落盘在 `~/.tradingagents/sft/{ticker}_{trade_date}_{timestamp}.jsonl`。每行结构：

```json
{
  "agent_id": "market_analyst",
  "agent_role": "技术面分析师",
  "task": {"ticker": "000001", "trade_date": "2026-06-20"},
  "status": "ok",
  "degradation_reason": "",
  "messages": [
    {"role": "system", "content": "你是一位专注于 A 股市场的技术分析师…"},
    {"role": "user", "content": "300308"},
    {"role": "assistant", "content": null, "tool_calls": [
      {"type": "function", "id": "call_1", "function": {"name": "get_stock_data", "arguments": {"symbol": "300308"}}}
    ]},
    {"role": "tool", "content": "…K 线数据…", "name": "get_stock_data", "tool_call_id": "call_1"},
    {"role": "assistant", "content": "最终技术分析报告…"}
  ],
  "tools": [
    {"type": "function", "function": {"name": "get_stock_data", "description": "Get stock data by symbol", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}
  ]
}
```

```json
{
  "tools": []
}
```
