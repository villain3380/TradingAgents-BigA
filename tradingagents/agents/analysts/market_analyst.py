from langchain_core.messages import HumanMessage
from tradingagents.agents.utils.agent_utils import (
    build_analyst_prompt,
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
    run_react_loop,
)
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt


def create_market_analyst(llm):

    async def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_stock_data,
            get_indicators,
        ]

        system_message = (
            get_prompt("market_analyst")
            + get_language_instruction()
        )

        prompt = build_analyst_prompt(system_message, tools, current_date, instrument_context)

        chain = prompt | llm.bind_tools(tools)

        initial_msg = HumanMessage(content=state["company_of_interest"])

        # Render the full system prompt once for SFT recording.
        rendered = prompt.invoke({"messages": [initial_msg]})
        system_prompt_text = str(rendered.messages[0].content) if rendered.messages else ""

        report = await run_react_loop(
            chain, tools, initial_msg, max_iterations=10,
            system_prompt_text=system_prompt_text,
        )

        return {
            "market_report": report,
        }

    return market_analyst_node
