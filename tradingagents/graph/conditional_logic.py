# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue.

        Routes on the explicit ``current_speaker`` token ("bull"/"bear"), NOT
        on the prose prefix of ``current_response``. Prefix-based routing
        coupled control flow to LLM output and broke if the prefix was
        localized (e.g. "多方分析师：") — bull would route to bull forever and
        the debate would spin to recursion_limit.
        """
        debate = state["investment_debate_state"]
        if debate["count"] >= 2 * self.max_debate_rounds:
            return "Research Manager"
        if debate.get("current_speaker", "") == "bull":
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue.

        ``latest_speaker`` is a controlled token set by the debator nodes
        ("Aggressive"/"Conservative"/"Neutral"), not LLM prose, so an exact
        match is safe and stricter than the previous ``startswith``.
        """
        risk = state["risk_debate_state"]
        if risk["count"] >= 3 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"
        speaker = risk.get("latest_speaker", "")
        if speaker == "Aggressive":
            return "Conservative Analyst"
        if speaker == "Conservative":
            return "Neutral Analyst"
        return "Aggressive Analyst"
