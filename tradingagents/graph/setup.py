# TradingAgents/graph/setup.py

from typing import Any, List

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_neutral_debator,
    create_portfolio_manager,
    create_quality_gate,
    create_research_manager,
    create_trader,
)
from tradingagents.agents.analysts.registry import AnalystSpec, resolve_selected
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Sets up the agent workflow graph.

    Analysts run in parallel via Send fan-out from START, then fan-in to the
    Quality Gate (LangGraph barrier — the gate waits for every selected
    analyst to finish). The set of analysts is driven entirely by the
    registry; adding/removing an analyst needs no change here.
    """

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        selected_analysts: List[str] | None = None,
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts: Keys of analyst roles to include (see
                ``ANALYST_REGISTRY``). ``None`` or empty → all analysts.
        """
        active: list[AnalystSpec] = resolve_selected(selected_analysts)
        if not active:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        workflow = StateGraph(AgentState)

        # --- Analyst nodes (one self-contained ReAct node each) ---
        for spec in active:
            workflow.add_node(f"{spec.key}_analyst", spec.create(self.quick_thinking_llm))

        # --- Quality gate (receives the active specs so it only grades them) ---
        workflow.add_node("Quality Gate", create_quality_gate(self.quick_thinking_llm, active))

        # --- Researcher / manager / trader / risk / PM nodes (unchanged) ---
        workflow.add_node("Bull Researcher", create_bull_researcher(self.quick_thinking_llm))
        workflow.add_node("Bear Researcher", create_bear_researcher(self.quick_thinking_llm))
        workflow.add_node("Research Manager", create_research_manager(self.deep_thinking_llm))
        workflow.add_node("Trader", create_trader(self.quick_thinking_llm))
        workflow.add_node("Aggressive Analyst", create_aggressive_debator(self.quick_thinking_llm))
        workflow.add_node("Neutral Analyst", create_neutral_debator(self.quick_thinking_llm))
        workflow.add_node("Conservative Analyst", create_conservative_debator(self.quick_thinking_llm))
        workflow.add_node("Portfolio Manager", create_portfolio_manager(self.deep_thinking_llm))

        # --- Send fan-out: all selected analysts start in one superstep ---
        def fan_out(state):
            return [
                Send(f"{spec.key}_analyst", {
                    "company_of_interest": state["company_of_interest"],
                    "trade_date": state["trade_date"],
                })
                for spec in active
            ]

        workflow.add_conditional_edges(START, fan_out)

        # --- barrier fan-in: every analyst → Quality Gate ---
        # LangGraph waits for all incoming edges before running Quality Gate.
        for spec in active:
            workflow.add_edge(f"{spec.key}_analyst", "Quality Gate")

        # --- Downstream edges (unchanged from the serial pipeline) ---
        workflow.add_edge("Quality Gate", "Bull Researcher")
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_edge("Portfolio Manager", END)

        return workflow
