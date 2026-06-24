from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.signal_data_tools import (
    get_profit_forecast,
    get_hot_stocks,
    get_northbound_flow,
    get_concept_blocks,
    get_fund_flow,
    get_dragon_tiger_board,
    get_lockup_expiry,
    get_industry_comparison,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


def run_react_loop(chain, tools, initial_message, max_iterations: int = 10) -> str:
    """Self-contained ReAct tool-calling loop that stays inside one graph node.

    Runs ``chain`` (a ``prompt | llm.bind_tools(tools)``) against a *local*
    message list, executing any tool calls inline until the model stops
    requesting tools (or ``max_iterations`` is hit). The report string is
    returned; the local messages are discarded and never written back to
    ``state["messages"]``.

    This is what lets analysts run in parallel: each analyst's tool-call
    history is isolated to a local list, so concurrent analysts don't pollute
    the shared ``messages`` channel. It also removes the need for the old
    per-analyst ``ToolNode`` + conditional-edge + ``Msg Clear`` graph machinery.
    """
    local_messages = [initial_message]
    tool_map = {t.name: t for t in tools}
    result = None
    for _ in range(max_iterations):
        result = chain.invoke(local_messages)
        if not result.tool_calls:
            return result.content
        local_messages.append(result)
        for tc in result.tool_calls:
            output = tool_map[tc["name"]].invoke(tc["args"])
            local_messages.append(
                ToolMessage(content=str(output), tool_call_id=tc["id"])
            )
    return getattr(result, "content", "") or "分析未完成（达到最大迭代次数）"

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
