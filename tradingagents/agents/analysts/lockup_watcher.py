from langchain_core.messages import HumanMessage
from tradingagents.agents.utils.agent_utils import (
    build_analyst_prompt,
    build_instrument_context,
    get_fundamentals,
    get_insider_transactions,
    get_language_instruction,
    get_lockup_expiry,
    get_news,
    run_react_loop,
)
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt


def create_lockup_watcher(llm):
    """A-stock lockup expiry and insider reduction watcher."""

    async def lockup_watcher_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_insider_transactions,
            get_news,
            get_fundamentals,
            get_lockup_expiry,
        ]

        system_message = (
            get_prompt("lockup_watcher")
            + get_language_instruction()
        )

        prompt = build_analyst_prompt(system_message, tools, current_date, instrument_context)

        chain = prompt | llm.bind_tools(tools)

        initial_msg = HumanMessage(content=state["company_of_interest"])
        rendered = prompt.invoke({"messages": [initial_msg]})
        system_prompt_text = str(rendered.messages[0].content) if rendered.messages else ""

        report = await run_react_loop(
            chain, tools, initial_msg, max_iterations=10,
            system_prompt_text=system_prompt_text,
        )

        return {
            "lockup_report": report,
        }

    return lockup_watcher_node
