import { useState, useCallback, useRef } from 'react';
import { useVaneAPI } from './useVaneAPI';

function nowStr() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

const TOOL_LABELS = {
  run_simulation: 'Ran Monte Carlo simulation',
  run_temporal_simulation: 'Ran temporal simulation',
  run_what_if: 'Ran what-if analysis',
  run_stress_tests: 'Ran stress tests',
  get_venue_info: 'Retrieved venue data',
  get_engine_specs: 'Retrieved engine specs',
  web_search: 'Searched the web',
};

export function useSimulation() {
  const [log, setLog] = useState([]);
  const [simResults, setSimResults] = useState(null);
  const [baselineResults, setBaselineResults] = useState(null);
  const [temporalData, setTemporalData] = useState(null);
  const [stressData, setStressData] = useState(null);
  const [lastScenario, setLastScenario] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [viewMode, setViewMode] = useState('results'); // 'results' | 'stress'
  const [conversationId, setConversationId] = useState(null);
  const [lastRunId, setLastRunId] = useState(null);
  const api = useVaneAPI();
  const abortRef = useRef(false);

  const addLog = useCallback((icon, content, type = 'detail') => {
    setLog(prev => [{
      id: `${Date.now()}-${Math.random()}`,
      time: nowStr(),
      icon,
      content,
      type, // 'success' | 'running' | 'detail' | 'user' | 'error' | 'vane'
    }, ...prev]);
  }, []);

  // Flow 1: structured input — direct /simulate + /simulate/temporal calls
  const runSimulation = useCallback(async (params) => {
    if (isProcessing) return;
    abortRef.current = false;
    setIsProcessing(true);
    setBaselineResults(null);
    setLastScenario(params);

    const venueLabel = params.venue_name || params.venue_id;
    const dateStr = params.event_date ? ` · ${params.event_date}${params.event_time ? ` ${params.event_time}` : ''}` : '';
    addLog('→', `Scenario: ${(params.event_type || '').toUpperCase()} · ${(params.attendance || 0).toLocaleString()} attendance · ${venueLabel}${dateStr}`, 'user');
    addLog('◉', `Running Monte Carlo simulation (network engine)`, 'running');

    try {
      const simReq = {
        venue_id: params.venue_id,
        attendance: params.attendance,
        event_type: params.event_type,
        ...(params.event_date ? { event_date: params.event_date } : {}),
        ...(params.event_time ? { event_time: params.event_time } : {}),
        ...(params.weather_factor != null ? { weather_factor: params.weather_factor } : {}),
        ...(params.transit_factor != null ? { transit_factor: params.transit_factor } : {}),
        // Persist every run so users get a shareable URL. Backend no-ops
        // gracefully when Supabase isn't configured (no run_id in response).
        save: true,
      };

      const [simResp, temporalResp] = await Promise.all([
        api.simulate(simReq),
        api.simulateTemporal({ ...simReq, mode: 'fast' }).catch(() => null),
      ]);

      if (abortRef.current) return;

      const w = (simResp.parameters?.weather_factor ?? 0.3).toFixed(2);
      const t = (simResp.parameters?.transit_factor ?? 0.5).toFixed(2);
      addLog('┊', `Weather: ${w} · Transit: ${t}`, 'detail');

      setSimResults(simResp);
      setTemporalData(temporalResp?.temporal || null);
      setViewMode('results');
      setLastRunId(simResp.run_id || null);

      const ms = simResp.computation_time_ms != null ? ` · ${simResp.computation_time_ms.toFixed(0)}ms` : '';
      addLog('✓', `Simulation complete · 1,000 trials${ms} · ${venueLabel}`, 'success');
      if (simResp.run_id) {
        addLog('⤴', `Share: /runs/${simResp.run_id}`, 'detail');
      }
    } catch (err) {
      addLog('✗', `Simulation failed: ${err.message}`, 'error');
    } finally {
      setIsProcessing(false);
    }
  }, [isProcessing, api, addLog]);

  // Flow 2 & 3: natural language command → /chat → LLM tool use
  const runCommand = useCallback(async (text) => {
    if (!text.trim() || isProcessing) return;
    abortRef.current = false;
    setIsProcessing(true);

    addLog('→', text, 'user');

    const lower = text.toLowerCase();
    if (lower.includes('stress') || lower.includes('resilience')) {
      addLog('◉', 'Running stress test suite', 'running');
    } else if (lower.includes('what if') || (lower.includes('add') && lower.includes('lane'))) {
      addLog('◉', 'Running what-if analysis', 'running');
    } else {
      addLog('◉', 'Processing with Vane intelligence', 'running');
    }

    try {
      const scenario = lastScenario ? {
        venue_id: lastScenario.venue_id,
        venue_name: lastScenario.venue_name,
        event_type: lastScenario.event_type,
        attendance: lastScenario.attendance,
        event_date: lastScenario.event_date,
        event_time: lastScenario.event_time,
        weather_factor: lastScenario.weather_factor,
        transit_factor: lastScenario.transit_factor,
      } : null;

      const response = await api.chat(text, conversationId, scenario);
      if (abortRef.current) return;

      setConversationId(response.conversation_id);

      const tools = response.tool_calls_made || [];
      for (const tool of tools) {
        addLog('┊', TOOL_LABELS[tool] || tool, 'detail');
      }
      for (const q of response.web_searches || []) {
        addLog('┊', `Searched: ${typeof q === 'string' ? q : q?.query || 'web'}`, 'detail');
      }

      if (response.simulation_results?.length > 0) {
        const result = response.simulation_results[0];

        if (tools.includes('run_stress_tests')) {
          setStressData(result);
          setViewMode('stress');
        } else if (tools.includes('run_what_if')) {
          if (result?.baseline) {
            setBaselineResults(result.baseline);
            setSimResults(result.modified || result);
          } else {
            setSimResults(result);
          }
          setViewMode('results');
        } else {
          setSimResults(result);
          setTemporalData(result?.temporal || null);
          setBaselineResults(null);
          setViewMode('results');
        }
      }

      if (response.response) {
        addLog('◇', `Vane: ${response.response}`, 'vane');
      }
    } catch (err) {
      addLog('✗', `${err.message}. Ensure the backend is running on :8000 and ANTHROPIC_API_KEY is set.`, 'error');
    } finally {
      setIsProcessing(false);
    }
  }, [isProcessing, conversationId, api, addLog]);

  // Flow: stress test from ScenarioBar button
  const runStressTest = useCallback(async (params) => {
    if (isProcessing) return;
    abortRef.current = false;
    setIsProcessing(true);
    setLastScenario(params);

    const venueLabel = params.venue_name || params.venue_id;
    addLog('→', `Stress test: ${venueLabel} · ${(params.event_type || '').toUpperCase()}`, 'user');
    addLog('◉', 'Running stress test suite (6 scenarios)', 'running');

    try {
      const result = await api.stressTest({
        venue_id: params.venue_id,
        attendance: params.attendance,
        event_type: params.event_type,
      });

      if (abortRef.current) return;
      setStressData(result);
      setViewMode('stress');
      const score = result.resilience_score != null ? ` · Resilience: ${result.resilience_score.toFixed(0)}/100` : '';
      addLog('✓', `Stress tests complete${score} · ${venueLabel}`, 'success');
    } catch (err) {
      addLog('✗', `Stress test failed: ${err.message}`, 'error');
    } finally {
      setIsProcessing(false);
    }
  }, [isProcessing, api, addLog]);

  const backToResults = useCallback(() => setViewMode('results'), []);

  const reset = useCallback(async () => {
    if (conversationId) {
      try { await api.deleteConversation(conversationId); } catch {}
    }
    abortRef.current = true;
    setLog([]);
    setSimResults(null);
    setBaselineResults(null);
    setTemporalData(null);
    setStressData(null);
    setLastScenario(null);
    setIsProcessing(false);
    setViewMode('results');
    setConversationId(null);
    setLastRunId(null);
  }, [conversationId, api]);

  // Load a previously-persisted run by id (used by the /runs/:id route).
  // Reconstructs the result state so every downstream panel renders as if
  // the user had just run the scenario themselves.
  const loadRun = useCallback(async (runId) => {
    if (!runId) return;
    setIsProcessing(true);
    try {
      const row = await api.getRun(runId);
      const req = row?.request || {};
      setLastScenario({
        venue_id: req.venue_id,
        venue_name: row?.venue_id,
        attendance: req.attendance,
        event_type: req.event_type,
        event_date: req.event_date,
        event_time: req.event_time,
        weather_factor: req.weather_factor,
        transit_factor: req.transit_factor,
      });
      setSimResults(row?.response || null);
      setTemporalData((row?.response?.temporal) || null);
      setLastRunId(row?.id || runId);
      setViewMode('results');
      addLog('↩', `Loaded shared run · ${row?.venue_id || 'scenario'}`, 'detail');
    } catch (err) {
      addLog('✗', `Could not load run: ${err.message}`, 'error');
    } finally {
      setIsProcessing(false);
    }
  }, [api, addLog]);

  return {
    log,
    simResults,
    baselineResults,
    temporalData,
    stressData,
    isProcessing,
    viewMode,
    hasResults: !!(simResults || stressData),
    lastRunId,
    runSimulation,
    runCommand,
    runStressTest,
    backToResults,
    reset,
    loadRun,
  };
}
