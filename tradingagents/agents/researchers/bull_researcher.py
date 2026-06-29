
from tradingagents.prompts import get_prompt


def create_bull_researcher(llm):
    async def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")
        data_quality_summary = state.get("data_quality_summary", "")

        template = get_prompt("bull_researcher")
        prompt = template.format(
            market_research_report=market_research_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            policy_report=policy_report,
            hot_money_report=hot_money_report,
            lockup_report=lockup_report,
            data_quality_summary=data_quality_summary,
            history=history,
            current_response=current_response,
        )

        from tradingagents.agents.utils.agent_utils import stream_invoke
        content = await stream_invoke(llm, prompt, "bull")

        argument = f"Bull Analyst: {content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "current_speaker": "bull",
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
