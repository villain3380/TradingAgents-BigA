from langchain_core.messages import HumanMessage
from tradingagents.agents.utils.agent_utils import (
    build_analyst_prompt,
    build_instrument_context,
    get_concept_blocks,
    get_dragon_tiger_board,
    get_fund_flow,
    get_hot_stocks,
    get_industry_comparison,
    get_insider_transactions,
    get_language_instruction,
    get_news,
    get_northbound_flow,
    get_stock_data,
    run_react_loop,
)
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt


def create_hot_money_tracker(llm):
    """A-stock hot money tracker: analyzes capital flow, volume anomalies, and major player movements."""

    async def hot_money_tracker_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_stock_data,
            get_news,
            get_insider_transactions,
            get_hot_stocks,
            get_northbound_flow,
            get_concept_blocks,
            get_fund_flow,
            get_dragon_tiger_board,
            get_industry_comparison,
        ]

        system_message = (
            get_prompt("hot_money_tracker")
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
            "hot_money_report": report,
        }

    return hot_money_tracker_node
