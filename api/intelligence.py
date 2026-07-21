"""
Vane Intelligence Interface — LLM orchestration layer.

Connects natural language to the simulation engine via Anthropic Claude API
with tool use and web search. The LLM doesn't simulate — it decides what
to simulate, interprets results, and communicates with operational authority.

Architecture:
  User message → Claude Sonnet (with tools) → tool calls → EngineBridge → results → Claude → response

The LLM has access to:
  1. Simulation tools (mapped to EngineBridge methods)
  2. Web search (for real-time data: events, traffic, weather alerts)
  3. System prompt with factor translation guide
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

import httpx

from api.models import (
    SimulationRequest,
    StressTestRequest,
    TemporalRequest,
    WhatIfRequest,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from api.engine_bridge import EngineBridge

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
# Override with env var if you want to experiment with models locally.
# Default to the current generally-available Sonnet model alias.
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are the Vane Intelligence Interface — an operational decision intelligence system for venue events built on queueing network theory and Monte Carlo simulation.

## Your Identity
You are not a chatbot. You are not a general assistant. You are a simulation-driven decision engine for venue operations.
You speak in a calm, executive, professional tone suitable for an ops director.
You do not run the math yourself — you decide what to simulate, orchestrate the simulation tools, and translate the numeric results into an operational recommendation.

## How You Communicate
- Do not use emojis or decorative symbols.
- Do not use markdown tables. Use short bullet lists instead.
- Do not use slang, casual phrasing, or hype. Avoid exclamation marks.
- Avoid filler. Prefer short sentences. Prefer concrete numbers.
- If you must make an assumption, state it explicitly and continue. Do not ask unnecessary questions.
- Never say "I think". Prefer: "the model estimates", "the model indicates", "under the current assumptions".
- Always include specific numbers with units.
- Include uncertainty whenever available: "mean 18.2 minutes (P10 12.1, P90 26.4)".
- Lead with the most operationally critical finding first.
- Provide 2-3 actionable recommendations, ranked by impact, with the expected effect quantified when possible.

## When to Ask Clarifying Questions
Ask ONLY when the missing information materially changes the simulation output. Do not ask generic questions.

Ask about:
- Venue (if not specified and multiple venues could match)
- Approximate attendance (if not stated or inferable)
- Event type (if ambiguous — "a show" could be concert or theater)
- Known operational constraints the user hasn't mentioned (gate closures, construction, special security)

Do NOT ask about:
- Weather (auto-fetch from forecast if date is given, use moderate default if not)
- Traffic (auto-computed from date/time if given)
- Exact staffing numbers (use venue defaults unless user specifies)
- Technical parameters (dt, n_simulations, etc.)

If only one piece of information is missing and you can infer a reasonable default, state your assumption and proceed.

## Factor Translation Guide
When the user mentions real-world factors not directly in the simulation parameters, translate them:

### Concurrent Events
Search for the event's expected attendance and location. Determine proximity to user's venue:
- Same building: traffic_factor += 0.5, transit reduction 0.2
- Adjacent (within 0.5 miles): traffic_factor += 0.3, transit reduction 0.1
- Same corridor (within 2 miles): traffic_factor += 0.15
- Different area (2+ miles): traffic_factor += 0.05
Also extend arrival window estimate and note to user.

### Road Closures / Construction
Search for specific road and closure extent. Identify which venue gates are accessed via that road.
- Reduce arrival rate at affected gates by 30-60%
- Recommend redistributing staff to unaffected gates
- Increase weather_factor by 0.05-0.1 (proxy for general disruption)

### Transit Disruptions
Identify which transit lines serve the venue.
- Monorail shutdown: transit_factor -= 0.15 to 0.25 for venues on the line
- Bus route suspended: transit_factor -= 0.05 to 0.1 per route
- Ride-share surge pricing: note for user, minimal simulation impact

### Demographics
- Families with children: note slower walking speeds, higher restroom demand
- Elderly audience: note extended service times
- College/young crowd: higher concession purchase rates
- International tourists: note longer security screening (document checks)
- For these, adjust weather_factor slightly as a proxy or note the limitation.

### Security Level Changes
- Enhanced/heightened: note slower screening rates to user, increase weather_factor as proxy
- Clear bag policy: note faster screening
- No bags allowed: note fastest screening possible

### Weather Extremes (beyond forecast)
- User mentions extreme heat concern: validate against forecast, note heat impact on HES
- Rain/storms: note impact on outdoor venues, covered venues less affected

When translating factors, always tell the user what adjustment you're making and why:
"CES is running concurrently at the Convention Center, about 2 miles north on the same Strip corridor. I'm increasing the traffic congestion factor by 0.15 to account for the additional 130,000 visitors affecting shared roadways."

## Available Venues
You have simulation models for 17 Las Vegas venues. When the user mentions a venue by name, match it to the closest venue_id. Common aliases:
- "Allegiant" / "the stadium" / "Raiders stadium" → allegiant_stadium
- "T-Mobile" / "the arena" → t_mobile_arena
- "The Sphere" / "MSG Sphere" → sphere_las_vegas
- "MGM Grand" / "Grand Garden" → mgm_grand_garden_arena
- "Convention Center" / "LVCC" → las_vegas_convention_center
- "Mandalay Bay" → mandalay_bay_events_center

If unsure, list the available venues and ask.

## Response Structure for Simulation Results
When presenting simulation results, always use this structure and headings exactly (keep it short):

Headline
- One sentence. Most operationally critical metric first.

Key metrics
- Wait time: mean, P10, P90 (minutes)
- HES: score/100 and grade
- Safety risk: score and label
- Revenue impact: current + (if available) future

Primary constraints
- Identify the controlling node(s) and why.

Recommendations (ranked)
- 2-3 actions. Each includes the expected improvement if available.

Next simulation
- One follow-up simulation to run next.

## What You Cannot Do
- You cannot access live sensor data or gate scanner feeds (future capability)
- You cannot guarantee prediction accuracy — always note this is a simulation model
- You do not model dynamic crowd rerouting within a single run
- Venue infrastructure data is estimated for most venues (medium-low confidence)
- You have not been validated against real venue measurements

Be honest about these limitations when relevant. Credibility comes from transparency.
"""

# Tool definitions for Anthropic API tool_use format
TOOLS = [
    {
        "name": "run_simulation",
        "description": "Run a Monte Carlo simulation on a venue's queueing network. Returns wait times, congestion probability, utilization, bottleneck analysis, safety risk score, human experience score, revenue impact, and prioritized recommendations. Use this when the user asks about expected conditions, wait times, congestion, staffing needs, or risk assessment for a specific event scenario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "string",
                    "description": "Venue identifier. Must be one of the available venue IDs (e.g., 'allegiant_stadium', 't_mobile_arena', 'sphere_las_vegas').",
                },
                "attendance": {
                    "type": "integer",
                    "description": "Expected attendance count.",
                },
                "event_type": {
                    "type": "string",
                    "enum": ["nfl", "concert", "concert_large", "sports", "boxing_mma", "convention", "festival", "theater"],
                    "description": "Type of event. Determines arrival pattern shape.",
                },
                "weather_factor": {
                    "type": "number",
                    "description": "Weather severity 0-1 (0=perfect, 1=extreme). Omit to auto-fetch from forecast if event_date is provided.",
                },
                "transit_factor": {
                    "type": "number",
                    "description": "Transit quality 0-1 (0=no transit, 1=excellent). Omit to auto-compute from traffic data.",
                },
                "event_date": {
                    "type": "string",
                    "description": "Event date in YYYY-MM-DD format. Used for automatic weather and traffic data.",
                },
                "event_time": {
                    "type": "string",
                    "description": "Event start time in HH:MM 24hr format. Used for time-of-day traffic adjustment.",
                },
                "avg_ticket_price": {
                    "type": "number",
                    "description": "Optional average ticket price in USD. Used for turnout-feasibility and revenue modeling.",
                },
                "service_rate_tier": {
                    "type": "string",
                    "enum": ["operational", "literature"],
                    "description": "Service-rate tier. 'operational' uses planning defaults informed by public event reporting and literature. 'literature' uses conservative published benchmarks.",
                },
                "n_simulations": {
                    "type": "integer",
                    "description": "Number of Monte Carlo trials. Default 1000. Use 500 for faster results.",
                },
            },
            "required": ["venue_id", "attendance", "event_type"],
        },
    },
    {
        "name": "run_temporal_simulation",
        "description": "Run a time-resolved simulation showing how conditions evolve across the full event lifecycle (arrival → event → egress). Returns temporal curves for wait times, congestion, HES, and safety risk at every time step, plus peak congestion timing and egress duration. Use when the user asks about WHEN congestion happens, how long it lasts, peak times, or temporal patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {"type": "string"},
                "attendance": {"type": "integer"},
                "event_type": {
                    "type": "string",
                    "enum": ["nfl", "concert", "concert_large", "sports", "boxing_mma", "convention", "festival", "theater"],
                },
                "event_duration_hours": {
                    "type": "number",
                    "description": "Duration of the event itself in hours. Default 3.0.",
                },
                "weather_factor": {"type": "number"},
                "transit_factor": {"type": "number"},
                "event_date": {"type": "string"},
                "event_time": {"type": "string"},
                "avg_ticket_price": {
                    "type": "number",
                    "description": "Optional average ticket price in USD. Used for turnout-feasibility and revenue modeling.",
                },
                "service_rate_tier": {
                    "type": "string",
                    "enum": ["operational", "literature"],
                    "description": "Service-rate tier. 'operational' uses planning defaults informed by public event reporting and literature. 'literature' uses conservative published benchmarks.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fast", "deep"],
                    "description": "'fast' for interactive results. 'deep' for full stochastic analysis with temporal uncertainty bands. Runtime depends on venue size and mode. Default 'fast'.",
                },
            },
            "required": ["venue_id", "attendance", "event_type"],
        },
    },
    {
        "name": "run_what_if",
        "description": "Compare a base scenario against a modified version to show the operational impact of a change. Use when the user asks 'what if', 'what happens if', or wants to evaluate a specific change like closing a gate, adding staff, or reducing capacity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {"type": "string"},
                "attendance": {"type": "integer"},
                "event_type": {
                    "type": "string",
                    "enum": ["nfl", "concert", "concert_large", "sports", "boxing_mma", "convention", "festival", "theater"],
                },
                "weather_factor": {"type": "number"},
                "transit_factor": {"type": "number"},
                "event_date": {"type": "string"},
                "event_time": {"type": "string"},
                "avg_ticket_price": {
                    "type": "number",
                    "description": "Optional average ticket price in USD. Used for turnout-feasibility and revenue modeling.",
                },
                "service_rate_tier": {
                    "type": "string",
                    "enum": ["operational", "literature"],
                    "description": "Service-rate tier. 'operational' uses planning defaults informed by public event reporting and literature. 'literature' uses conservative published benchmarks.",
                },
                "changes": {
                    "type": "object",
                    "description": "Changes to apply. Supported keys: 'disable_gates' (list of gate node IDs to close), 'add_servers' (dict of node_id → additional servers), 'reduce_staffing_pct' (float, fraction to reduce all servers), 'close_section' (node ID prefix to disable).",
                    "properties": {
                        "disable_gates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Gate node IDs to disable (e.g., ['gate_0', 'gate_1'])",
                        },
                        "add_servers": {
                            "type": "object",
                            "description": "Node ID → number of additional servers to add",
                        },
                        "reduce_staffing_pct": {
                            "type": "number",
                            "description": "Fraction to reduce all server counts (0.3 = 30% reduction)",
                        },
                        "close_section": {
                            "type": "string",
                            "description": "Node ID prefix — all nodes matching this prefix will be disabled",
                        },
                    },
                },
            },
            "required": ["venue_id", "attendance", "event_type", "changes"],
        },
    },
    {
        "name": "run_stress_tests",
        "description": "Run predefined extreme scenarios to assess venue resilience. Tests include gate failure, extreme heat, transit shutdown, staffing cuts, a high-load egress stress pass, and compound (multiple simultaneous) stress. Returns a resilience score and identifies the venue's most vulnerable scenario. Use when the user asks about worst case, resilience, risk assessment, or stress testing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {"type": "string"},
                "attendance": {"type": "integer"},
                "event_type": {
                    "type": "string",
                    "enum": ["nfl", "concert", "concert_large", "sports", "boxing_mma", "convention", "festival", "theater"],
                },
                "weather_factor": {"type": "number"},
                "transit_factor": {"type": "number"},
                "event_date": {"type": "string"},
                "avg_ticket_price": {
                    "type": "number",
                    "description": "Optional average ticket price in USD. Used for turnout-feasibility and revenue modeling.",
                },
                "service_rate_tier": {
                    "type": "string",
                    "enum": ["operational", "literature"],
                    "description": "Service-rate tier. 'operational' uses planning defaults informed by public event reporting and literature. 'literature' uses conservative published benchmarks.",
                },
                "tests": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["gate_failure", "extreme_heat", "transit_shutdown", "staffing_cut", "mass_egress", "compound"],
                    },
                    "description": "Which stress tests to run. Omit to run all.",
                },
            },
            "required": ["venue_id", "attendance", "event_type"],
        },
    },
    {
        "name": "get_venue_info",
        "description": "Get specifications and configuration for a venue, including capacity, infrastructure, gate counts, and queueing network topology. Use when the user asks about a venue's setup, capabilities, or available venues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "venue_id": {
                    "type": "string",
                    "description": "Venue identifier. Use 'list' to get all available venues.",
                },
            },
            "required": ["venue_id"],
        },
    },
    {
        "name": "get_engine_specs",
        "description": "Get the technical specification of the Vane simulation engine — methodology, capabilities, limitations, and data sources. Use when the user asks what Vane can do, how it works, or about its technical details.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class VaneIntelligence:
    """
    Orchestrates the conversation between user, LLM, and simulation engine.

    Handles the tool-use loop:
    1. Send user message + conversation history + tools to Claude
    2. If Claude returns tool_use blocks, execute them via EngineBridge
    3. Feed tool results back to Claude
    4. Repeat until Claude returns a final text response
    """

    def __init__(self, api_key: str = None, bridge: EngineBridge | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        # Share the process-wide bridge from FastAPI when provided (one venue load).
        # Lazy-import EngineBridge when absent so importing VaneIntelligence does not
        # pull scipy/simulation at FastAPI module load (keeps startup bind latency low).
        if bridge is not None:
            self.bridge = bridge
        else:
            from api.engine_bridge import EngineBridge as _EngineBridge

            self.bridge = _EngineBridge()
        self.conversation_history: list[dict] = []
        self._scenario: dict = {}

    def _scenario_context_block(self) -> str:
        """
        Return a compact, machine-readable context block for the current scenario.
        This is injected into the system prompt so Claude does not need to ask
        for venue/event type that the UI already knows.
        """
        if not self._scenario:
            return ""

        keys = [
            "venue_id",
            "venue_name",
            "event_type",
            "attendance",
            "attendance_requested",
            "event_date",
            "event_time",
            "weather_factor",
            "transit_factor",
            "avg_ticket_price",
            "service_rate_tier",
            "event_duration_hours",
        ]
        ctx = {k: self._scenario.get(k) for k in keys if self._scenario.get(k) is not None}
        if not ctx:
            return ""

        return (
            "\n\n## Scenario context (authoritative)\n"
            "The UI has selected these scenario parameters. Treat them as true unless the user explicitly overrides:\n"
            f"{json.dumps(ctx, indent=2)}\n"
        )

    def _input_or_scenario(self, tool_input: dict, key: str, default=None):
        """Prefer explicit tool input, then fall back to authoritative UI scenario context."""
        value = tool_input.get(key)
        if value is not None:
            return value
        scenario_value = self._scenario.get(key)
        if scenario_value is not None:
            return scenario_value
        return default

    def _required_input(self, tool_input: dict, key: str):
        """Resolve a required field from tool input or scenario context."""
        value = self._input_or_scenario(tool_input, key)
        if value is None:
            raise ValueError(
                f"Missing required field '{key}'. Provide it directly or include it in scenario context."
            )
        return value

    def _call_anthropic(self, messages: list[dict],
                        include_web_search: bool = True) -> dict:
        """
        Call the Anthropic Messages API with tools.

        Returns raw API response dict.
        """
        tools = list(TOOLS)
        if include_web_search:
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search",
            })

        payload = {
            "model": MODEL,
            "max_tokens": 4096,
            # Sonnet 5 enables adaptive thinking by default. This layer is a
            # tool-use narrator, so keep thinking off: it preserves the response
            # shape and leaves the full max_tokens for the reply.
            "thinking": {"type": "disabled"},
            "system": SYSTEM_PROMPT + self._scenario_context_block(),
            "tools": tools,
            "messages": messages,
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            # Anthropic requires this header; use the latest stable version.
            "anthropic-version": "2023-06-01",
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
            if response.status_code >= 400:
                # Help debugging misconfigured keys/models/payloads.
                logger.error(
                    "Anthropic API error %s: %s",
                    response.status_code,
                    response.text[:2000],
                )
            response.raise_for_status()
            return response.json()

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute a tool call by routing to the appropriate EngineBridge method.

        Returns the result as a JSON string for feeding back to Claude.
        """
        try:
            if tool_name == "run_simulation":
                req = SimulationRequest(
                    venue_id=self._required_input(tool_input, "venue_id"),
                    attendance=self._required_input(tool_input, "attendance"),
                    event_type=self._required_input(tool_input, "event_type"),
                    weather_factor=self._input_or_scenario(tool_input, "weather_factor"),
                    transit_factor=self._input_or_scenario(tool_input, "transit_factor"),
                    event_date=self._input_or_scenario(tool_input, "event_date"),
                    event_time=self._input_or_scenario(tool_input, "event_time"),
                    avg_ticket_price=self._input_or_scenario(tool_input, "avg_ticket_price"),
                    n_simulations=self._input_or_scenario(tool_input, "n_simulations"),
                    service_rate_tier=self._input_or_scenario(tool_input, "service_rate_tier", "operational"),
                )
                result = self.bridge.run_simulation(req)
                return json.dumps(self._trim_simulation_result(result), default=str)

            elif tool_name == "run_temporal_simulation":
                req = TemporalRequest(
                    venue_id=self._required_input(tool_input, "venue_id"),
                    attendance=self._required_input(tool_input, "attendance"),
                    event_type=self._required_input(tool_input, "event_type"),
                    event_duration_hours=self._input_or_scenario(tool_input, "event_duration_hours", 3.0),
                    weather_factor=self._input_or_scenario(tool_input, "weather_factor"),
                    transit_factor=self._input_or_scenario(tool_input, "transit_factor"),
                    event_date=self._input_or_scenario(tool_input, "event_date"),
                    event_time=self._input_or_scenario(tool_input, "event_time"),
                    avg_ticket_price=self._input_or_scenario(tool_input, "avg_ticket_price"),
                    mode=self._input_or_scenario(tool_input, "mode", "fast"),
                    service_rate_tier=self._input_or_scenario(tool_input, "service_rate_tier", "operational"),
                )
                result = self.bridge.run_temporal(req)
                return json.dumps(self._trim_temporal_result(result), default=str)

            elif tool_name == "run_what_if":
                req = WhatIfRequest(
                    venue_id=self._required_input(tool_input, "venue_id"),
                    attendance=self._required_input(tool_input, "attendance"),
                    event_type=self._required_input(tool_input, "event_type"),
                    weather_factor=self._input_or_scenario(tool_input, "weather_factor"),
                    transit_factor=self._input_or_scenario(tool_input, "transit_factor"),
                    event_date=self._input_or_scenario(tool_input, "event_date"),
                    event_time=self._input_or_scenario(tool_input, "event_time"),
                    avg_ticket_price=self._input_or_scenario(tool_input, "avg_ticket_price"),
                    service_rate_tier=self._input_or_scenario(tool_input, "service_rate_tier", "operational"),
                    changes=tool_input["changes"],
                )
                result = self.bridge.run_what_if(req)
                # Trim both base and modified simulation results
                if "base" in result and "simulation" in result["base"]:
                    result["base"] = self._trim_simulation_result(result["base"])
                if "modified" in result and "simulation" in result["modified"]:
                    result["modified"] = self._trim_simulation_result(result["modified"])
                return json.dumps(result, default=str)

            elif tool_name == "run_stress_tests":
                tests_raw = tool_input.get("tests")
                req = StressTestRequest(
                    venue_id=self._required_input(tool_input, "venue_id"),
                    attendance=self._required_input(tool_input, "attendance"),
                    event_type=self._required_input(tool_input, "event_type"),
                    weather_factor=self._input_or_scenario(tool_input, "weather_factor"),
                    transit_factor=self._input_or_scenario(tool_input, "transit_factor"),
                    event_date=self._input_or_scenario(tool_input, "event_date"),
                    avg_ticket_price=self._input_or_scenario(tool_input, "avg_ticket_price"),
                    service_rate_tier=self._input_or_scenario(tool_input, "service_rate_tier", "operational"),
                    tests=tests_raw,
                )
                result = self.bridge.run_stress_tests(req)
                # Trim per-stress-test simulation results
                for test_name, test_data in result.get("stress_results", {}).items():
                    if "simulation" in test_data:
                        test_data["simulation"] = self._trim_node_metrics(
                            test_data["simulation"]
                        )
                return json.dumps(result, default=str)

            elif tool_name == "get_venue_info":
                venue_id = tool_input["venue_id"]
                if venue_id == "list":
                    result = self.bridge.get_venue_list()
                else:
                    try:
                        result = self.bridge.get_venue_detail(venue_id)
                    except ValueError as e:
                        return json.dumps({
                            "success": False,
                            "error": str(e),
                        })
                return json.dumps(result, default=str)

            elif tool_name == "get_engine_specs":
                result = self.bridge.get_specs()
                return json.dumps(result, default=str)

            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                })

        except ValueError as e:
            return json.dumps({
                "success": False,
                "error": str(e),
            })
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return json.dumps({
                "success": False,
                "error": f"Tool execution failed: {type(e).__name__}: {e}",
            })

    def _trim_node_metrics(self, simulation: dict) -> dict:
        """
        Trim node_metrics in a simulation dict to top 5 by utilization.
        Returns a new dict with trimmed node_metrics.
        """
        if "node_metrics" not in simulation:
            return simulation

        node_metrics = simulation["node_metrics"]
        if len(node_metrics) <= 5:
            return simulation

        # Sort by utilization descending, keep top 5
        sorted_nodes = sorted(
            node_metrics.items(),
            key=lambda kv: kv[1].get("util_mean", 0),
            reverse=True,
        )
        trimmed = dict(sorted_nodes[:5])

        result = dict(simulation)
        result["node_metrics"] = trimmed
        result["_node_metrics_trimmed"] = True
        result["_total_nodes"] = len(node_metrics)
        return result

    def _trim_simulation_result(self, result: dict) -> dict:
        """
        Trim a simulation result to keep context size manageable.

        Keeps all top-level aggregate metrics and the full metrics dict.
        Limits per-node details to top 5 bottleneck nodes.
        """
        trimmed = dict(result)

        if "simulation" in trimmed:
            trimmed["simulation"] = self._trim_node_metrics(trimmed["simulation"])

        return trimmed

    def _trim_temporal_result(self, result: dict) -> dict:
        """
        Trim a temporal simulation result.

        The temporal dict can contain per-timestep data for 241 steps.
        Keep the summary curves but limit node_timeseries to top 5 nodes.
        """
        trimmed = dict(result)

        if "temporal" in trimmed:
            temporal = dict(trimmed["temporal"])

            # Trim node_timeseries to top 5 by peak wait
            if "node_timeseries" in temporal:
                nts = temporal["node_timeseries"]
                if len(nts) > 5:
                    # Sort by max wait value
                    def peak_wait(node_data):
                        waits = node_data.get("wait", [])
                        return max(waits) if waits else 0

                    sorted_nodes = sorted(
                        nts.items(), key=lambda kv: peak_wait(kv[1]), reverse=True
                    )
                    temporal["node_timeseries"] = dict(sorted_nodes[:5])
                    temporal["_node_timeseries_trimmed"] = True
                    temporal["_total_nodes"] = len(nts)

            trimmed["temporal"] = temporal

        # Trim the snapshot simulation in metrics path
        if "simulation" in trimmed:
            trimmed["simulation"] = self._trim_node_metrics(trimmed["simulation"])

        return trimmed

    async def chat(self, user_message: str, scenario: dict | None = None) -> dict:
        """
        Process a user message and return the Vane response.

        Handles the full tool-use loop: send to Claude, execute tool calls,
        feed results back, repeat until final text response.
        """
        if not self.api_key:
            raise ValueError(
                "No Anthropic API key configured. Set ANTHROPIC_API_KEY environment "
                "variable or pass api_key to VaneIntelligence()."
            )

        if scenario:
            # Update per-conversation scenario context (sent from the UI).
            if isinstance(scenario, dict):
                self._scenario.update({k: v for k, v in scenario.items() if v is not None})

        # Add user message
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        # Trim history if too long — keep last 20 messages
        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-20:]

        tool_calls_made: list[str] = []
        simulation_results: list[dict] = []
        web_searches: list[str] = []

        max_iterations = 5
        for _ in range(max_iterations):
            api_response = self._call_anthropic(self.conversation_history)

            stop_reason = api_response.get("stop_reason", "end_turn")
            content_blocks = api_response.get("content", [])

            # Add assistant response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": content_blocks,
            })

            # If no tool use, we're done
            if stop_reason != "tool_use":
                break

            # Process all tool_use blocks
            tool_results = []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_name = block["name"]
                    tool_input = block.get("input", {})
                    tool_id = block["id"]

                    tool_calls_made.append(tool_name)

                    if tool_name == "web_search":
                        query = tool_input.get("query", "")
                        web_searches.append(query)
                        # Web search is handled by the API itself — skip local execution
                        continue

                    result_str = self._execute_tool(tool_name, tool_input)

                    # Track simulation results
                    if tool_name in ("run_simulation", "run_temporal_simulation",
                                     "run_what_if", "run_stress_tests"):
                        try:
                            simulation_results.append(json.loads(result_str))
                        except json.JSONDecodeError:
                            pass

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    })

            if not tool_results:
                # All blocks were web_search (handled by API) or no tools — done
                break

            # Feed tool results back
            self.conversation_history.append({
                "role": "user",
                "content": tool_results,
            })

        # Extract final text response
        response_text = ""
        last_assistant = None
        for msg in reversed(self.conversation_history):
            if msg["role"] == "assistant":
                last_assistant = msg
                break

        if last_assistant:
            for block in last_assistant.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    response_text += block.get("text", "")
                elif isinstance(block, str):
                    response_text += block

        return {
            "response": response_text,
            "tool_calls_made": tool_calls_made,
            "simulation_results": simulation_results or None,
            "web_searches": web_searches or None,
        }

    def reset_conversation(self):
        """Clear conversation history for a new session."""
        self.conversation_history = []

    def get_conversation_summary(self) -> dict:
        """Return a summary of the current conversation state."""
        tools_used = []
        for msg in self.conversation_history:
            if msg["role"] == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tools_used.append(block["name"])
        return {
            "message_count": len(self.conversation_history),
            "tools_used": tools_used,
        }


# Convenience function for single-turn usage
async def ask_vane(question: str, api_key: str = None) -> str:
    """
    One-shot question to Vane. No conversation history.
    Returns just the text response.
    """
    intel = VaneIntelligence(api_key=api_key)
    result = await intel.chat(question)
    return result["response"]
