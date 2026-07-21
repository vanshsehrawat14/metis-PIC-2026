"""
tests/test_intelligence.py — Tests for the Vane Intelligence Interface.

Tests the LLM orchestration layer without requiring an API key.
Tool routing tests call _execute_tool directly (hits real EngineBridge).
Chat loop tests mock _call_anthropic to simulate the Anthropic API.
"""

import asyncio
import json

import pytest

from api.intelligence import VaneIntelligence, TOOLS, SYSTEM_PROMPT


@pytest.fixture
def intel():
    """VaneIntelligence instance with dummy API key."""
    return VaneIntelligence(api_key="test-key-not-real")


def run_async(coro):
    """Helper to run async coroutines in sync tests (Python 3.14 compatible)."""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
#  Tool Execution — routes through real EngineBridge
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolExecution:
    """Test that tools route correctly to EngineBridge methods."""

    def test_run_simulation_tool(self, intel):
        """run_simulation tool should call bridge.run_simulation."""
        result = intel._execute_tool("run_simulation", {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "weather_factor": 0.3,
            "transit_factor": 0.5,
            "n_simulations": 200,
        })
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["venue_id"] == "allegiant_stadium"
        assert "metrics" in parsed

    def test_run_temporal_tool(self, intel):
        """run_temporal_simulation tool should call bridge.run_temporal."""
        result = intel._execute_tool("run_temporal_simulation", {
            "venue_id": "t_mobile_arena",
            "attendance": 18000,
            "event_type": "boxing_mma",
            "event_duration_hours": 4.0,
            "weather_factor": 0.2,
            "transit_factor": 0.6,
            "mode": "fast",
        })
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_get_venue_info_list(self, intel):
        """get_venue_info with 'list' should return all venues."""
        result = intel._execute_tool("get_venue_info", {"venue_id": "list"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert len(parsed["venues"]) >= 15

    def test_get_venue_info_specific(self, intel):
        """get_venue_info with a venue_id should return that venue's details."""
        result = intel._execute_tool("get_venue_info", {"venue_id": "sphere_las_vegas"})
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_get_engine_specs(self, intel):
        """get_engine_specs should return technical specifications."""
        result = intel._execute_tool("get_engine_specs", {})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "limitations" in parsed["engine"]

    def test_unknown_venue_returns_error(self, intel):
        """Unknown venue should return helpful error, not crash."""
        result = intel._execute_tool("run_simulation", {
            "venue_id": "madison_square_garden",
            "attendance": 20000,
            "event_type": "concert",
        })
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "error" in parsed
        assert "madison_square_garden" in parsed["error"]

    def test_stress_test_tool(self, intel):
        """run_stress_tests should execute and return resilience score."""
        result = intel._execute_tool("run_stress_tests", {
            "venue_id": "allegiant_stadium",
            "attendance": 50000,
            "event_type": "nfl",
            "weather_factor": 0.3,
            "transit_factor": 0.5,
            "tests": ["gate_failure", "extreme_heat"],
        })
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "resilience_score" in parsed

    def test_what_if_tool(self, intel):
        """run_what_if should execute and return comparison."""
        result = intel._execute_tool("run_what_if", {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "changes": {"reduce_staffing_pct": 0.3},
        })
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_unknown_tool_returns_error(self, intel):
        """Unknown tool name should return error, not crash."""
        result = intel._execute_tool("nonexistent_tool", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "Unknown tool" in parsed["error"]

    def test_simulation_with_minimal_params(self, intel):
        """Tool should work with only required parameters."""
        result = intel._execute_tool("run_simulation", {
            "venue_id": "sphere_las_vegas",
            "attendance": 15000,
            "event_type": "concert",
        })
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["venue_id"] == "sphere_las_vegas"

    def test_tool_falls_back_to_authoritative_scenario_context(self, intel):
        """Tool execution should use scenario context when Claude omits repeated fields."""
        intel._scenario = {
            "venue_id": "t_mobile_arena",
            "attendance": 18000,
            "event_type": "boxing_mma",
            "service_rate_tier": "literature",
            "avg_ticket_price": 225.0,
            "weather_factor": 0.2,
            "transit_factor": 0.6,
        }
        result = intel._execute_tool("run_simulation", {"n_simulations": 200})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["venue_id"] == "t_mobile_arena"
        assert parsed["parameters"]["service_rate_tier"] == "literature"
        assert parsed["parameters"]["avg_ticket_price"] == pytest.approx(225.0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Result Trimming
# ═══════════════════════════════════════════════════════════════════════════════

class TestResultTrimming:
    """Test that simulation results are trimmed for LLM context."""

    def test_trim_keeps_aggregate_metrics(self, intel):
        """Trimmed result should retain all top-level metrics."""
        from api.models import SimulationRequest
        raw = intel.bridge.run_simulation(SimulationRequest(
            venue_id="allegiant_stadium",
            attendance=45000,
            event_type="nfl",
            weather_factor=0.3,
            transit_factor=0.5,
            n_simulations=200,
        ))
        trimmed = intel._trim_simulation_result(raw)
        assert "metrics" in trimmed
        assert trimmed["metrics"]["operational"]["wait_time"]["mean"] > 0

    def test_trim_limits_node_count(self, intel):
        """Trimmed result should have at most 5 node details."""
        from api.models import SimulationRequest
        raw = intel.bridge.run_simulation(SimulationRequest(
            venue_id="allegiant_stadium",
            attendance=45000,
            event_type="nfl",
            weather_factor=0.3,
            transit_factor=0.5,
            n_simulations=200,
        ))
        trimmed = intel._trim_simulation_result(raw)
        if "node_metrics" in trimmed.get("simulation", {}):
            assert len(trimmed["simulation"]["node_metrics"]) <= 5

    def test_trim_preserves_success_flag(self, intel):
        """Trimming should not remove top-level result keys."""
        from api.models import SimulationRequest
        raw = intel.bridge.run_simulation(SimulationRequest(
            venue_id="t_mobile_arena",
            attendance=18000,
            event_type="concert",
            weather_factor=0.2,
            transit_factor=0.6,
            n_simulations=200,
        ))
        trimmed = intel._trim_simulation_result(raw)
        assert trimmed["success"] is True
        assert trimmed["venue_id"] == "t_mobile_arena"
        assert "computation_time_ms" in trimmed

    def test_trim_marks_trimmed_flag(self, intel):
        """Trimmed results should indicate they were trimmed."""
        from api.models import SimulationRequest
        raw = intel.bridge.run_simulation(SimulationRequest(
            venue_id="allegiant_stadium",
            attendance=45000,
            event_type="nfl",
            weather_factor=0.3,
            transit_factor=0.5,
            n_simulations=200,
        ))
        trimmed = intel._trim_simulation_result(raw)
        sim = trimmed.get("simulation", {})
        # Allegiant has 39 nodes — should be trimmed
        if sim.get("_node_metrics_trimmed"):
            assert sim["_total_nodes"] > 5


# ═══════════════════════════════════════════════════════════════════════════════
#  Conversation History Management
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationHistory:
    """Test conversation state management."""

    def test_reset_clears_history(self, intel):
        intel.conversation_history = [{"role": "user", "content": "test"}]
        intel.reset_conversation()
        assert len(intel.conversation_history) == 0

    def test_system_prompt_exists(self):
        """System prompt should be non-empty and contain key directives."""
        assert len(SYSTEM_PROMPT) > 100
        assert "simulate" in SYSTEM_PROMPT.lower()
        assert "venue" in SYSTEM_PROMPT.lower()

    def test_tools_defined(self):
        """All required tools should be defined."""
        tool_names = {t["name"] for t in TOOLS}
        assert "run_simulation" in tool_names
        assert "run_temporal_simulation" in tool_names
        assert "run_what_if" in tool_names
        assert "run_stress_tests" in tool_names
        assert "get_venue_info" in tool_names
        assert "get_engine_specs" in tool_names

    def test_tool_count(self):
        """Should have exactly 6 simulation tools."""
        assert len(TOOLS) == 6

    def test_conversation_summary_empty(self, intel):
        """Empty conversation should report zero messages."""
        summary = intel.get_conversation_summary()
        assert summary["message_count"] == 0
        assert summary["tools_used"] == []

    def test_conversation_summary_tracks_history(self, intel):
        """Summary should reflect conversation state."""
        intel.conversation_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "run_simulation", "id": "t1", "input": {}},
            ]},
        ]
        summary = intel.get_conversation_summary()
        assert summary["message_count"] == 2
        assert "run_simulation" in summary["tools_used"]

    def test_no_api_key_raises(self, intel):
        """chat() should raise ValueError when no API key is set."""
        intel.api_key = ""
        with pytest.raises(ValueError, match="API key"):
            run_async(intel.chat("test"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Chat Loop — mocked Anthropic API
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatLoop:
    """Test the chat loop with mocked API responses."""

    def test_simple_text_response(self, intel):
        """Chat should return text when API responds with text only."""
        from unittest.mock import patch

        mock_response = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "Allegiant Stadium can hold 65,000 for NFL."}
            ],
        }

        with patch.object(intel, "_call_anthropic", return_value=mock_response):
            result = run_async(intel.chat("Tell me about Allegiant Stadium"))

        assert "Allegiant" in result["response"]
        assert result["tool_calls_made"] == []
        assert result["simulation_results"] is None

    def test_tool_use_then_text(self, intel):
        """Chat should execute tools and return final text."""
        from unittest.mock import patch

        # First API call: Claude wants to use a tool
        tool_response = {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Let me run that simulation."},
                {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "get_venue_info",
                    "input": {"venue_id": "list"},
                },
            ],
        }
        # Second API call: Claude responds with text
        final_response = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "There are 17 venues available."}
            ],
        }

        with patch.object(intel, "_call_anthropic", side_effect=[tool_response, final_response]):
            result = run_async(intel.chat("What venues do you have?"))

        assert "17 venues" in result["response"]
        assert "get_venue_info" in result["tool_calls_made"]

    def test_max_iterations_cap(self, intel):
        """Chat should stop after max iterations even if tools keep being called."""
        from unittest.mock import patch

        # Always return tool_use — should cap at 5
        looping_response = {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_loop",
                    "name": "get_engine_specs",
                    "input": {},
                },
            ],
        }

        call_count = 0

        def counting_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return looping_response

        with patch.object(intel, "_call_anthropic", side_effect=counting_call):
            result = run_async(intel.chat("infinite loop test"))

        assert call_count <= 5


# ═══════════════════════════════════════════════════════════════════════════════
#  /chat API Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatEndpoint:
    """Test the /chat API endpoint (mocked LLM)."""

    def test_chat_endpoint_exists(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        # Will fail with 500 (no API key) but should not 404
        r = client.post("/chat", json={"message": "test"})
        assert r.status_code != 404

    def test_chat_returns_503_without_key(self, monkeypatch):
        import time

        from fastapi.testclient import TestClient

        from api.main import app

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with TestClient(app) as client:
            deadline = time.monotonic() + 120.0
            while time.monotonic() < deadline:
                h = client.get("/health")
                if h.status_code == 200 and h.json().get("venues_loaded", 0) >= 1:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Engine did not become ready for /chat key test")

            r = client.post("/chat", json={"message": "test"})
        # 503 Service Unavailable lets the UI render a "configure intelligence" hint
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert ("API key" in detail) or ("provider unavailable" in detail.lower())

    def test_delete_conversation(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        # DELETE is idempotent: a well-formed (but unknown) UUID succeeds.
        # Malformed IDs are rejected with 400 by the path-param guard.
        r = client.delete("/chat/00000000-0000-4000-8000-000000000000")
        assert r.status_code == 200
        assert r.json()["status"] == "cleared"
        r2 = client.delete("/chat/nonexistent-id")
        assert r2.status_code == 400

    def test_chat_request_validation(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        # Missing required 'message' field
        r = client.post("/chat", json={})
        assert r.status_code == 422
