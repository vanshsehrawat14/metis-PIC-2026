import { useState, useCallback, useRef, useEffect } from 'react';
import { useVaneAPI } from './useVaneAPI';

const CHAT_ID_KEY = 'vane.conversation_id';

function readStoredConversationId() {
  try {
    return window.localStorage.getItem(CHAT_ID_KEY) || null;
  } catch {
    return null;
  }
}

function writeStoredConversationId(id) {
  try {
    if (id) window.localStorage.setItem(CHAT_ID_KEY, id);
    else window.localStorage.removeItem(CHAT_ID_KEY);
  } catch {
    // swallow — private-mode browsers block localStorage; chat still works in-memory.
  }
}

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [conversationId, setConversationId] = useState(readStoredConversationId);
  const [simulationResults, setSimulationResults] = useState(null);
  const [temporalData, setTemporalData] = useState(null);
  const [stressTestData, setStressTestData] = useState(null);
  const [activeTools, setActiveTools] = useState([]);
  const api = useVaneAPI();
  const abortRef = useRef(false);

  // Persist the conversation id so chat survives page refresh / device-switch
  // when the backend is wired to Supabase (write-through cache rehydrates
  // the Anthropic message history server-side).
  useEffect(() => {
    writeStoredConversationId(conversationId);
  }, [conversationId]);

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || isProcessing) return;
    abortRef.current = false;

    const userMsg = { role: 'user', content: text, timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setIsProcessing(true);
    setActiveTools([]);

    try {
      // Show tool indicators based on message content heuristics
      const lower = text.toLowerCase();
      if (lower.includes('stress') || lower.includes('resilience')) {
        setActiveTools(['Running stress tests...']);
      } else if (lower.includes('temporal') || lower.includes('timeline') || lower.includes('when')) {
        setActiveTools(['Running temporal simulation...']);
      } else if (lower.includes('simulat') || lower.includes('wait') || lower.includes('congestion')) {
        setActiveTools(['Running simulation...']);
      }

      const response = await api.chat(text, conversationId);
      if (abortRef.current) return;

      setConversationId(response.conversation_id);

      // Extract tools actually used
      const tools = response.tool_calls_made || [];
      const toolLabels = tools.map(t => {
        const labels = {
          run_simulation: 'Ran Monte Carlo simulation',
          run_temporal_simulation: 'Ran temporal simulation',
          run_what_if: 'Ran what-if analysis',
          run_stress_tests: 'Ran stress tests',
          get_venue_info: 'Retrieved venue data',
          get_engine_specs: 'Retrieved engine specs',
          web_search: 'Searched the web',
        };
        return labels[t] || t;
      });

      // Process simulation results
      if (response.simulation_results?.length > 0) {
        const result = response.simulation_results[0];
        setSimulationResults(result);

        if (result?.temporal) {
          setTemporalData(result.temporal);
        }

        if (tools.includes('run_stress_tests')) {
          setStressTestData(result);
        }
      }

      // Web searches done by Vane
      const searchLabels = (response.web_searches || []).map(q =>
        `Searched: ${typeof q === 'string' ? q : q?.query || 'web'}`
      );

      const vaneMsg = {
        role: 'assistant',
        content: response.response,
        tools: [...toolLabels, ...searchLabels],
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev, vaneMsg]);
    } catch (err) {
      const raw = String(err?.message || err || '');
      const isNoKey = /Anthropic API key/i.test(raw);
      const content = isNoKey
        ? 'The chat requires an Anthropic API key. Copy `.env.example` to `.env` at the project root, paste your key after `ANTHROPIC_API_KEY=`, then restart the backend. The key stays on your machine and is git-ignored.'
        : `System error: ${raw}. Verify the FastAPI backend is running at http://127.0.0.1:8000.`;
      const errorMsg = {
        role: 'assistant',
        content,
        isError: true,
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsProcessing(false);
      setActiveTools([]);
    }
  }, [isProcessing, conversationId, api]);

  const reset = useCallback(async () => {
    if (conversationId) {
      try { await api.deleteConversation(conversationId); } catch {}
    }
    abortRef.current = true;
    setMessages([]);
    setIsProcessing(false);
    setConversationId(null);
    writeStoredConversationId(null);
    setSimulationResults(null);
    setTemporalData(null);
    setStressTestData(null);
    setActiveTools([]);
  }, [conversationId, api]);

  return {
    messages,
    isProcessing,
    activeTools,
    simulationResults,
    temporalData,
    stressTestData,
    conversationId,
    sendMessage,
    reset,
  };
}
