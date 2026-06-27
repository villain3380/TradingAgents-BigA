"""Tests for reasoning-model detection and structured-output gating.

Regression coverage for the bug where broad substring markers ("latest",
"think") mis-flagged ordinary models like ``glm-latest`` as reasoning models,
silently disabling structured output for the default config — so PM/Trader/
Research Manager emitted free-text prose instead of typed PortfolioDecision /
TraderProposal / ResearchPlan objects.
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.utils.structured import (
    _is_thinking_model,
    bind_structured,
)


def _llm_with_name(name: str) -> MagicMock:
    """A minimal mock exposing model_name like a LangChain chat model does."""
    m = MagicMock()
    m.model_name = name
    # MagicMock auto-creates other attrs as mocks; _resolve_model_name checks
    # isinstance(str), so model_name is the only one it will read.
    return m


@pytest.mark.unit
class TestIsThinkingModelHeuristic:
    def test_glm_latest_is_not_reasoning(self):
        """Default-config regression: glm-latest must NOT be flagged."""
        assert _is_thinking_model(_llm_with_name("glm-latest")) is False

    def test_gpt5_default_is_not_reasoning(self):
        assert _is_thinking_model(_llm_with_name("gpt-5.4")) is False
        assert _is_thinking_model(_llm_with_name("gpt-5.4-mini")) is False

    def test_deepseek_reasoner_is_reasoning(self):
        assert _is_thinking_model(_llm_with_name("deepseek-reasoner")) is True

    def test_deepseek_r1_is_reasoning(self):
        assert _is_thinking_model(_llm_with_name("deepseek-r1")) is True

    def test_openai_o1_o3_are_reasoning(self):
        assert _is_thinking_model(_llm_with_name("o1")) is True
        assert _is_thinking_model(_llm_with_name("o1-mini")) is True
        assert _is_thinking_model(_llm_with_name("o1-pro")) is True
        assert _is_thinking_model(_llm_with_name("o3")) is True
        assert _is_thinking_model(_llm_with_name("o3-mini")) is True

    def test_no_broad_substring_false_positives(self):
        """Names that merely contain an old marker substring are NOT flagged."""
        # "latest" and "think" used to trigger false positives.
        assert _is_thinking_model(_llm_with_name("qwen-latest")) is False
        assert _is_thinking_model(_llm_with_name("thinker-toy")) is False
        # Bare substring "o1" inside another token must not match.
        assert _is_thinking_model(_llm_with_name("foo1")) is False

    def test_unknown_model_name_returns_false(self):
        """No detectable name → defer to provider-layer / runtime fallback."""
        llm = MagicMock()
        del llm.model_name
        del llm.model
        del llm.deployment_name
        # getattr returns MagicMock (not str) for all attrs → name stays "".
        assert _is_thinking_model(llm) is False


@pytest.mark.unit
class TestIsThinkingModelConfigOverride:
    """thinking_models / non_thinking_models override the heuristic."""

    def test_thinking_models_forces_reasoning(self):
        from tradingagents.dataflows.config import set_config

        set_config({"thinking_models": ["glm-latest"]})
        try:
            assert _is_thinking_model(_llm_with_name("glm-latest")) is True
            # Case-insensitive exact match.
            assert _is_thinking_model(_llm_with_name("GLM-Latest")) is True
        finally:
            set_config({"thinking_models": []})

    def test_non_thinking_models_overrides_heuristic_match(self):
        from tradingagents.dataflows.config import set_config

        set_config({"non_thinking_models": ["deepseek-r1"]})
        try:
            # Heuristic would say True, but explicit exclusion wins.
            assert _is_thinking_model(_llm_with_name("deepseek-r1")) is False
        finally:
            set_config({"non_thinking_models": []})


@pytest.mark.unit
class TestBindStructuredGating:
    class _DummySchema(MagicMock):
        pass

    def test_non_reasoning_model_binds_structured(self):
        llm = _llm_with_name("glm-latest")
        llm.with_structured_output.return_value = "BOUND"
        result = bind_structured(llm, self._DummySchema, "PM")
        assert result == "BOUND"
        llm.with_structured_output.assert_called_once()

    def test_reasoning_model_skips_structured(self):
        llm = _llm_with_name("deepseek-reasoner")
        result = bind_structured(llm, self._DummySchema, "PM")
        assert result is None
        llm.with_structured_output.assert_not_called()

    def test_provider_not_implemented_falls_back(self):
        llm = _llm_with_name("glm-latest")
        llm.with_structured_output.side_effect = NotImplementedError("nope")
        result = bind_structured(llm, self._DummySchema, "PM")
        assert result is None
