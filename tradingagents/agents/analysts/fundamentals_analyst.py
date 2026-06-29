from langchain_core.messages import HumanMessage
from tradingagents.agents.utils.agent_utils import (
    build_analyst_prompt,
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_industry_comparison,
    get_insider_transactions,
    get_language_instruction,
    get_profit_forecast,
    run_react_loop,
)
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt


def create_fundamentals_analyst(llm):
    async def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
            get_profit_forecast,
            get_industry_comparison,
        ]

        system_message = (
            get_prompt("fundamentals_analyst")
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
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
