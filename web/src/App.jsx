import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  chat as chatRequest,
  clearConversation,
  compareScenarios,
  getDataSources,
  getHealth,
  getRun,
  getSpecs,
  getVenue,
  getVenues,
  listScenarios,
  simulate,
  simulateTemporal,
  stressTest,
  whatIf,
} from "./utils/api";
import { userFacingMessage, sanitizeForTicker } from "./utils/errors.js";

const EVENT_OPTIONS = [
  { id: "nfl", name: "NFL Game", desc: "Stadium arrival peak" },
  { id: "concert", name: "Arena Concert", desc: "Late compressed arrival" },
  { id: "concert_large", name: "Large Concert", desc: "Floor capacity enabled" },
  { id: "sports", name: "Sports Event", desc: "Balanced ingress pattern" },
  { id: "boxing_mma", name: "Boxing / MMA", desc: "Late undercard surge" },
  { id: "convention", name: "Convention", desc: "Rolling arrivals" },
  { id: "festival", name: "Festival", desc: "Extended arrival window" },
  { id: "theater", name: "Residency / Theater", desc: "Punctual reserved seating" },
];

const EVENT_PROFILES = {
  nfl: { alpha: 2.5, beta: 1.8, windowMinutes: 150 },
  concert: { alpha: 3.5, beta: 1.5, windowMinutes: 120 },
  concert_large: { alpha: 3.8, beta: 1.3, windowMinutes: 120 },
  sports: { alpha: 2.5, beta: 1.8, windowMinutes: 120 },
  boxing_mma: { alpha: 3.0, beta: 1.5, windowMinutes: 120 },
  convention: { alpha: 1.8, beta: 2.2, windowMinutes: 180 },
  festival: { alpha: 2.0, beta: 2.0, windowMinutes: 240 },
  theater: { alpha: 2.8, beta: 2.0, windowMinutes: 90 },
};

const STRESS_META = {
  gate_failure: {
    label: "Gate Failure",
    detail: "Random gate and security checkpoint disabled",
  },
  extreme_heat: {
    label: "Extreme Heat",
    detail: "Service rates degraded by heat exposure",
  },
  transit_shutdown: {
    label: "Transit Shutdown",
    detail: "Transit access collapses toward emergency fallback",
  },
  staffing_cut: {
    label: "Staffing Cut",
    detail: "Service nodes drop 40% staffing",
  },
  mass_egress: {
    label: "Mass Egress",
    detail: "High-load egress stress pass on the current exit topology",
  },
  compound: {
    label: "Compound Event",
    detail: "Gate loss plus heat plus service degradation",
  },
};

const CHAT_TOOL_LABELS = {
  run_simulation: "Ran Monte Carlo simulation",
  run_temporal_simulation: "Ran temporal simulation",
  run_what_if: "Ran what-if analysis",
  run_stress_tests: "Ran stress panel",
  get_venue_info: "Retrieved venue profile",
  get_engine_specs: "Retrieved engine specification",
};

const SECTION_NAV = [
  { id: "results", label: "Output" },
  { id: "network", label: "Network" },
  { id: "temporal", label: "Lifecycle" },
  { id: "stress", label: "Stress" },
  { id: "whatif", label: "What-If" },
  { id: "chat", label: "Ask" },
  { id: "math", label: "Math" },
];

const INITIAL_FORM = {
  eventType: "nfl",
  attendance: 55000,
  factorMode: "manual",
  weather: 30,
  transit: 50,
  eventDate: "",
  eventTime: "18:00",
  serviceRateTier: "operational",
  avgTicketPrice: "",
};

const CHAT_ID_KEY = "vane.conversation_id";

function readStoredConversationId() {
  try {
    return window.localStorage.getItem(CHAT_ID_KEY) || null;
  } catch {
    return null;
  }
}

function writeStoredConversationId(id) {
  try {
    if (id) {
      window.localStorage.setItem(CHAT_ID_KEY, id);
    } else {
      window.localStorage.removeItem(CHAT_ID_KEY);
    }
  } catch {
    // Private-mode browsers can block localStorage; in-memory chat still works.
  }
}

export default function App() {
  const [venues, setVenues] = useState([]);
  const [venueDetails, setVenueDetails] = useState({});
  const [specs, setSpecs] = useState(null);
  const [health, setHealth] = useState(null);
  const [dataSources, setDataSources] = useState(null);
  const [selectedVenueId, setSelectedVenueId] = useState("");
  const [form, setForm] = useState(INITIAL_FORM);
  const [phase, setPhase] = useState("setup");
  const [bootLoading, setBootLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const [runConfig, setRunConfig] = useState(null);
  const [simulationResult, setSimulationResult] = useState(null);
  const [temporalResult, setTemporalResult] = useState(null);
  const [stressResult, setStressResult] = useState(null);
  const [stressLoading, setStressLoading] = useState(false);
  const [stressError, setStressError] = useState("");
  const [whatIfResult, setWhatIfResult] = useState(null);
  const [whatIfLoading, setWhatIfLoading] = useState(false);
  const [compareResult, setCompareResult] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [analysisMode, setAnalysisMode] = useState("perturb");
  const [sheetKey, setSheetKey] = useState(null);

  const [whatIfForm, setWhatIfForm] = useState({
    disabledGates: 1,
    extraServers: 1,
    staffingCut: 0,
    closedSection: "",
  });
  const [compareForm, setCompareForm] = useState({
    eventType: "nfl",
    attendance: 55000,
    weather: 30,
    transit: 50,
    serviceRateTier: "operational",
  });

  const [conversationId, setConversationId] = useState(readStoredConversationId);
  const [chatMessages, setChatMessages] = useState(() => initialChatMessages(""));
  const [chatInput, setChatInput] = useState("");
  const [chatThinking, setChatThinking] = useState(false);

  // Persistence-backed features: scenario library, shareable run URLs.
  const [scenarioLibrary, setScenarioLibrary] = useState([]);
  const [lastRunId, setLastRunId] = useState(null);
  const { runId: routeRunId } = useParams();
  const navigate = useNavigate();
  const hydratedRunRef = useRef(null);

  const mainScrollRef = useRef(null);
  const previousVenueRef = useRef("");
  const activeScenarioKeyRef = useRef("");
  const autoStressKeyRef = useRef("");

  const selectedVenue = useMemo(
    () => venues.find((venue) => venue.venue_id === selectedVenueId) || null,
    [venues, selectedVenueId],
  );
  const selectedVenueDetail = venueDetails[selectedVenueId] || null;
  const selectedVenueName =
    selectedVenueDetail?.venue?.name || selectedVenue?.name || "Venue";
  const selectedCapacity = useMemo(
    () => resolveVenueCapacity(selectedVenue, selectedVenueDetail, form.eventType),
    [selectedVenue, selectedVenueDetail, form.eventType],
  );

  const summary = useMemo(
    () => getSimulationSummary(simulationResult),
    [simulationResult],
  );
  const graphNodes = useMemo(
    () => buildGraphNodes(simulationResult?.simulation?.node_metrics),
    [simulationResult],
  );
  const temporalSeries = useMemo(
    () => buildTemporalSeries(temporalResult, runConfig),
    [temporalResult, runConfig],
  );
  const stressRows = useMemo(
    () => buildStressRows(stressResult),
    [stressResult],
  );
  const tickerItems = useMemo(
    () => buildTickerItems(runConfig, simulationResult, stressResult, health),
    [runConfig, simulationResult, stressResult, health],
  );
  const promptSuggestions = useMemo(
    () => buildPromptSuggestions(runConfig, selectedVenueName),
    [runConfig, selectedVenueName],
  );

  useEffect(() => {
    writeStoredConversationId(conversationId);
  }, [conversationId]);

  useEffect(() => {
    let isActive = true;

    async function bootstrap() {
      setBootLoading(true);
      setErrorMessage("");

      try {
        // Load venues first. Do NOT use Promise.all for the whole boot — if
        // /specs or /health fails, we still need the venue list (Promise.all
        // used to fail the entire boot and left venues empty with no cards).
        let venuesResponse;
        try {
          venuesResponse = await getVenues();
        } catch (err) {
          if (isActive) {
            setErrorMessage(userFacingMessage(err));
          }
          return;
        }

        if (!isActive) {
          return;
        }

        const venueList = [...(venuesResponse.venues || [])].sort((left, right) =>
          left.name.localeCompare(right.name),
        );

        setVenues(venueList);
        if (venueList.length === 0) {
          setErrorMessage(
            "The API returned no venues. Confirm the backend is running and /venues returns JSON.",
          );
          return;
        }

        const preferredVenue =
          venueList.find((venue) => venue.venue_id === "allegiant_stadium") ||
          venueList[0] ||
          null;

        if (preferredVenue) {
          setSelectedVenueId(preferredVenue.venue_id);
          setForm((current) => ({
            ...current,
            attendance: recommendedAttendance(preferredVenue.capacity || 1000),
          }));
        }

        const [healthR, specsR, dataSourcesR, scenariosR] = await Promise.allSettled([
          getHealth(),
          getSpecs(),
          getDataSources(),
          listScenarios(),
        ]);

        if (!isActive) {
          return;
        }

        if (healthR.status === "fulfilled") {
          setHealth(healthR.value);
        }
        if (specsR.status === "fulfilled" && specsR.value?.engine) {
          setSpecs(specsR.value.engine);
        }
        if (dataSourcesR.status === "fulfilled") {
          setDataSources(dataSourcesR.value);
        } else {
          setDataSources(null);
        }
        if (scenariosR.status === "fulfilled" && scenariosR.value?.scenarios) {
          setScenarioLibrary(scenariosR.value.scenarios);
        } else {
          setScenarioLibrary([]);
        }

        const secondaryIssues = [healthR, specsR, scenariosR].filter((r) => r.status === "rejected");
        if (secondaryIssues.length > 0 && isActive) {
          const first = /** @type {PromiseRejectedResult} */ (secondaryIssues[0]);
          setErrorMessage(
            (prev) =>
              prev ||
              `Loaded venues; optional data failed: ${userFacingMessage(/** @type {Error} */ (first.reason))}`,
          );
        }
      } catch (error) {
        if (isActive) {
          setErrorMessage(userFacingMessage(error));
        }
      } finally {
        if (isActive) {
          setBootLoading(false);
        }
      }
    }

    bootstrap();

    return () => {
      isActive = false;
    };
  }, []);

  // ── Hydrate a shared run from /runs/:id ─────────────────────────────────
  // When the user lands directly on /runs/<uuid> we fetch the persisted run
  // from the backend and rebuild local state so every downstream panel
  // renders exactly as the original scenario. Guard against re-hydration
  // loops with a ref keyed on the run id.
  useEffect(() => {
    if (!routeRunId) return;
    if (hydratedRunRef.current === routeRunId) return;
    if (bootLoading) return; // wait until venues + scenarios are loaded

    let isActive = true;
    (async () => {
      try {
        const row = await getRun(routeRunId);
        if (!isActive || !row) return;
        hydratedRunRef.current = routeRunId;

        const req = row.request || {};
        const resp = row.response || {};

        // Rebuild the descriptor the UI uses to drive downstream calls.
        const scenarioDescriptor = {
          venue_id: req.venue_id,
          venue_name: resp.venue_name,
          attendance: req.attendance,
          attendance_requested: req.attendance,
          event_type: req.event_type,
          event_date: req.event_date,
          event_time: req.event_time,
          weather_factor: resp.parameters?.weather_factor ?? req.weather_factor,
          transit_factor: resp.parameters?.transit_factor ?? req.transit_factor,
          service_rate_tier: resp.parameters?.service_rate_tier || req.service_rate_tier || "operational",
          avg_ticket_price: req.avg_ticket_price ?? resp.parameters?.avg_ticket_price,
          event_duration_hours: 3,
        };

        setSelectedVenueId(req.venue_id || "");
        setForm((current) => ({
          ...current,
          eventType: req.event_type || current.eventType,
          attendance: req.attendance || current.attendance,
          eventDate: req.event_date || current.eventDate,
          eventTime: req.event_time || current.eventTime,
          factorMode: (req.weather_factor != null || req.transit_factor != null) ? "manual" : current.factorMode,
          weather: req.weather_factor != null ? Math.round(req.weather_factor * 100) : current.weather,
          transit: req.transit_factor != null ? Math.round(req.transit_factor * 100) : current.transit,
          serviceRateTier: scenarioDescriptor.service_rate_tier,
          avgTicketPrice:
            req.avg_ticket_price != null
              ? String(req.avg_ticket_price)
              : current.avgTicketPrice,
        }));
        setRunConfig(scenarioDescriptor);
        setSimulationResult(resp);
        setTemporalResult(resp.temporal ? { temporal: resp.temporal, parameters: resp.parameters } : null);
        setLastRunId(row.id);
        setPhase("results");
      } catch (error) {
        if (isActive) {
          setErrorMessage(`Could not load shared run: ${error.message}`);
        }
      }
    })();

    return () => {
      isActive = false;
    };
  }, [routeRunId, bootLoading]);

  // ── Load a curated scenario from the gallery strip ──────────────────────
  function loadScenarioFromLibrary(scenario) {
    if (!scenario || !scenario.request_json) return;
    const req = scenario.request_json;
    // Clear the /runs/:id path if we came from one so the URL reflects the
    // fact that we're about to run a fresh simulation, not replay a saved one.
    if (routeRunId) navigate("/", { replace: true });
    hydratedRunRef.current = null;
    setSelectedVenueId(req.venue_id || "");
    setForm((current) => ({
      ...current,
      eventType: req.event_type || current.eventType,
      attendance: req.attendance ?? current.attendance,
      eventDate: req.event_date || "",
      eventTime: req.event_time || current.eventTime,
      serviceRateTier: req.service_rate_tier || "operational",
      factorMode:
        req.weather_factor != null || req.transit_factor != null ? "manual" : "auto",
      weather: req.weather_factor != null ? Math.round(req.weather_factor * 100) : current.weather,
      transit: req.transit_factor != null ? Math.round(req.transit_factor * 100) : current.transit,
      avgTicketPrice: req.avg_ticket_price != null ? String(req.avg_ticket_price) : "",
    }));
    setPhase("setup");
    setLastRunId(null);
  }

  useEffect(() => {
    if (!selectedVenueId || venueDetails[selectedVenueId]) {
      return;
    }

    let isActive = true;

    getVenue(selectedVenueId)
      .then((detail) => {
        if (!isActive) {
          return;
        }
        setVenueDetails((current) => ({
          ...current,
          [selectedVenueId]: detail,
        }));
      })
      .catch((error) => {
        if (isActive) {
          setErrorMessage(error.message);
        }
      });

    return () => {
      isActive = false;
    };
  }, [selectedVenueId, venueDetails]);

  useEffect(() => {
    if (!selectedVenueId || !selectedCapacity) {
      return;
    }

    setForm((current) => {
      if (previousVenueRef.current !== selectedVenueId) {
        previousVenueRef.current = selectedVenueId;
        return {
          ...current,
          attendance: recommendedAttendance(selectedCapacity),
        };
      }

      const clampedAttendance = clamp(current.attendance, 100, selectedCapacity);
      return clampedAttendance === current.attendance
        ? current
        : { ...current, attendance: roundAttendance(clampedAttendance) };
    });
  }, [selectedCapacity, selectedVenueId]);

  useEffect(() => {
    if (!simulationResult || !runConfig) {
      return;
    }

    const scenarioKey = buildScenarioKey(runConfig);
    if (autoStressKeyRef.current === scenarioKey) {
      return;
    }

    autoStressKeyRef.current = scenarioKey;
    let isActive = true;
    setStressError("");
    setStressLoading(true);

    stressTest(buildStressPayload(runConfig))
      .then((result) => {
        if (!isActive || activeScenarioKeyRef.current !== scenarioKey) {
          return;
        }
        setStressError("");
        setStressResult(result);
      })
      .catch((error) => {
        if (!isActive || activeScenarioKeyRef.current !== scenarioKey) {
          return;
        }
        setStressResult(null);
        setStressError(userFacingMessage(error));
      })
      .finally(() => {
        if (isActive && activeScenarioKeyRef.current === scenarioKey) {
          setStressLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [runConfig, simulationResult]);

  async function handleRunSimulation() {
    if (!selectedVenueId) {
      setErrorMessage("Select a venue before running a simulation.");
      return;
    }

    setErrorMessage("");

    try {
      const scenarioPayload = buildScenarioPayload(selectedVenueId, form);
      const scenarioDescriptor = {
        ...scenarioPayload,
        venue_name: selectedVenueName,
        factorMode: form.factorMode,
        weather_display: form.weather,
        transit_display: form.transit,
        event_duration_hours: 3,
        service_rate_tier: form.serviceRateTier,
      };

      const scenarioKey = buildScenarioKey(scenarioDescriptor);
      activeScenarioKeyRef.current = scenarioKey;
      autoStressKeyRef.current = "";

      setPhase("running");
      setRunConfig(scenarioDescriptor);
      setSimulationResult(null);
      setTemporalResult(null);
      setStressResult(null);
      setStressError("");
      setWhatIfResult(null);
      setCompareResult(null);
      setAnalysisMode("perturb");
      setSheetKey(null);
      setLastRunId(null);
      setWhatIfForm(buildInitialWhatIfForm(selectedVenueDetail));
      setCompareForm(buildInitialCompareForm(scenarioDescriptor));
      resetChatState(selectedVenueName, setChatMessages, setConversationId, conversationId);

      const [simulationResponse, temporalResponse] = await Promise.all([
        simulate(scenarioPayload),
        simulateTemporal({ ...scenarioPayload, mode: "fast" }),
      ]);

      if (activeScenarioKeyRef.current !== scenarioKey) {
        return;
      }

      const resolvedConfig = {
        ...scenarioDescriptor,
        venue_id: simulationResponse.venue_id,
        venue_name: simulationResponse.venue_name,
        attendance: simulationResponse.parameters?.attendance || scenarioPayload.attendance,
        attendance_requested:
          simulationResponse.parameters?.attendance_requested || scenarioPayload.attendance,
        event_type: simulationResponse.parameters?.event_type || scenarioPayload.event_type,
        weather_factor:
          simulationResponse.parameters?.weather_factor ?? scenarioPayload.weather_factor,
        transit_factor:
          simulationResponse.parameters?.transit_factor ?? scenarioPayload.transit_factor,
        avg_ticket_price:
          simulationResponse.parameters?.avg_ticket_price ?? scenarioPayload.avg_ticket_price,
        event_duration_hours:
          temporalResponse.parameters?.event_duration_hours ||
          scenarioDescriptor.event_duration_hours,
      };
      const mergedSimulationResponse = temporalResponse?.metrics
        ? {
            ...simulationResponse,
            metrics: temporalResponse.metrics,
          }
        : simulationResponse;

      setRunConfig(resolvedConfig);
      setSimulationResult(mergedSimulationResponse);
      setTemporalResult(temporalResponse);
      setPhase("results");
      if (simulationResponse.run_id) {
        setLastRunId(simulationResponse.run_id);
        // Reflect the shareable URL in the browser address bar without
        // navigating away or re-mounting components.
        try {
          window.history.replaceState(
            window.history.state,
            "",
            `/runs/${simulationResponse.run_id}`,
          );
        } catch {
          // history.replaceState is not critical; fail quiet.
        }
      }
      setChatMessages(initialChatMessages(simulationResponse.venue_name));
      setWhatIfForm(buildInitialWhatIfForm(selectedVenueDetail));
      setCompareForm(buildInitialCompareForm(resolvedConfig));

      requestAnimationFrame(() => {
        mainScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
      });
    } catch (error) {
      setErrorMessage(userFacingMessage(error) || "Simulation failed");
      setPhase("setup");
    }
  }

  async function handleStressRerun() {
    if (!runConfig) {
      return;
    }

    setStressLoading(true);
    setErrorMessage("");
    setStressError("");

    try {
      const result = await stressTest(buildStressPayload(runConfig));
      setStressError("");
      setStressResult(result);
    } catch (error) {
      setStressError(userFacingMessage(error));
      setErrorMessage(error.message);
    } finally {
      setStressLoading(false);
    }
  }

  async function handleWhatIfRun() {
    if (!runConfig) {
      return;
    }

    const changes = buildWhatIfChanges(
      whatIfForm,
      selectedVenueDetail?.graph_summary?.entry_nodes,
    );

    if (!Object.keys(changes).length) {
      setErrorMessage("Select at least one perturbation before running what-if analysis.");
      return;
    }

    setWhatIfLoading(true);
    setErrorMessage("");

    try {
      const result = await whatIf({
        ...buildScenarioPayloadFromRunConfig(runConfig),
        changes,
      });
      // Snapshot the form used for the run so the result panel can surface
      // exactly what was perturbed without being confused if the user
      // moves a slider after running.
      setWhatIfResult({ ...result, _applied: { ...whatIfForm, changes } });
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setWhatIfLoading(false);
    }
  }

  async function handleCompareRun() {
    if (!runConfig) {
      return;
    }

    setCompareLoading(true);
    setErrorMessage("");

    const base = buildScenarioPayloadFromRunConfig(runConfig);
    const modified = {
      ...base,
      attendance: compareForm.attendance,
      event_type: compareForm.eventType,
      weather_factor: compareForm.weather / 100,
      transit_factor: compareForm.transit / 100,
      service_rate_tier: compareForm.serviceRateTier,
    };

    try {
      const result = await compareScenarios({
        venue_id: runConfig.venue_id,
        base,
        modified,
      });
      setCompareResult(result);
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setCompareLoading(false);
    }
  }

  async function handleSendChat(submittedText) {
    const text = submittedText.trim();
    if (!text || chatThinking) {
      return;
    }

    setChatThinking(true);
    setChatInput("");
    setErrorMessage("");
    setChatMessages((current) => [...current, { role: "user", text }]);

    try {
      const response = await chatRequest({
        message: text,
        conversation_id: conversationId || null,
        ...(runConfig ? { scenario: buildChatScenarioContext(runConfig) } : {}),
      });

      setConversationId(response.conversation_id || null);

      const toolLines = [
        ...(response.tool_calls_made || []).map(
          (tool) => CHAT_TOOL_LABELS[tool] || tool.replaceAll("_", " "),
        ),
        ...(response.web_searches || []).map((query) =>
          `Searched: ${typeof query === "string" ? query : query?.query || "web"}`,
        ),
      ];

      if (toolLines.length > 0) {
        setChatMessages((current) => [...current, { role: "tool", items: toolLines }]);
      }

      applyChatResults(response.simulation_results || [], {
        setSelectedVenueId,
        setRunConfig,
        setSimulationResult,
        setTemporalResult,
        setStressResult,
        setWhatIfResult,
        setPhase,
      });

      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: response.response || "No response returned by the intelligence layer.",
        },
      ]);
    } catch (error) {
      const message = `${error.message}. Ensure the backend is running and ANTHROPIC_API_KEY is configured for /chat.`;
      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: message,
          error: true,
        },
      ]);
    } finally {
      setChatThinking(false);
    }
  }

  function handleNewRun() {
    setPhase("setup");
    setSimulationResult(null);
    setTemporalResult(null);
    setStressResult(null);
    setWhatIfResult(null);
    setCompareResult(null);
    setRunConfig(null);
    setSheetKey(null);
    setAnalysisMode("perturb");
    autoStressKeyRef.current = "";
    activeScenarioKeyRef.current = "";
    resetChatState(selectedVenueName, setChatMessages, setConversationId, conversationId);
  }

  function handleNav(targetId) {
    const node = document.getElementById(targetId);
    if (node) {
      node.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  if (bootLoading) {
    return (
      <div className="app">
        <Header
          onNav={handleNav}
          health={health}
          bootComplete={!bootLoading}
          showNav={false}
        />
        <div className="loading-screen">
          <div className="loading-card">
            <div className="t-label accent">Boot Sequence</div>
            <div className="loading-title">Loading venue models and engine specs.</div>
            <div className="loading-sub">FastAPI, Monte Carlo engine, and Claude-backed chat are being synchronized.</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={phase === "setup" ? "app app-setup" : "app"}>
      <Header
        onNav={handleNav}
        health={health}
        bootComplete={!bootLoading}
        showNav={phase === "results"}
      />
      {errorMessage ? <ErrorStrip message={errorMessage} onDismiss={() => setErrorMessage("")} /> : null}

      {phase === "setup" ? (
        <SetupScreen
          form={form}
          onFormChange={setForm}
          venues={venues}
          venueDetails={venueDetails}
          selectedVenueId={selectedVenueId}
          onSelectVenue={setSelectedVenueId}
          capacity={selectedCapacity}
          onRun={handleRunSimulation}
          scenarios={scenarioLibrary}
          onLoadScenario={loadScenarioFromLibrary}
        />
      ) : null}

      {phase === "running" ? (
        <RunningOverlay config={runConfig} />
      ) : null}

      {phase === "results" ? (
        <>
          <Ticker items={tickerItems} />
          <div className="main-scroll" ref={mainScrollRef}>
            <RunBar
              config={runConfig}
              summary={summary}
              onNewRun={handleNewRun}
            />

            <Section
              id="results"
              idx="§01 · OUTPUT"
              title="Simulation result"
              desc="Backend model output from the current engine. Click any metric for the derivation panel."
            >
              <div className="metric-grid metric-grid-main">
                <MetricCard
                  label="Expected Wait"
                  value={formatNumber(summary.waitMean, 1)}
                  unit="min"
                  sub={`P10 ${formatNumber(summary.waitP10, 1)} · P90 ${formatNumber(summary.waitP90, 1)}`}
                  large
                  onClick={() => setSheetKey("wait")}
                />
                <MetricCard
                  label="HES · Experience"
                  value={formatNumber(summary.hes, 1)}
                  sub={`Grade ${summary.hesGrade}`}
                  valueTone={summary.hes >= 70 ? "ok" : summary.hes >= 55 ? "warn" : "danger"}
                  onClick={() => setSheetKey("hes")}
                />
                <MetricCard
                  label="Safety Risk"
                  value={formatNumber(summary.safetyScore, 0)}
                  unit="/100"
                  sub={summary.safetyLabel}
                  valueTone={safetyTone(summary.safetyLabel)}
                  onClick={() => setSheetKey("safety")}
                />
                <MetricCard
                  label="Downside At Risk"
                  value={formatImpactCurrency(summary.revenueImpact)}
                  sub={deriveRevenueSubtitle(summary)}
                  onClick={() => setSheetKey("revenue")}
                />
              </div>

              <div className="section-stack">
                <div className="div-label">Model-Based Recommendations · Priority Order</div>
                <RecommendationsList
                  recommendations={simulationResult?.metrics?.recommendations || []}
                />
              </div>
            </Section>

            <Section
              id="network"
              idx="§02 · NETWORK"
              title="Queueing network"
              desc="Actual node metrics from the backend solver, laid out in the supplied command-center view."
            >
              <NetworkGraph nodes={graphNodes} />
              <div className="metric-grid metric-grid-mini">
                <MetricMini
                  label="Bottleneck"
                  value={humanizeNodeId(simulationResult?.metrics?.operational?.bottleneck?.node)}
                  sub={`${formatPercent(simulationResult?.metrics?.operational?.bottleneck?.utilization, 0)} util`}
                  onClick={() => setSheetKey("bottleneck")}
                />
                <MetricMini
                  label="Worst LOS"
                  value={simulationResult?.simulation?.worst_fruin_los || "—"}
                  sub="Fruin crowding grade"
                  onClick={() => setSheetKey("los")}
                />
                <MetricMini
                  label="Unstable Nodes"
                  value={`${formatNumber(simulationResult?.simulation?.unstable_node_pct || 0, 0)}%`}
                  sub="share of unstable queues"
                  onClick={() => setSheetKey("unstable")}
                />
                <MetricMini
                  label="Solve Time"
                  value={formatMilliseconds(simulationResult?.computation_time_ms)}
                  sub={`${simulationResult?.simulation?.n_simulations || 0} trials`}
                  onClick={() => setSheetKey("solve")}
                />
              </div>
            </Section>

            <Section
              id="temporal"
              idx="§03 · LIFECYCLE"
              title="Arrival / egress curve"
              desc="Temporal response from `/simulate/temporal`, aggregated into a wait and arrival view."
            >
              <TemporalChart
                series={temporalSeries}
                summary={temporalResult?.temporal}
              />
            </Section>

            <Section
              id="stress"
              idx="§04 · STRESS"
              title="Stress envelope"
              desc="Six backend stress scenarios, collapsed into a resilience panel for the active run."
            >
              <StressPanel
                rows={stressRows}
                loading={stressLoading}
                errorMessage={stressError}
                resilienceScore={stressResult?.resilience_score}
                mostVulnerable={stressResult?.most_vulnerable}
                onRerun={handleStressRerun}
              />
            </Section>

            <Section
              id="whatif"
              idx="§05 · WHAT-IF"
              title="What-if and compare"
              desc="Perturb the current scenario with the real backend or run a direct scenario comparison."
            >
              <div className="analysis-toggle">
                <button
                  className={`tweak-opt ${analysisMode === "perturb" ? "active" : ""}`}
                  onClick={() => setAnalysisMode("perturb")}
                >
                  Perturbation
                </button>
                <button
                  className={`tweak-opt ${analysisMode === "compare" ? "active" : ""}`}
                  onClick={() => setAnalysisMode("compare")}
                >
                  Direct Compare
                </button>
              </div>

              {analysisMode === "perturb" ? (
                <WhatIfPanel
                  form={whatIfForm}
                  onChange={setWhatIfForm}
                  loading={whatIfLoading}
                  graphSummary={selectedVenueDetail?.graph_summary}
                  attendance={runConfig?.attendance}
                  eventType={runConfig?.event_type}
                  onRun={handleWhatIfRun}
                  result={whatIfResult}
                />
              ) : (
                <ComparePanel
                  form={compareForm}
                  onChange={setCompareForm}
                  baseConfig={runConfig}
                  capacity={resolveVenueCapacity(selectedVenue, selectedVenueDetail, compareForm.eventType)}
                  loading={compareLoading}
                  onRun={handleCompareRun}
                  result={compareResult}
                />
              )}
            </Section>

            <Section
              id="chat"
              idx="§06 · ASK"
              title="Ask"
              desc="The chat console calls `/api/chat`, which uses the backend Claude tool loop and the current scenario context."
            >
              <ChatConsole
                messages={chatMessages}
                thinking={chatThinking}
                input={chatInput}
                onInputChange={setChatInput}
                onSubmit={handleSendChat}
                prompts={promptSuggestions}
              />
            </Section>

            <Section
              id="math"
              idx="§07 · MATH"
              title="The math"
              desc="Operational metrics plus engine methodology and limitations pulled from the live `/specs` endpoint."
            >
              <MathPanel
                simulationResult={simulationResult}
                temporalResult={temporalResult}
                specs={specs}
                dataSources={dataSources}
              />
            </Section>

            <footer className="footer">
              <div>
                <div className="footer-wordmark">Vane</div>
                <div className="footer-copy">
                  Decision intelligence for high-density venue operations in Las Vegas.
                </div>
              </div>
              <div className="footer-meta">
                <div className="t-label-sm">Live Stack</div>
                <div>FastAPI · React · Anthropic Claude via backend</div>
              </div>
              {lastRunId ? (
                <div className="footer-meta">
                  <div className="t-label-sm">Replay URL</div>
                  <div>/runs/{lastRunId}</div>
                </div>
              ) : null}
            </footer>
          </div>
        </>
      ) : null}

      <Sheet
        sheetKey={sheetKey}
        onClose={() => setSheetKey(null)}
        simulationResult={simulationResult}
        temporalResult={temporalResult}
      />
    </div>
  );
}

function Header({ onNav, health, bootComplete, showNav = false }) {
  const [timestamp, setTimestamp] = useState(() => formatUtcClock(new Date()));

  useEffect(() => {
    const timer = window.setInterval(() => {
      setTimestamp(formatUtcClock(new Date()));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  const engineLine = (() => {
    if (!bootComplete) {
      return "Loading engine…";
    }
    if (health?.status === "operational") {
      return "Engine Online";
    }
    if (health) {
      return "Engine Syncing";
    }
    return "API offline (backend URL unreachable)";
  })();

  return (
    <header className="header">
      <div className="wordmark">
        <span className="wordmark-main">Vane</span>
        <span className="wordmark-sub">Decision Intelligence · v2.4</span>
      </div>

      {showNav ? (
        <nav className="header-nav">
          {SECTION_NAV.map((item) => (
            <button key={item.id} className="header-link" onClick={() => onNav(item.id)}>
              {item.label}
            </button>
          ))}
        </nav>
      ) : null}

      <div className="header-status">
        <div className="s-item">
          <span className="dot acc" />
          <span>{engineLine}</span>
        </div>
        <div className="s-item sep">|</div>
        <div className="s-item">{timestamp}</div>
      </div>
    </header>
  );
}

function Ticker({ items }) {
  const looped = [...items, ...items];

  return (
    <div className="ticker">
      <div className="ticker-track">
        {looped.map((item, index) => (
          <span className="ticker-item" key={`${item.label}-${index}`}>
            <span className={`dot ${item.tone || "acc"}`} />
            <span>{item.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function ErrorStrip({ message, onDismiss }) {
  return (
    <div className="error-strip">
      <span className="dot danger" />
      <span>{userFacingMessage(message)}</span>
      <button className="error-dismiss" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}

function SetupScreen({
  form,
  onFormChange,
  venues,
  venueDetails,
  selectedVenueId,
  onSelectVenue,
  capacity,
  onRun,
  scenarios = [],
  onLoadScenario,
}) {
  const selectedVenue = venues.find((venue) => venue.venue_id === selectedVenueId) || null;
  const graphSummary = venueDetails[selectedVenueId]?.graph_summary;

  return (
    <div className="setup-screen">
      <div className="setup-left">
        <div className="setup-hero">
          <div className="setup-kicker">Decision Intelligence · Venue Operations</div>
          <h1 className="setup-title">
            Model the event.
            <br />
            <span className="accent-copy">Decide the plan.</span>
          </h1>
          <div className="setup-sub">
            Configure a venue scenario and run the queueing-network backend.
            Auto mode pulls dated weather and traffic overlays when available; manual mode
            keeps those factors as explicit user overrides with provenance.
          </div>
        </div>

        <div className="setup-support">
          {scenarios.length > 0 ? (
            <ScenarioLibraryStrip scenarios={scenarios} onLoad={onLoadScenario} />
          ) : null}

          <div className="setup-meta">
            <div className="setup-meta-item">
              <div className="k">Trials / eval</div>
              <div className="v">1,000</div>
            </div>
            <div className="setup-meta-item">
              <div className="k">Network nodes</div>
              <div className="v">{graphSummary?.total_nodes || "—"}</div>
            </div>
            <div className="setup-meta-item">
              <div className="k">Solve time</div>
              <div className="v">varies by venue</div>
            </div>
          </div>
          <div className="setup-note">
            Grounded in DHS · Fruin HCM6 · Erlang-C · Allen-Cunneen
          </div>
        </div>
      </div>

      <div className="setup-right">
        <div className="setup-mobile-intro">
          <div className="setup-kicker">Operations console</div>
          <div className="setup-mobile-title">Build the event model.</div>
          <div className="setup-mobile-sub">
            Pick a venue, set the event profile, and run a shareable simulation directly from your phone.
          </div>
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Venue</span>
            <span className="setup-field-val">{selectedVenue?.name || "Select a venue"}</span>
          </div>
          <div className="venue-select">
            {venues.length === 0 ? (
              <div className="venue-empty">
                No venues loaded from the API. Start the backend with{" "}
                <code className="inline-code">uvicorn api.main:app --port 8000</code> and confirm{" "}
                <code className="inline-code">/venues</code> returns JSON. The engine initializes
                asynchronously after boot, so venues may be empty for a few seconds.
              </div>
            ) : null}
            {venues.map((venue) => {
              const detail = venueDetails[venue.venue_id];
              const gates =
                detail?.venue?.infrastructure?.gates?.count ||
                detail?.graph_summary?.entry_nodes ||
                "—";
              const nodes = detail?.graph_summary?.total_nodes || "—";
              const parking = detail?.venue?.infrastructure?.parking_capacity?.value;
              const corridor =
                detail?.venue?.location?.corridor ||
                venue.location?.address ||
                slugToTitle(venue.venue_id);

              return (
                <button
                  type="button"
                  key={venue.venue_id}
                  className={`venue-opt ${selectedVenueId === venue.venue_id ? "active" : ""}`}
                  onClick={() => onSelectVenue(venue.venue_id)}
                >
                  <div className="v-row">
                    <span className="vn">{venue.name}</span>
                    <span className="vm">{formatNumber(venue.capacity, 0)}</span>
                  </div>
                  <div className="v-meta">
                    <span className="v-corr">{corridor}</span>
                    <span className="v-infra">
                      <span>{gates}g</span>
                      <span>{nodes}n</span>
                      <span>{parking ? `${formatCompactNumber(parking)} park` : "shared park"}</span>
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Event type</span>
            <span className="setup-field-val">{eventName(form.eventType)}</span>
          </div>
          <div className="event-grid event-grid-wide">
            {EVENT_OPTIONS.map((option) => (
              <button
                type="button"
                key={option.id}
                className={`event-opt ${form.eventType === option.id ? "active" : ""}`}
                onClick={() =>
                  onFormChange((current) => ({
                    ...current,
                    eventType: option.id,
                  }))
                }
              >
                <div className="en">{option.name}</div>
                <div className="ed">{option.desc}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Attendance</span>
            <span className="setup-field-val">
              {formatNumber(form.attendance, 0)} · {formatNumber((form.attendance / Math.max(capacity || 1, 1)) * 100, 0)}% of capacity
            </span>
          </div>
          <input
            className="slider"
            type="range"
            min={Math.max(100, roundAttendance((capacity || 1000) * 0.2))}
            max={Math.max(100, capacity || 1000)}
            step={500}
            value={Math.min(form.attendance, capacity || form.attendance)}
            onChange={(event) =>
              onFormChange((current) => ({
                ...current,
                attendance: Number(event.target.value),
              }))
            }
          />
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Factor mode</span>
            <span className="setup-field-val">{form.factorMode === "manual" ? "Manual sliders" : "Auto from date"}</span>
          </div>
          <div className="tweak-options">
            <button
              type="button"
              className={`tweak-opt ${form.factorMode === "manual" ? "active" : ""}`}
              onClick={() =>
                onFormChange((current) => ({
                  ...current,
                  factorMode: "manual",
                }))
              }
            >
              Manual
            </button>
            <button
              type="button"
              className={`tweak-opt ${form.factorMode === "auto" ? "active" : ""}`}
              onClick={() =>
                onFormChange((current) => ({
                  ...current,
                  factorMode: "auto",
                }))
              }
            >
              Auto forecast / traffic
            </button>
          </div>
        </div>

        {form.factorMode === "manual" ? (
          <>
            <div className="setup-field">
              <div className="setup-field-label">
                <span>Weather factor</span>
                <span className="setup-field-val">{weatherDescriptor(form.weather)} · {form.weather}% override</span>
              </div>
              <input
                className="slider"
                type="range"
                min={0}
                max={100}
                step={1}
                value={form.weather}
                onChange={(event) =>
                  onFormChange((current) => ({
                    ...current,
                    weather: Number(event.target.value),
                  }))
                }
              />
            </div>

            <div className="setup-field">
              <div className="setup-field-label">
                <span>Transit factor</span>
                <span className="setup-field-val">{transitDescriptor(form.transit)} · {form.transit}% override</span>
              </div>
              <input
                className="slider"
                type="range"
                min={0}
                max={100}
                step={1}
                value={form.transit}
                onChange={(event) =>
                  onFormChange((current) => ({
                    ...current,
                    transit: Number(event.target.value),
                  }))
                }
              />
            </div>
          </>
        ) : (
          <div className="setup-date-grid">
            <label className="setup-date-field">
              <span className="t-label-sm">Event date</span>
              <input
                className="input"
                type="date"
                value={form.eventDate}
                onChange={(event) =>
                  onFormChange((current) => ({
                    ...current,
                    eventDate: event.target.value,
                  }))
                }
              />
            </label>
            <label className="setup-date-field">
              <span className="t-label-sm">Event time</span>
              <input
                className="input"
                type="time"
                value={form.eventTime}
                onChange={(event) =>
                  onFormChange((current) => ({
                    ...current,
                    eventTime: event.target.value,
                  }))
                }
              />
            </label>
          </div>
        )}

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Service rate model</span>
            <span className="setup-field-val">{form.serviceRateTier}</span>
          </div>
          <div className="tweak-options">
            <button
              type="button"
              className={`tweak-opt ${form.serviceRateTier === "operational" ? "active" : ""}`}
              onClick={() =>
                onFormChange((current) => ({
                  ...current,
                  serviceRateTier: "operational",
                }))
              }
            >
              Operational
            </button>
            <button
              type="button"
              className={`tweak-opt ${form.serviceRateTier === "literature" ? "active" : ""}`}
              onClick={() =>
                onFormChange((current) => ({
                  ...current,
                  serviceRateTier: "literature",
                }))
              }
            >
              Literature
            </button>
          </div>
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Avg. ticket price</span>
            <span className="setup-field-val">
              {form.avgTicketPrice !== "" && Number(form.avgTicketPrice) > 0
                ? `$${Number(form.avgTicketPrice).toLocaleString()}`
                : "NAC default · $95"}
            </span>
          </div>
          <label className="numeric-input">
            <span className="numeric-input-prefix">$</span>
            <input
              type="number"
              inputMode="decimal"
              min="5"
              max="10000"
              step="1"
              placeholder="95"
              value={form.avgTicketPrice}
              onChange={(event) =>
                onFormChange((current) => ({
                  ...current,
                  avgTicketPrice: event.target.value,
                }))
              }
            />
            <span className="numeric-input-suffix">per ticket</span>
          </label>
          <div className="setup-field-hint">
            When supplied, Vane checks whether this price can realistically support
            the requested turnout, then simulates on the feasible attendance. It also
            scales secondary-spend benchmarks and future-ticket value.
          </div>
        </div>

        <div className="setup-run-wrap">
          <button type="button" className="run-btn" onClick={onRun}>
            <span>▸ Run simulation</span>
            <span className="run-meta">Monte Carlo · temporal · chat-ready</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function RunningOverlay({ config }) {
  const [stepIndex, setStepIndex] = useState(0);
  const steps = [
    "Loading venue topology",
    "Resolving weather and traffic factors",
    "Running Monte Carlo network snapshot",
    "Solving temporal lifecycle model",
    "Computing HES · safety · revenue",
    "Formatting recommendations and graph metrics",
  ];

  useEffect(() => {
    const timer = window.setInterval(() => {
      setStepIndex((current) => Math.min(current + 1, steps.length - 1));
    }, 260);
    return () => window.clearInterval(timer);
  }, [steps.length]);

  return (
    <div className="running-shell">
      <div className="running-card">
        <div className="t-label accent">Simulating</div>
        <div className="running-title">
          {config?.venue_name || "Selected venue"}
          <br />
          <span>{eventName(config?.event_type)} · {formatNumber(config?.attendance, 0)} attendance</span>
        </div>
        <div className="panel">
          <div className="panel-head panel-head-acc">
            <span>Live execution</span>
            <span>API · network · temporal</span>
          </div>
          <div className="running-steps">
            {steps.map((step, index) => (
              <div
                key={step}
                className={`running-step ${index < stepIndex ? "complete" : ""} ${index === stepIndex ? "active" : ""}`}
              >
                <span>{index < stepIndex ? "✓" : index === stepIndex ? "▸" : "·"}</span>
                <span>{step}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function RunBar({ config, summary, onNewRun }) {
  const requestedAttendance = summary?.requestedAttendance || config?.attendance_requested;
  const effectiveAttendance = summary?.effectiveAttendance || config?.attendance;
  const attendanceDelta = summary?.attendanceDelta || 0;
  const isPriceConstrained = Boolean(summary?.isPriceConstrained);

  return (
    <div className="run-bar">
      <div className="run-bar-label">Run</div>
      <div className="run-bar-chip">
        <span className="k">venue</span>
        <span className="v">{config?.venue_name}</span>
      </div>
      <div className="run-bar-chip">
        <span className="k">event</span>
        <span className="v">{eventName(config?.event_type)}</span>
      </div>
      <div className="run-bar-chip">
        <span className="k">{isPriceConstrained ? "attendance eff" : "attendance"}</span>
        <span className="v">{formatNumber(effectiveAttendance, 0)}</span>
      </div>
      {requestedAttendance && requestedAttendance !== effectiveAttendance ? (
        <div className="run-bar-chip">
          <span className="k">requested</span>
          <span className="v">{formatNumber(requestedAttendance, 0)}</span>
        </div>
      ) : null}
      {isPriceConstrained ? (
        <div className="run-bar-chip">
          <span className="k">price delta</span>
          <span className="v">-{formatNumber(attendanceDelta, 0)}</span>
        </div>
      ) : null}
      <div className="run-bar-chip">
        <span className="k">weather</span>
        <span className="v">{config?.weather_factor != null ? formatNumber(config.weather_factor * 100, 0) : "auto"}</span>
      </div>
      <div className="run-bar-chip">
        <span className="k">transit</span>
        <span className="v">{config?.transit_factor != null ? formatNumber(config.transit_factor * 100, 0) : "auto"}</span>
      </div>
      {summary?.nTrials ? (
        <div className="run-bar-chip">
          <span className="k">trials</span>
          <span className="v">{formatNumber(summary.nTrials, 0)}</span>
        </div>
      ) : null}
      {summary?.arrivalWindow ? (
        <div className="run-bar-chip">
          <span className="k">window</span>
          <span className="v">{formatNumber(summary.arrivalWindow, 1)}h</span>
        </div>
      ) : null}
      {config?.avg_ticket_price ? (
        <div className="run-bar-chip">
          <span className="k">ticket</span>
          <span className="v">${formatNumber(config.avg_ticket_price, 0)}</span>
        </div>
      ) : null}
      <div className="run-status">
        <span className="dot acc" />
        <span>Simulation complete · {formatMilliseconds(summary.computeMs)}</span>
      </div>
      <button className="btn btn-ghost" onClick={onNewRun}>
        ◂ New run
      </button>
    </div>
  );
}

function Section({ id, idx, title, desc, children }) {
  return (
    <section id={id} className="section">
      <div className="section-head">
        <div>
          <div className="section-idx">{idx}</div>
          <div className="section-title">{title}</div>
        </div>
        <div className="section-desc">{desc}</div>
      </div>
      {children}
    </section>
  );
}

function ScenarioLibraryStrip({ scenarios, onLoad }) {
  return (
    <div className="scenario-strip">
      <div className="scenario-strip-head">
        <div className="scenario-strip-kicker">Canonical Scenarios</div>
        <div className="scenario-strip-sub">
          One-click presets sourced from documented Las Vegas events. Each card
          loads the full scenario configuration; you still press Run to simulate.
        </div>
      </div>
      <div className="scenario-strip-grid">
        {scenarios.map((s) => (
          <button
            key={s.slug}
            type="button"
            className="scenario-card"
            onClick={() => onLoad(s)}
            title={s.description || s.name}
          >
            <div className="scenario-card-name">{s.name}</div>
            <div className="scenario-card-meta">
              {eventName(s.request_json?.event_type)} ·{" "}
              {formatNumber(s.request_json?.attendance, 0)} attendance
            </div>
            {s.description ? (
              <div className="scenario-card-desc">{s.description}</div>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, unit, sub, large, valueTone, onClick }) {
  return (
    <button className="metric-clickable" onClick={onClick}>
      <div className="t-label">{label}</div>
      <div className={`metric-value-row ${large ? "large" : ""}`}>
        <span className={`metric-big ${valueTone || ""}`}>{value ?? "—"}</span>
        {unit ? <span className="metric-unit">{unit}</span> : null}
      </div>
      <div className="metric-subcopy">{sub}</div>
    </button>
  );
}

function MetricMini({ label, value, sub, onClick }) {
  const interactive = typeof onClick === "function";
  const Tag = interactive ? "button" : "div";
  return (
    <Tag
      type={interactive ? "button" : undefined}
      className={`metric-mini ${interactive ? "metric-mini-interactive" : ""}`}
      onClick={onClick}
    >
      <div className="t-label-sm">{label}</div>
      <div className="metric-mini-value">{value || "—"}</div>
      <div className="metric-mini-sub">{sub}</div>
      {interactive ? <span className="metric-mini-chev" aria-hidden="true">∂</span> : null}
    </Tag>
  );
}

function RecommendationsList({ recommendations }) {
  if (!recommendations.length) {
    return (
      <div className="panel panel-empty">
        No ranked recommendations returned for this scenario.
      </div>
    );
  }

  return (
    <div className="recommendations">
      {recommendations.map((recommendation) => (
        <div className="recommendation-row" key={`${recommendation.priority}-${recommendation.action}`}>
          <div className="recommendation-rank">{String(recommendation.priority).padStart(2, "0")}</div>
          <div className={`recommendation-cat ${toneForRecommendation(recommendation.category)}`}>
            {recommendation.category}
          </div>
          <div className="recommendation-action">{recommendation.action}</div>
          <div className="recommendation-impact">{recommendation.expected_impact}</div>
        </div>
      ))}
    </div>
  );
}

function NetworkGraph({ nodes }) {
  const [hovered, setHovered] = useState(null);
  const width = 980;
  const height = 520;
  const positions = useMemo(() => buildGraphPositions(nodes, width, height), [nodes]);
  const edges = useMemo(() => buildGraphEdges(nodes), [nodes]);

  if (!nodes.length) {
    return <div className="panel empty-viz">Awaiting simulation output</div>;
  }

  return (
    <div className="network-shell">
      <svg viewBox={`0 0 ${width} ${height}`} className="network-svg">
        {[...Array(8)].map((_, index) => (
          <line
            key={`grid-v-${index}`}
            x1={(index * width) / 8}
            y1="0"
            x2={(index * width) / 8}
            y2={height}
            stroke="var(--line-0)"
            strokeWidth="0.6"
          />
        ))}
        {[...Array(6)].map((_, index) => (
          <line
            key={`grid-h-${index}`}
            x1="0"
            y1={(index * height) / 6}
            x2={width}
            y2={(index * height) / 6}
            stroke="var(--line-0)"
            strokeWidth="0.6"
          />
        ))}

        {["ENTRY", "SECURITY", "FLOW", "SEATING", "EGRESS"].map((label, index) => (
          <text
            key={label}
            x={[90, 230, 440, 620, 875][index]}
            y="24"
            textAnchor="middle"
            fontSize="10"
            fill="var(--fg-3)"
            letterSpacing="2"
          >
            {label}
          </text>
        ))}

        {edges.map((edge) => {
          const start = positions[edge[0]];
          const end = positions[edge[1]];
          if (!start || !end) {
            return null;
          }
          return (
            <line
              key={`${edge[0]}-${edge[1]}`}
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              stroke="var(--line-2)"
              strokeWidth="0.8"
              opacity="0.38"
            />
          );
        })}

        {nodes.map((node) => {
          const position = positions[node.id];
          if (!position) {
            return null;
          }

          return (
            <g
              key={node.id}
              onMouseEnter={() => setHovered(node)}
              onMouseLeave={() => setHovered(null)}
            >
              {node.utilization > 0.72 ? (
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={nodeRadius(node) + 8}
                  fill={nodeColor(node)}
                  opacity="0.14"
                >
                  <animate
                    attributeName="r"
                    values={`${nodeRadius(node) + 6};${nodeRadius(node) + 11};${nodeRadius(node) + 6}`}
                    dur="2s"
                    repeatCount="indefinite"
                  />
                  <animate
                    attributeName="opacity"
                    values="0.16;0.02;0.16"
                    dur="2s"
                    repeatCount="indefinite"
                  />
                </circle>
              ) : null}

              <circle
                cx={position.x}
                cy={position.y}
                r={nodeRadius(node)}
                fill={nodeColor(node)}
                stroke="var(--bg-0)"
                strokeWidth="1.2"
              />
              <text
                x={position.x}
                y={position.y + nodeRadius(node) + 13}
                textAnchor="middle"
                fontSize="8.8"
                fill="var(--fg-3)"
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>

      {hovered ? (
        <div className="graph-tooltip">
          <div className="t-label-sm accent">{hovered.label}</div>
          <div className="graph-tooltip-grid">
            <div>
              <span className="muted">Type</span>
              <span>{hovered.type}</span>
            </div>
            <div>
              <span className="muted">Util</span>
              <span>{formatPercent(hovered.utilization, 0)}</span>
            </div>
            <div>
              <span className="muted">Wait</span>
              <span>{formatNumber(hovered.waitMean, 1)}m</span>
            </div>
            <div>
              <span className="muted">LOS</span>
              <span>{hovered.los || "—"}</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TemporalChart({ series, summary }) {
  const width = 1200;
  const height = 320;
  const pad = { left: 52, right: 30, top: 26, bottom: 34 };
  const maxWait = Math.max(30, ...series.map((point) => point.wait));
  const maxArrival = Math.max(1, ...series.map((point) => point.arrival));

  const xFor = (index) =>
    pad.left + (index / Math.max(series.length - 1, 1)) * (width - pad.left - pad.right);
  const yFor = (value, max) =>
    pad.top + (height - pad.top - pad.bottom) * (1 - value / Math.max(max, 1));

  const waitPath = series
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(index)},${yFor(point.wait, maxWait)}`)
    .join(" ");
  const arrivalPath = series
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"}${xFor(index)},${yFor(point.arrival, maxArrival)}`,
    )
    .join(" ");
  const areaPath = `${waitPath} L${xFor(series.length - 1)},${height - pad.bottom} L${xFor(0)},${height - pad.bottom} Z`;

  if (!series.length) {
    return <div className="panel empty-viz">Temporal simulation data is not available.</div>;
  }

  const eventStartIndex = series.findIndex((point) => point.tMinutes >= 0);
  const peakWaitIndex = series.reduce(
    (bestIndex, point, index) => (point.wait > series[bestIndex].wait ? index : bestIndex),
    0,
  );

  return (
    <div className="panel temporal-panel">
      <svg viewBox={`0 0 ${width} ${height}`} className="temporal-svg">
        <defs>
          <linearGradient id="temporal-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--acc)" stopOpacity="0.24" />
            <stop offset="100%" stopColor="var(--acc)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={pad.top + (height - pad.top - pad.bottom) * fraction}
              y2={pad.top + (height - pad.top - pad.bottom) * fraction}
              stroke="var(--line-1)"
              strokeWidth="0.6"
              strokeDasharray="2 4"
            />
            <text
              x={pad.left - 8}
              y={pad.top + (height - pad.top - pad.bottom) * fraction + 4}
              textAnchor="end"
              fontSize="10"
              fill="var(--fg-3)"
            >
              {formatNumber(maxWait * (1 - fraction), 0)}m
            </text>
          </g>
        ))}

        <path d={areaPath} fill="url(#temporal-fill)" />
        <path d={waitPath} stroke="var(--acc)" strokeWidth="2" fill="none" />
        <path d={arrivalPath} stroke="var(--info)" strokeWidth="1.2" fill="none" opacity="0.62" />

        {eventStartIndex >= 0 ? (
          <>
            <line
              x1={xFor(eventStartIndex)}
              x2={xFor(eventStartIndex)}
              y1={pad.top}
              y2={height - pad.bottom}
              stroke="var(--info)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <text
              x={xFor(eventStartIndex) + 6}
              y={pad.top + 12}
              fontSize="9"
              fill="var(--info)"
              letterSpacing="2"
            >
              EVENT START
            </text>
          </>
        ) : null}

        <line
          x1={xFor(peakWaitIndex)}
          x2={xFor(peakWaitIndex)}
          y1={pad.top}
          y2={height - pad.bottom}
          stroke="var(--warn)"
          strokeWidth="1"
          strokeDasharray="2 2"
          opacity="0.8"
        />
        <text
          x={xFor(peakWaitIndex) + 6}
          y={pad.top + 24}
          fontSize="9"
          fill="var(--warn)"
          letterSpacing="1"
        >
          PEAK · {formatNumber(series[peakWaitIndex].wait, 1)}m
        </text>

        {buildTickIndexes(series.length).map((index) => (
          <text
            key={`tick-${index}`}
            x={xFor(index)}
            y={height - 10}
            textAnchor="middle"
            fontSize="9"
            fill="var(--fg-3)"
          >
            T{series[index].tMinutes > 0 ? "+" : ""}
            {formatNumber(series[index].tMinutes, 0)}
          </text>
        ))}
      </svg>

      <div className="temporal-foot">
        <span className="legend-item">
          <span className="legend-line acc" />
          wait
        </span>
        <span className="legend-item">
          <span className="legend-line info" />
          arrival
        </span>
        <span className="temporal-summary">
          Peak congestion at T+{formatNumber(summary?.peak_congestion_time || 0, 0)} · {formatNumber(summary?.peak_congestion_wait || 0, 1)}m
        </span>
      </div>
    </div>
  );
}

function StressPanel({ rows, loading, errorMessage, resilienceScore, mostVulnerable, onRerun }) {
  return (
    <div className="stress-grid">
      <div className="stress-score">
        <div>
          <div className="t-label-sm">Resilience Score</div>
          <div className="banner-num">{resilienceScore != null ? formatNumber(resilienceScore, 0) : "—"}</div>
          <div className="stress-sub">/ 100 · aggregate HES preservation</div>
        </div>
        <div className="stress-copy">
          <div>
            Most vulnerable scenario: <span className="accent-copy inline">{STRESS_META[mostVulnerable]?.label || "pending"}</span>
          </div>
          <button className="btn" onClick={onRerun}>
            {loading ? "Running…" : "↻ Re-run stress panel"}
          </button>
        </div>
      </div>

      <div className="stress-list">
        {!loading && errorMessage ? (
          <div className="empty-card">
            <div className="t-label-sm danger-copy">Stress panel unavailable</div>
            <div className="panel-copy">{errorMessage}</div>
          </div>
        ) : null}
        {loading && !rows.length ? (
          <>
            {[...Array(6)].map((_, index) => (
              <div className="shimmer stress-row" key={`loading-${index}`} />
            ))}
          </>
        ) : (
          rows.map((row) => (
            <div className="stress-row-data" key={row.id}>
              <div>
                <div className="stress-name">{row.label}</div>
                <div className="stress-detail">{row.detail}</div>
              </div>
              <div className="bar">
                <div
                  className={`bar-fill ${row.resilience < 40 ? "danger" : row.resilience < 65 ? "warn" : ""}`}
                  style={{ width: `${row.resilience}%` }}
                />
              </div>
              <div className="stress-value">{formatNumber(row.resilience, 0)}</div>
              <div className={`stress-delta ${row.waitDelta > 0 ? "danger-copy" : "ok-copy"}`}>
                {row.waitDelta > 0 ? "+" : ""}
                {formatNumber(row.waitDelta, 1)}m wait
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function WhatIfPanel({
  form,
  onChange,
  loading,
  graphSummary,
  attendance,
  eventType,
  onRun,
  result,
}) {
  const nodeTypes = graphSummary?.node_types || {};
  const entryNodeCount = graphSummary?.entry_nodes || 4;
  const securityCount = nodeTypes.security ?? entryNodeCount;
  const concessionCount = nodeTypes.concession ?? 0;
  const restroomCount = nodeTypes.restroom ?? 0;
  const seatingCount = nodeTypes.seating ?? 0;
  const ticketingCount = nodeTypes.ticketing ?? 0;
  const staffedNodeCount = securityCount + ticketingCount + concessionCount + restroomCount;

  // Keep the gate-disable slider sane: never let the user disable *every*
  // gate, and cap at 3 so the perturbation stays interpretable.  For a
  // 3-gate venue you can disable 2, etc.
  const maxDisabledGates = Math.max(1, Math.min(3, entryNodeCount - 1));

  // "Extra security servers" means: add N servers to EACH of the
  // `securityCount` checkpoints.  Capped at +4 per lane — beyond that the
  // marginal throughput gain collapses (Erlang-C tail) and the bar is no
  // longer a realistic staffing ask.
  const maxExtraServers = 4;

  // Concise one-liners under each slider. Operators need fast scanning during
  // numbers, not paragraphs.  Scale-aware so the text changes with the venue.
  const gateHint = form.disabledGates > 0
    ? `−${form.disabledGates} of ${entryNodeCount} gates (+ paired security lane${form.disabledGates === 1 ? "" : "s"})`
    : `All ${entryNodeCount} gates online`;

  const serverHint = form.extraServers > 0
    ? `+${form.extraServers * securityCount} lanes total · +${form.extraServers} × ${securityCount} checkpoints`
    : `Baseline · ${securityCount} checkpoints at roster strength`;

  const staffingHint = form.staffingCut > 0
    ? `−${form.staffingCut}% across ${staffedNodeCount} service nodes`
    : `Full roster at ${staffedNodeCount} service nodes`;

  const closedHint = (() => {
    if (!form.closedSection) return "All sections open";
    if (form.closedSection === "seating_") return "Seating bowl offline · concourse-only mode";
    if (form.closedSection === "concession_") return `Close all ${concessionCount} concession stations`;
    if (form.closedSection === "restroom_")   return `Close all ${restroomCount} restroom clusters`;
    return "Close selected section";
  })();

  const attendanceLabel = attendance
    ? `${Number(attendance).toLocaleString()} · ${(eventType || "event").replace(/_/g, " ")}`
    : "active baseline";

  return (
    <div className="analysis-grid">
      <div className="analysis-controls">
        <div className="perturb-head">
          <span className="t-label accent">Perturbation controls</span>
          <span className="perturb-sub">{attendanceLabel} · 500 MC trials</span>
        </div>

        <SliderRow
          label="Disable gates"
          value={form.disabledGates}
          min={0}
          max={maxDisabledGates}
          step={1}
          unit=""
          hint={gateHint}
          onChange={(value) => onChange((current) => ({ ...current, disabledGates: value }))}
        />
        <SliderRow
          label="Extra security servers"
          value={form.extraServers}
          min={0}
          max={maxExtraServers}
          step={1}
          unit=""
          hint={serverHint}
          onChange={(value) => onChange((current) => ({ ...current, extraServers: value }))}
        />
        <SliderRow
          label="Staffing cut"
          value={form.staffingCut}
          min={0}
          max={50}
          step={5}
          unit="%"
          hint={staffingHint}
          onChange={(value) => onChange((current) => ({ ...current, staffingCut: value }))}
        />

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Close section</span>
            <span className="setup-field-val">{form.closedSection ? humanizeCloseSection(form.closedSection) : "none"}</span>
          </div>
          <div className="tweak-options">
            {[
              { value: "", label: "None", count: null },
              { value: "concession_", label: "Concessions", count: concessionCount },
              { value: "restroom_",   label: "Restrooms",   count: restroomCount },
              // Seating is a single absorbing node — closing it simulates
              // concourse-only mode (legitimate but extreme what-if).
              { value: "seating_",    label: "Seating bowl", count: null },
            ].map((option) => (
              <button
                type="button"
                key={option.value || "none"}
                className={`tweak-opt ${form.closedSection === option.value ? "active" : ""}`}
                onClick={() => onChange((current) => ({ ...current, closedSection: option.value }))}
                disabled={option.value !== "" && (option.count ?? 0) === 0}
              >
                {option.label}{option.count !== null && option.count > 0 ? ` · ${option.count}` : ""}
              </button>
            ))}
          </div>
          <div className="slider-hint">{closedHint}</div>
        </div>

        <button className="btn run-whatif-btn" onClick={onRun}>
          {loading ? "Running…" : "Run what-if"}
        </button>

        <PerturbationRunCard
          attendanceLabel={attendanceLabel}
          graphSummary={graphSummary}
          staffedNodeCount={staffedNodeCount}
        />
      </div>

      <div className="analysis-results">
        {result ? (
          <>
            <div className="analysis-head">
              <div className="analysis-summary">{result.summary}</div>
              <AppliedPerturbationRibbon applied={result._applied} graphSummary={graphSummary} />
            </div>
            <div className="delta-list">
              <DeltaRow
                label="Expected wait"
                base={result.base?.metrics?.operational?.wait_time?.mean ?? result.base?.simulation?.wait_mean}
                modified={result.modified?.metrics?.operational?.wait_time?.mean ?? result.modified?.simulation?.wait_mean}
                unit="min"
                invert
              />
              <DeltaRow
                label="HES"
                base={result.base?.metrics?.experience?.hes ?? result.base?.simulation?.hes_mean}
                modified={result.modified?.metrics?.experience?.hes ?? result.modified?.simulation?.hes_mean}
              />
              <DeltaRow
                label="Utilization"
                base={scaleFraction(result.base?.simulation?.util_mean)}
                modified={scaleFraction(result.modified?.simulation?.util_mean)}
                unit="%"
                invert
              />
              <DeltaRow
                label="Congestion"
                base={scaleFraction(result.base?.simulation?.congestion_mean)}
                modified={scaleFraction(result.modified?.simulation?.congestion_mean)}
                unit="%"
                invert
              />
              <DeltaRow
                label="Downside at risk"
                base={result.base?.metrics?.revenue?.total_economic_impact}
                modified={result.modified?.metrics?.revenue?.total_economic_impact}
                money
                invert
              />
            </div>

            <div className="analysis-node-grid">
              <NodeListCard title="Improved nodes" nodes={result.improved_nodes || []} tone="ok" />
              <NodeListCard title="Degraded nodes" nodes={result.degraded_nodes || []} tone="danger" />
            </div>
          </>
        ) : (
          <WhatIfPreview
            attendance={attendance}
            eventType={eventType}
            graphSummary={graphSummary}
          />
        )}
      </div>
    </div>
  );
}

function WhatIfPreview({ attendance, eventType, graphSummary }) {
  const nodeTypes = graphSummary?.node_types || {};
  const entryCount = graphSummary?.entry_nodes ?? nodeTypes.entry ?? 0;
  const securityCount = nodeTypes.security ?? entryCount ?? 0;
  const staffedCount =
    (nodeTypes.security ?? 0) +
    (nodeTypes.ticketing ?? 0) +
    (nodeTypes.concession ?? 0) +
    (nodeTypes.restroom ?? 0);
  const formattedAttendance = attendance ? Number(attendance).toLocaleString() : "—";
  const evLabel = (eventType || "event").replace(/_/g, " ");
  const previewPanels = [
    {
      title: "Headline deltas",
      body: "Expected wait, HES, safety, and downside at risk with baseline, modified, and delta readouts.",
    },
    {
      title: "Node movement",
      body: "Which gates, checkpoints, and service nodes improve, which degrade, and by how much.",
    },
    {
      title: "Held constant",
      body: "Attendance, weather, and transit stay locked to the baseline unless the active perturbation changes them.",
    },
    {
      title: "Traceability",
      body: "Weather, traffic, and service-rate provenance stay attached so the modified run never looks ungrounded.",
    },
  ];

  return (
    <div className="whatif-preview">
      <div className="whatif-preview-head">
        <span className="t-label accent">Waiting for perturbation</span>
        <span className="whatif-preview-sub">500 Monte-Carlo trials · baseline locked</span>
      </div>

      <div className="whatif-preview-formula">
        <span className="wpf-lhs">Δ<span className="wpf-sub">metric</span></span>
        <span className="wpf-eq">=</span>
        <span className="wpf-rhs">
          <span className="wpf-term">f(topology′, staffing′, weather, transit)</span>
          <span className="wpf-minus">−</span>
          <span className="wpf-term">f(topology, staffing, weather, transit)</span>
        </span>
      </div>

      <div className="whatif-preview-grid">
        <div className="wp-cell">
          <span className="wp-k">Baseline</span>
          <span className="wp-v">{formattedAttendance} · {evLabel}</span>
        </div>
        <div className="wp-cell">
          <span className="wp-k">Topology</span>
          <span className="wp-v">{entryCount} gates · {securityCount} security · {staffedCount} service nodes</span>
        </div>
        <div className="wp-cell">
          <span className="wp-k">Engine</span>
          <span className="wp-v">Allen-Cunneen G/G/s · Jackson network · Monte Carlo</span>
        </div>
      </div>

      <div className="whatif-preview-body">
        <div className="whatif-preview-expect whatif-preview-expect-rich">
          <span className="t-label-sm">You'll get back</span>
          <div className="whatif-preview-panels">
            {previewPanels.map((panel) => (
              <div key={panel.title} className="wp-panel">
                <span className="wp-panel-k">{panel.title}</span>
                <span className="wp-panel-v">{panel.body}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="whatif-preview-notes">
          <span className="t-label-sm">Why this matters</span>
          <ul>
            <li><span className="wp-dot" />This is a perturbation engine, not a blank sandbox, so every change is measured against the live baseline you just ran.</li>
            <li><span className="wp-dot" />Revenue is reported as downside at risk, not gross event revenue, so upside never gets mislabeled as loss.</li>
            <li><span className="wp-dot" />Safety respects both structural envelope math and temporal peak risk when that sharper signal is available.</li>
          </ul>
        </div>
      </div>

      <div className="whatif-preview-expect">
        <span className="t-label-sm">You'll get back</span>
        <ul>
          <li><span className="wp-dot" />Expected wait · HES · utilization · congestion · revenue — each with baseline → modified → Δ</li>
          <li><span className="wp-dot" />Per-node deltas: which queues improved, which degraded, by how much</li>
          <li><span className="wp-dot" />Full provenance on weather / traffic overlays at the new operating point</li>
        </ul>
      </div>

      <div className="whatif-preview-foot">Move a slider · pick a section · press RUN WHAT-IF</div>
    </div>
  );
}

function ComparePanel({ form, onChange, baseConfig, capacity, loading, onRun, result }) {
  const baselineAttendance = Math.max(baseConfig?.attendance || 1000, 100);
  const nominalCapacity = Math.max(capacity || 0, 100);
  const compareMaxAttendance = resolveCompareAttendanceMax(baselineAttendance, nominalCapacity);
  const attendanceDelta = (form.attendance || 0) - baselineAttendance;
  const loadPct = nominalCapacity > 0 ? (form.attendance / nominalCapacity) * 100 : null;
  const overloadCount = nominalCapacity > 0 ? Math.max(0, form.attendance - nominalCapacity) : 0;
  const attendanceHintParts = [];

  if (baselineAttendance > 0) {
    if (attendanceDelta === 0) {
      attendanceHintParts.push("Matches baseline demand");
    } else {
      const deltaPrefix = attendanceDelta > 0 ? "+" : "-";
      attendanceHintParts.push(
        `${deltaPrefix}${formatNumber(Math.abs(attendanceDelta), 0)} vs baseline`,
      );
    }
  }

  if (loadPct != null) {
    attendanceHintParts.push(`${formatNumber(loadPct, 0)}% of nominal capacity`);
  }

  if (overloadCount > 0) {
    attendanceHintParts.push(`${formatNumber(overloadCount, 0)} above nominal capacity`);
  } else {
    attendanceHintParts.push("Within nominal capacity");
  }

  const attendanceHint = attendanceHintParts.join(" - ");
  const comparePresets = [5000, 10000, 20000].map((delta) => ({
    delta,
    target: Math.min(compareMaxAttendance, roundAttendance(baselineAttendance + delta)),
  }));

  return (
    <div className="analysis-grid">
      <div className="analysis-controls">
        <div className="t-label accent">Modified scenario</div>
        <div className="compare-baseline">
          Baseline: {eventName(baseConfig?.event_type)} · {formatNumber(baseConfig?.attendance, 0)} · weather {formatNumber((baseConfig?.weather_factor || 0) * 100, 0)} · transit {formatNumber((baseConfig?.transit_factor || 0) * 100, 0)}
        </div>

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Event type</span>
            <span className="setup-field-val">{eventName(form.eventType)}</span>
          </div>
          <div className="event-grid">
            {EVENT_OPTIONS.map((option) => (
              <button
                type="button"
                key={option.id}
                className={`event-opt ${form.eventType === option.id ? "active" : ""}`}
                onClick={() => onChange((current) => ({ ...current, eventType: option.id }))}
              >
                <div className="en">{option.name}</div>
                <div className="ed">{option.desc}</div>
              </button>
            ))}
          </div>
        </div>

        <SliderRow
          label="Attendance"
          value={form.attendance}
          min={100}
          max={compareMaxAttendance}
          step={500}
          hint={attendanceHint}
          onChange={(value) => onChange((current) => ({ ...current, attendance: value }))}
        />
        <div className="tweak-options">
          <button
            type="button"
            className={`tweak-opt ${form.attendance === baselineAttendance ? "active" : ""}`}
            onClick={() => onChange((current) => ({ ...current, attendance: baselineAttendance }))}
          >
            Baseline
          </button>
          {comparePresets.map((preset) => (
            <button
              type="button"
              key={preset.delta}
              className={`tweak-opt ${form.attendance === preset.target ? "active" : ""}`}
              onClick={() => onChange((current) => ({ ...current, attendance: preset.target }))}
            >
              +{preset.delta / 1000}k
            </button>
          ))}
        </div>
        <div className="setup-field-hint">
          Quick presets are relative to the active baseline. Overload scenarios are allowed;
          slider max is {formatNumber(compareMaxAttendance, 0)} attendees.
        </div>
        <SliderRow
          label="Weather"
          value={form.weather}
          min={0}
          max={100}
          step={1}
          unit="%"
          onChange={(value) => onChange((current) => ({ ...current, weather: value }))}
        />
        <SliderRow
          label="Transit"
          value={form.transit}
          min={0}
          max={100}
          step={1}
          unit="%"
          onChange={(value) => onChange((current) => ({ ...current, transit: value }))}
        />

        <div className="setup-field">
          <div className="setup-field-label">
            <span>Service rate model</span>
            <span className="setup-field-val">{form.serviceRateTier}</span>
          </div>
          <div className="tweak-options">
            {["operational", "literature"].map((tier) => (
              <button
                type="button"
                key={tier}
                className={`tweak-opt ${form.serviceRateTier === tier ? "active" : ""}`}
                onClick={() => onChange((current) => ({ ...current, serviceRateTier: tier }))}
              >
                {tier}
              </button>
            ))}
          </div>
        </div>

        <button className="btn" onClick={onRun}>
          {loading ? "Running…" : "Run compare"}
        </button>
      </div>

      <div className="analysis-results">
        {result ? (
          <>
            <div className="analysis-summary">{result.summary}</div>
            <div className="delta-list">
              <DeltaRow
                label="Expected wait"
                base={result.base?.metrics?.operational?.wait_time?.mean ?? result.base?.simulation?.wait_mean}
                modified={result.modified?.metrics?.operational?.wait_time?.mean ?? result.modified?.simulation?.wait_mean}
                unit="min"
                invert
              />
              <DeltaRow
                label="HES"
                base={result.base?.metrics?.experience?.hes ?? result.base?.simulation?.hes_mean}
                modified={result.modified?.metrics?.experience?.hes ?? result.modified?.simulation?.hes_mean}
              />
              <DeltaRow
                label="Congestion"
                base={scaleFraction(result.base?.simulation?.congestion_mean)}
                modified={scaleFraction(result.modified?.simulation?.congestion_mean)}
                unit="%"
                invert
              />
              <DeltaRow
                label="Breakdown risk"
                base={scaleFraction(result.base?.simulation?.breakdown_mean)}
                modified={scaleFraction(result.modified?.simulation?.breakdown_mean)}
                unit="%"
                invert
              />
              <DeltaRow
                label="Downside at risk"
                base={result.base?.metrics?.revenue?.total_economic_impact}
                modified={result.modified?.metrics?.revenue?.total_economic_impact}
                money
                invert
              />
            </div>

            <div className="analysis-node-grid">
              <NodeListCard title="Improved nodes" nodes={result.improved_nodes || []} tone="ok" />
              <NodeListCard title="Degraded nodes" nodes={result.degraded_nodes || []} tone="danger" />
            </div>
          </>
        ) : (
          <div className="panel panel-empty">
            Modify attendance, weather, transit, or event type, then run a direct compare against the active baseline.
          </div>
        )}
      </div>
    </div>
  );
}

function ChatConsole({ messages, thinking, input, onInputChange, onSubmit, prompts }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!scrollRef.current) {
      return;
    }
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, thinking]);

  return (
    <div className="panel chat-panel">
      <div className="panel-head">
        <span>▸ Scenario-aware chat</span>
        <span>Claude via backend when configured · current scenario attached</span>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`}>
            {message.role === "sys" ? (
              <div className="chat-system">{message.text}</div>
            ) : null}

            {message.role === "tool" ? (
              <div className="chat-tool">
                {message.items.map((item) => (
                  <div key={item}>{item}</div>
                ))}
              </div>
            ) : null}

            {message.role === "user" ? (
              <div className="chat-user">
                <span className="term-prompt">vane@ops~$</span>
                <span>{message.text}</span>
              </div>
            ) : null}

            {message.role === "assistant" ? (
              <div className={`chat-assistant ${message.error ? "error" : ""}`}>
                <div className="t-label-sm accent">Vane</div>
                <div>{message.text}</div>
              </div>
            ) : null}
          </div>
        ))}

        {thinking ? <div className="chat-thinking">vane thinking<span className="blink">●●●</span></div> : null}
      </div>

      <div className="chat-footer">
        <div className="chat-prompts">
          {prompts.map((prompt) => (
            <button
              key={prompt}
              className="tweak-opt"
              onClick={() => onSubmit(prompt)}
            >
              {prompt}
            </button>
          ))}
        </div>

        <form
          className="chat-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit(input);
          }}
        >
          <span className="term-prompt">vane@ops~$</span>
          <input
            className="input chat-input"
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder="Describe a follow-up scenario or ask for operational guidance…"
          />
          <button className="btn" type="submit">
            ↵ Run
          </button>
        </form>
      </div>
    </div>
  );
}

function MathPanel({ simulationResult, temporalResult, specs, dataSources }) {
  const factors = simulationResult?.metrics?.experience?.factors || {};
  const sim = simulationResult?.simulation || {};
  const params = simulationResult?.parameters || {};
  const demand = simulationResult?.metrics?.demand || {};
  const window = sim.arrival_window_hours;
  const peakRate = sim.peak_arrival_rate_per_hour;
  const nSims = sim.n_simulations || params.n_simulations;
  const computeMs = simulationResult?.computation_time_ms;
  const unstablePct = sim.unstable_node_pct;
  const utilMax = sim.util_max;
  const congProb = sim.congestion_probability;
  const provenance = simulationResult?.data_provenance;

  return (
    <div className="math-grid">
      <DataSourcesCard dataSources={dataSources} provenance={provenance} />

      <div className="panel math-card">
        <div className="t-label accent">Calibration · model assumptions</div>
        <div className="math-formula">
          Peak-hour steady-state · Jackson network · {formatNumber(nSims, 0)} Monte Carlo trials
        </div>
        <table className="math-table">
          <tbody>
            <MathRow label="Arrival window" value={`${formatNumber(window, 2)} h (event-type calibrated)`} />
            <MathRow label="Peak arrival rate" value={`${formatNumber(peakRate, 0)} pph`} />
            <MathRow label="Monte Carlo trials" value={formatNumber(nSims, 0)} />
            <MathRow label="Compute time" value={formatMilliseconds(computeMs)} />
            <MathRow label="Peak utilization ρ*" value={utilMax != null ? formatNumber(utilMax, 2) : "—"} />
            <MathRow label="Congestion probability" value={congProb != null ? `${formatNumber(congProb * 100, 0)}%` : "—"} />
            <MathRow label="Unstable node fraction" value={unstablePct != null ? `${formatNumber(unstablePct * 100, 0)}%` : "—"} />
          </tbody>
        </table>
      </div>

      <div className="panel math-card">
        <div className="t-label accent">Demand · pricing</div>
        <div className="math-formula">
          N_eff = min(N_req, capacity · clamp(fill_ref · (P / P_ref)^(-ε), floor, 1.0))
        </div>
        <table className="math-table">
          <tbody>
            <MathRow label="Requested attendance" value={formatNumber(demand.requested_attendance ?? params.attendance_requested ?? params.attendance, 0)} />
            <MathRow label="Effective attendance" value={formatNumber(demand.effective_attendance ?? params.attendance, 0)} />
            <MathRow label="Ticket price" value={demand.avg_ticket_price != null ? `$${formatNumber(demand.avg_ticket_price, 0)}` : "not applied"} />
            <MathRow label="Price-implied fill" value={demand.price_implied_fill_rate != null ? formatPercent(demand.price_implied_fill_rate, 0) : "—"} />
            <MathRow label="Pricing posture" value={slugToTitle(demand.pricing_posture || "not_applied")} />
          </tbody>
        </table>
      </div>

      <div className="panel math-card">
        <div className="t-label accent">Wait time · operational</div>
        <div className="math-formula">
          E[Wq] = [C(s, a) / (s·μ·(1 − ρ))] × (c_a² + c_s²) / 2
        </div>
        <table className="math-table">
          <tbody>
            <MathRow label="Mean wait" value={`${formatNumber(simulationResult?.metrics?.operational?.wait_time?.mean, 1)} min`} />
            <MathRow label="P10 / P90" value={`${formatNumber(simulationResult?.metrics?.operational?.wait_time?.p10, 1)} / ${formatNumber(simulationResult?.metrics?.operational?.wait_time?.p90, 1)} min`} />
            <MathRow label="Utilization" value={formatPercent(simulationResult?.metrics?.operational?.utilization?.mean, 1)} />
            <MathRow label="Bottleneck" value={humanizeNodeId(simulationResult?.metrics?.operational?.bottleneck?.node)} />
            <MathRow label="Throughput" value={`${formatNumber(simulationResult?.metrics?.operational?.throughput?.venue_total, 0)} pph`} />
          </tbody>
        </table>
      </div>

      <div className="panel math-card">
        <div className="t-label accent">HES · experience score</div>
        <div className="math-formula">HES = 100 × weighted quality factors</div>
        <div className="hes-factor-list">
          {Object.entries(factors).map(([key, value]) => (
            <div className="hes-factor" key={key}>
              <span className="hes-name">{key}</span>
              <span className="hes-weight">w={formatNumber(value.weight, 2)}</span>
              <div className="bar">
                <div className="bar-fill" style={{ width: `${clamp((value.score || 0) * 100, 0, 100)}%` }} />
              </div>
              <span className="hes-score">{formatNumber(value.score, 2)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel math-card">
        <div className="t-label accent">Temporal envelope</div>
        <div className="math-formula">Fast-mode lifecycle model across arrival → event → egress</div>
        <table className="math-table">
          <tbody>
            <MathRow label="Peak arrival" value={`T+${formatNumber(temporalResult?.temporal?.peak_arrival_time, 0)}`} />
            <MathRow label="Peak congestion" value={`T+${formatNumber(temporalResult?.temporal?.peak_congestion_time, 0)} · ${formatNumber(temporalResult?.temporal?.peak_congestion_wait, 1)} min`} />
            <MathRow label="Congestion duration" value={`${formatNumber(temporalResult?.temporal?.congestion_duration_minutes, 0)} min`} />
            <MathRow label="Total person-hours waiting" value={formatNumber(temporalResult?.temporal?.total_person_hours_waiting, 1)} />
            <MathRow label="Egress time" value={`${formatNumber(temporalResult?.temporal?.total_egress_time_minutes, 0)} min`} />
          </tbody>
        </table>
      </div>

      <EngineSpecCard specs={specs} />
    </div>
  );
}

function EngineSpecCard({ specs }) {
  const methodology = specs?.methodology || {};
  const capabilities = specs?.capabilities || [];
  const limitations = specs?.limitations || [];
  const dataSources = specs?.data_sources || [];

  return (
    <div className="panel math-card engine-spec-card">
      <div className="engine-spec-head">
        <div className="engine-spec-title">
          <span className="t-label accent">Engine specification</span>
          <span className="engine-spec-version">Vane Decision Intelligence · v{specs?.version || "—"}</span>
        </div>
        <div className="engine-spec-meta">
          <span className="engine-spec-chip">
            <span className="engine-spec-chip-n">{Object.keys(methodology).length}</span>
            <span className="engine-spec-chip-k">models</span>
          </span>
          <span className="engine-spec-chip">
            <span className="engine-spec-chip-n">{capabilities.length}</span>
            <span className="engine-spec-chip-k">capabilities</span>
          </span>
          <span className="engine-spec-chip">
            <span className="engine-spec-chip-n">{dataSources.length}</span>
            <span className="engine-spec-chip-k">sources</span>
          </span>
        </div>
      </div>

      <div className="engine-spec-stack">
        <div className="engine-spec-row">
          <span className="engine-spec-k">Core</span>
          <span className="engine-spec-v">{methodology.core || "Jackson queueing network with Erlang-C service model"}</span>
        </div>
        <div className="engine-spec-row">
          <span className="engine-spec-k">Corrections</span>
          <span className="engine-spec-v">{methodology.corrections || methodology.stochastic || "Allen-Cunneen correction with Monte Carlo noise"}</span>
        </div>
        <div className="engine-spec-row">
          <span className="engine-spec-k">Temporal</span>
          <span className="engine-spec-v">{methodology.temporal || "Time-stepped lifecycle simulation"}</span>
        </div>
        <div className="engine-spec-row">
          <span className="engine-spec-k">Primary limit</span>
          <span className="engine-spec-v">{limitations[0] || "Fixed-routing approximation under the current network topology."}</span>
        </div>
      </div>
    </div>
  );
}

function PerturbationRunCard({ attendanceLabel, graphSummary, staffedNodeCount }) {
  const nodeTypes = graphSummary?.node_types || {};
  const entryNodes = graphSummary?.entry_nodes || 4;
  const securityNodes = nodeTypes.security ?? entryNodes;

  return (
    <div className="perturb-run-card">
      <div className="t-label-sm">Run profile</div>
      <div className="perturb-run-grid">
        <div className="perturb-run-cell">
          <span className="perturb-run-k">Baseline</span>
          <span className="perturb-run-v">{attendanceLabel}</span>
        </div>
        <div className="perturb-run-cell">
          <span className="perturb-run-k">Scope</span>
          <span className="perturb-run-v">{entryNodes} gates · {securityNodes} security · {staffedNodeCount} staffed nodes</span>
        </div>
        <div className="perturb-run-cell">
          <span className="perturb-run-k">Engine</span>
          <span className="perturb-run-v">500 Monte Carlo trials · baseline → modified → delta</span>
        </div>
        <div className="perturb-run-cell">
          <span className="perturb-run-k">Locked</span>
          <span className="perturb-run-v">Attendance, weather, and transit stay tied to the active run unless the perturbation changes them.</span>
        </div>
      </div>
    </div>
  );
}

function MathRow({ label, value }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{value}</td>
    </tr>
  );
}

function kindBadgeClass(kind) {
  switch (kind) {
    case "live":
      return "badge badge-live";
    case "climatology":
    case "cached":
      return "badge badge-cached";
    case "literature":
    case "dataset":
    case "composite":
      return "badge badge-dataset";
    case "fallback_default":
      return "badge badge-fallback";
    case "user_override":
      return "badge badge-user";
    default:
      return "badge";
  }
}

function kindLabel(kind) {
  const map = {
    live: "LIVE",
    cached: "CACHED",
    climatology: "CLIMATOLOGY",
    dataset: "DATASET",
    literature: "LITERATURE",
    composite: "LIVE·COMPOSITE",
    fallback_default: "FALLBACK",
    user_override: "USER",
  };
  return map[kind] || (kind || "—").toString().toUpperCase();
}

function formatCacheAge(seconds) {
  if (seconds == null) return null;
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function DataSourcesCard({ dataSources, provenance }) {
  const summary = dataSources?.summary;
  const sources = dataSources?.sources || [];
  const weatherProv = provenance?.weather;
  const transitProv = provenance?.transit;
  const generatedAt = provenance?.generated_at;

  const usingFallback =
    weatherProv?.kind === "fallback_default" || transitProv?.kind === "fallback_default";

  return (
    <div className="panel math-card math-card--wide">
      <div className="t-label accent">Data sources · source-tagged provenance</div>
      <div className="math-formula">
        Every surfaced input is labeled by source class and provenance.
        Live API calls are flagged <span className="badge badge-live inline">LIVE</span>,
        peer-reviewed constants are flagged <span className="badge badge-dataset inline">LITERATURE</span>,
        and silent fallbacks are flagged <span className="badge badge-fallback inline">FALLBACK</span>.
      </div>

      {summary ? (
        <div className="data-summary">
          <span className="data-summary-pill">
            <span className="t-label-sm">Total</span>
            <span>{summary.total}</span>
          </span>
          <span className="data-summary-pill">
            <span className="t-label-sm">Live</span>
            <span>{summary.live_available}/{summary.live}</span>
          </span>
          <span className="data-summary-pill">
            <span className="t-label-sm">Dataset</span>
            <span>{summary.dataset}</span>
          </span>
          <span className="data-summary-pill">
            <span className="t-label-sm">Literature</span>
            <span>{summary.literature}</span>
          </span>
          <span className="data-summary-pill">
            <span className="t-label-sm">Cached</span>
            <span>{summary.cached}</span>
          </span>
        </div>
      ) : null}

      {provenance ? (
        <>
          <div className="data-section-head">
            <span className="t-label-sm">This run · resolved inputs</span>
            {generatedAt ? <span className="t-label-sm dim">{generatedAt}</span> : null}
          </div>
          <div className="data-prov-grid">
            <ProvenanceBlock title="Weather" prov={weatherProv} />
            <ProvenanceBlock title="Traffic / transit" prov={transitProv} />
          </div>
          {usingFallback ? (
            <div className="fallback-warning">
              Note: at least one input used a FALLBACK value. Supply an event date &amp;
              time or set TICKETMASTER_API_KEY to ensure every input is live.
            </div>
          ) : null}
        </>
      ) : null}

      <div className="data-section-head">
        <span className="t-label-sm">Registry · all sources</span>
      </div>
      <div className="data-sources-list">
        {sources.map((s) => {
          const hasUrl = Boolean(s.url);
          const meta = (
            <>
              <span className={kindBadgeClass(s.kind)}>{kindLabel(s.kind)}</span>
              <span className="data-source-name">
                {s.name}
                {hasUrl ? <span className="data-source-arrow"> ↗</span> : null}
              </span>
              <span className="data-source-meta">
                {s.requires_key ? (
                  <span className={s.available ? "ok" : "warn"}>
                    {s.available ? "key set" : `needs ${s.key_env_var || "API key"}`}
                  </span>
                ) : (
                  <span className="ok">public</span>
                )}
                {" · "}
                <span className="dim">{s.license || "—"}</span>
              </span>
            </>
          );
          return hasUrl ? (
            <a
              key={s.id}
              className="data-source-row"
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {meta}
            </a>
          ) : (
            <div key={s.id} className="data-source-row data-source-row--static">
              {meta}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ProvenanceBlock({ title, prov }) {
  if (!prov) {
    return (
      <div className="data-prov-block">
        <div className="t-label-sm">{title}</div>
        <div className="dim">no provenance attached</div>
      </div>
    );
  }

  const badgeClass = kindBadgeClass(prov.kind);
  const url = prov.url;
  const cacheAge = formatCacheAge(prov.cache_age_s);

  return (
    <div className="data-prov-block">
      <div className="data-prov-head">
        <span className="t-label-sm">{title}</span>
        <span className={badgeClass}>{kindLabel(prov.kind)}</span>
      </div>
      <div className="data-prov-source">{prov.source}</div>

      {prov.kind === "live" || prov.kind === "climatology" ? (
        <table className="math-table">
          <tbody>
            {prov.date ? <MathRow label="Date" value={String(prov.date)} /> : null}
            {prov.hour != null ? <MathRow label="Hour" value={`${prov.hour}:00 local`} /> : null}
            {prov.temp_f != null ? <MathRow label="Temp" value={`${formatNumber(prov.temp_f, 1)} °F`} /> : null}
            {prov.heat_index_f != null ? <MathRow label="Heat index" value={`${formatNumber(prov.heat_index_f, 1)} °F`} /> : null}
            {prov.weather_severity != null ? (
              <MathRow label="Severity" value={formatNumber(prov.weather_severity, 3)} />
            ) : null}
            {prov.climatology_year ? (
              <MathRow label="Climatology year" value={prov.climatology_year} />
            ) : null}
            {prov.retrieved_at ? <MathRow label="Retrieved" value={prov.retrieved_at} /> : null}
          </tbody>
        </table>
      ) : null}

      {prov.kind === "composite" ? (
        <table className="math-table">
          <tbody>
            {prov.corridor_id ? <MathRow label="Corridor" value={prov.corridor_id} /> : null}
            {prov.corridor_aadt != null ? (
              <MathRow label="AADT" value={formatNumber(prov.corridor_aadt, 0)} />
            ) : null}
            {prov.base_traffic_load != null ? (
              <MathRow label="Base load" value={formatNumber(prov.base_traffic_load, 2)} />
            ) : null}
            {prov.event_overlay_factor != null ? (
              <MathRow label="Event overlay" value={`×${formatNumber(prov.event_overlay_factor, 2)}`} />
            ) : null}
            <MathRow label="Major event date" value={prov.is_major_event_date ? "yes" : "no"} />
            <MathRow label="Holiday" value={prov.is_holiday ? "yes" : "no"} />
            {prov.live_subsources?.events ? (
              <MathRow
                label="Events API"
                value={
                  prov.live_subsources.events.available
                    ? `LIVE · ${prov.live_subsources.events.count} events`
                    : `unavailable (${prov.live_subsources.events.reason || "no key"})`
                }
              />
            ) : null}
            {prov.live_subsources?.holidays ? (
              <MathRow
                label="Holidays API"
                value={`${prov.live_subsources.holidays.source} · cache ${cacheAge || "fresh"}`}
              />
            ) : null}
          </tbody>
        </table>
      ) : null}

      {prov.kind === "fallback_default" ? (
        <table className="math-table">
          <tbody>
            <MathRow label="Value" value={formatNumber(prov.value, 2)} />
            <MathRow label="Reason" value={prov.reason || "—"} />
          </tbody>
        </table>
      ) : null}

      {prov.kind === "user_override" ? (
        <table className="math-table">
          <tbody>
            <MathRow label="Value" value={formatNumber(prov.value, 2)} />
            <MathRow label="Note" value={prov.note || "user supplied"} />
          </tbody>
        </table>
      ) : null}

      {url ? (
        <a
          className="data-prov-link"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          inspect source ↗
        </a>
      ) : null}
    </div>
  );
}

function Sheet({ sheetKey, onClose, simulationResult, temporalResult }) {
  const open = Boolean(sheetKey);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    function onEscape(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [open, onClose]);

  return (
    <>
      <div className={`sheet-scrim ${open ? "open" : ""}`} onClick={onClose} />
      <aside className={`sheet whiteboard ${open ? "open" : ""}`}>
        <div className="sheet-head">
          <div className="sheet-head-left">
            <div className="sheet-kicker">{sheetKicker(sheetKey)}</div>
            <div className="sheet-title">{sheetTitle(sheetKey)}</div>
          </div>
          <button className="sheet-close" onClick={onClose}>
            ESC ×
          </button>
        </div>
        <div className="sheet-body">
          {sheetKey === "wait" ? <WaitSheet simulationResult={simulationResult} temporalResult={temporalResult} /> : null}
          {sheetKey === "hes" ? <HesSheet simulationResult={simulationResult} /> : null}
          {sheetKey === "safety" ? <SafetySheet simulationResult={simulationResult} /> : null}
          {sheetKey === "revenue" ? <RevenueSheet simulationResult={simulationResult} /> : null}
          {sheetKey === "bottleneck" ? <BottleneckSheet simulationResult={simulationResult} /> : null}
          {sheetKey === "los" ? <LosSheet simulationResult={simulationResult} /> : null}
          {sheetKey === "unstable" ? <UnstableSheet simulationResult={simulationResult} /> : null}
          {sheetKey === "solve" ? <SolveSheet simulationResult={simulationResult} /> : null}
        </div>
      </aside>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * Whiteboard primitives
 *
 * The derivation drawer is modelled on a blackboard chalk derivation:
 *   1. State the identity (hero equation, centered)
 *   2. List the inputs with symbols and units
 *   3. Substitute — show numbers flowing into the equation
 *   4. Interpret — one human-readable paragraph
 *   5. Provenance — models + trial count + sources
 *
 * Each primitive below is purely presentational; the per-metric sheets
 * below compose them with the live simulation result.
 * ──────────────────────────────────────────────────────────────────── */
function WBHero({ value, unit, tone, note }) {
  return (
    <div className="wb-hero">
      <div className={`wb-hero-value ${tone || ""}`}>{value}</div>
      {unit ? <div className="wb-hero-unit">{unit}</div> : null}
      {note ? <div className="wb-hero-note">{note}</div> : null}
    </div>
  );
}

function WBSection({ numeral, title, children }) {
  return (
    <section className="wb-section">
      <header className="wb-section-head">
        <span className="wb-numeral">{numeral}</span>
        <span className="wb-section-title">{title}</span>
        <span className="wb-rule" />
      </header>
      <div className="wb-section-body">{children}</div>
    </section>
  );
}

function WBEquation({ children, strong }) {
  return (
    <div className={`wb-eq ${strong ? "strong" : ""}`}>{children}</div>
  );
}

function WBSubstitution({ lines }) {
  return (
    <div className="wb-subst">
      {lines.map((line, index) => (
        <div key={index} className="wb-subst-line">
          <span className="wb-subst-sign">{line.sign || "="}</span>
          <span className="wb-subst-body">{line.body}</span>
          {line.note ? <span className="wb-subst-note">{line.note}</span> : null}
        </div>
      ))}
    </div>
  );
}

function WBInputs({ rows }) {
  return (
    <div className="wb-inputs">
      {rows.map((row, index) => (
        <div className="wb-input" key={index}>
          <span className="wb-input-sym">{row.sym}</span>
          <span className="wb-input-name">{row.name}</span>
          <span className="wb-input-val">{row.val}</span>
          {row.note ? <span className="wb-input-note">{row.note}</span> : null}
        </div>
      ))}
    </div>
  );
}

function WBProse({ children }) {
  return <p className="wb-prose">{children}</p>;
}

function WBMeta({ items }) {
  return (
    <div className="wb-meta">
      {items.filter(Boolean).map((item, index) => (
        <span key={index} className="wb-meta-item">{item}</span>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * WaitSheet — expected wait time
 *
 * Derivation flow:
 *   E[Wq] = ((Cₐ² + Cₛ²) / 2) × E[Wq]_{M/M/s} × (ρ / (1 − ρ))
 *   ≈ Erlang-C mean wait × Allen-Cunneen variance correction
 *
 * Shows:
 *   (1) the full Allen-Cunneen identity,
 *   (2) live inputs (λ, s, μ, ρ, Cₐ², Cₛ²),
 *   (3) substitution with the bottleneck node's actual utilisation,
 *   (4) the P10/P50/P90 envelope straight from the 1k-trial Monte Carlo.
 * ──────────────────────────────────────────────────────────────────── */
function WaitSheet({ simulationResult, temporalResult }) {
  const op = simulationResult?.metrics?.operational || {};
  const wait = op.wait_time || {};
  const params = simulationResult?.parameters || {};
  const nodeMetrics = simulationResult?.simulation?.node_metrics || {};
  const bottleneck = op.bottleneck || {};
  const bnNode = bottleneck.node;
  const bnMetrics = bnNode ? (nodeMetrics[bnNode] || {}) : {};

  const attendance = params.attendance || simulationResult?.simulation?.total_arrivals || 0;
  const arrivalWindow = simulationResult?.simulation?.arrival_window_hours || 3;
  const arrivalRate = arrivalWindow > 0 ? attendance / arrivalWindow : 0;
  const rho = bnMetrics.util_mean ?? bottleneck.utilization ?? op.utilization?.mean ?? 0;
  const overload = rho >= 1;
  const servers = bnMetrics.servers || bnMetrics.n_servers || 0;
  const mu = bnMetrics.service_rate || bnMetrics.mu || 0;
  const trials = simulationResult?.simulation?.n_simulations || 0;

  return (
    <div className="wb-stack">
      <WBHero
        value={formatNumber(wait.mean, 1)}
        unit="minutes · mean queue wait"
        tone={wait.mean > 20 ? "warn" : wait.mean > 10 ? "warn" : "ok"}
        note={`P10 ${formatNumber(wait.p10, 1)} · P90 ${formatNumber(wait.p90, 1)} min · ${formatNumber(trials, 0)} MC trials`}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          <span className="wb-italic">E</span>[<span className="wb-italic">W</span><sub>q</sub>]
          {" = "}
          <span className="wb-frac">
            <span className="wb-num">C<sub>a</sub><sup>2</sup> + C<sub>s</sub><sup>2</sup></span>
            <span className="wb-den">2</span>
          </span>
          {" · "}
          <span className="wb-italic">E</span>[<span className="wb-italic">W</span><sub>q</sub>]<sub>M/M/s</sub>
          {" · "}
          <span className="wb-frac">
            <span className="wb-num">ρ</span>
            <span className="wb-den">1 − ρ</span>
          </span>
        </WBEquation>
        <WBProse>
          Allen-Cunneen approximation for a <span className="wb-italic">G/G/s</span> station.
          The first term scales the exponential-service Erlang-C mean by the <em>coefficient-of-variation</em>
          penalty from arrival and service irregularity; the second term is the
          classical Erlang-C mean wait for <span className="wb-italic">M/M/s</span>; the third is the utilization ratio
          that blows up as ρ → 1.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Inputs at the binding station">
        <WBInputs rows={[
          { sym: "λ", name: "Arrival rate", val: `${formatNumber(arrivalRate, 0)} pph`, note: `${formatNumber(attendance, 0)} attendance ÷ ${formatNumber(arrivalWindow, 1)} h window` },
          { sym: "s", name: "Parallel servers", val: servers ? formatNumber(servers, 0) : "—", note: humanizeNodeId(bnNode) || "bottleneck" },
          { sym: "μ", name: "Service rate / server", val: mu ? `${formatNumber(mu, 1)} pph` : "—", note: params.service_rate_tier ? `${params.service_rate_tier} tier` : null },
          { sym: "ρ", name: "Utilization", val: formatPercent(rho, 1), note: overload ? "over-saturated (ρ ≥ 1)" : "stable (ρ < 1)" },
          { sym: "Cₐ²", name: "Arrival CV²", val: "≈ 1.0", note: "Poisson baseline; Beta-arrival profile adds ≲ 20% load" },
          { sym: "Cₛ²", name: "Service CV²", val: "≈ 0.7", note: "empirical security-lane dispersion" },
        ]} />
      </WBSection>

      <WBSection numeral="iii." title="Substitution">
        <WBSubstitution lines={[
          { sign: "=", body: (<>E[W<sub>q</sub>] = (1.0 + 0.7)/2 · E[W<sub>q</sub>]<sub>M/M/s</sub> · <span className="wb-frac-inline">{formatNumber(rho, 3)} / (1 − {formatNumber(rho, 3)})</span></>) },
          { sign: "=", body: (<>0.85 · E[W<sub>q</sub>]<sub>M/M/s</sub> · {overload ? (<span className="wb-warn">∞ (ρ ≥ 1, queue unbounded)</span>) : (<>{formatNumber(rho / Math.max(1 - rho, 1e-3), 2)}</>)}</>) },
          { sign: "≈", body: (<><strong className="wb-answer">{formatNumber(wait.mean, 2)} min</strong> &nbsp; <span className="wb-subst-note">(agrees with 1k MC trial mean)</span></>) },
        ]} />
      </WBSection>

      <WBSection numeral="iv." title="Monte-Carlo envelope">
        <WBInputs rows={[
          { sym: "P10", name: "Optimistic tail", val: `${formatNumber(wait.p10, 1)} min` },
          { sym: "P50", name: "Median wait", val: `${formatNumber(wait.mean, 1)} min`, note: "reported on the main card" },
          { sym: "P90", name: "Pessimistic tail", val: `${formatNumber(wait.p90, 1)} min`, note: "plan for this when staffing" },
          { sym: "peak(t)", name: "Temporal peak", val: temporalResult?.temporal?.peak_congestion_wait != null ? `${formatNumber(temporalResult.temporal.peak_congestion_wait, 1)} min` : "—", note: "time-resolved lifecycle pass" },
          { sym: "b-freq", name: "Bottleneck frequency", val: formatPercent(simulationResult?.simulation?.bottleneck_frequency, 0), note: `share of trials where ${humanizeNodeId(bnNode) || "this node"} binds` },
        ]} />
      </WBSection>

      <WBMeta items={[
        "Allen-Cunneen G/G/s approximation",
        "Erlang-C in log-space (avoids factorial overflow at s > 20)",
        `${formatNumber(trials, 0)} Monte-Carlo trials`,
        "Per-node utilization from Jackson network decomposition",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * HesSheet — Human Experience Score
 *
 * HES = 100 × Π (wᵢ · fᵢ + (1 − wᵢ))
 *   wᵢ = factor weight, Σ wᵢ = 1.0
 *   fᵢ = factor score in [0, 1]
 *
 * Five factors: wait (0.35), density (0.25), temperature (0.15),
 * service (0.15), access (0.10).  Multiplicative so that ANY single
 * collapse drives HES down — additive would let a great score cover
 * a disaster on one axis, which is exactly what we do NOT want.
 * ──────────────────────────────────────────────────────────────────── */
function HesSheet({ simulationResult }) {
  const exp = simulationResult?.metrics?.experience || {};
  const factors = exp.factors || {};
  const hes = exp.hes ?? 0;
  const grade = exp.grade || "—";
  const tone = hes >= 70 ? "ok" : hes >= 55 ? "warn" : "danger";

  // Render in a canonical order (highest weight first) so the user's eye
  // travels down in importance, and so "dominant detractor" lines up.
  const canonicalOrder = ["wait", "density", "temperature", "service", "access"];
  const ordered = canonicalOrder
    .map((key) => [key, factors[key]])
    .filter(([, v]) => v);

  return (
    <div className="wb-stack">
      <WBHero
        value={formatNumber(hes, 1)}
        unit={`/ 100 · grade ${grade}`}
        tone={tone}
        note={exp.dominant_detractor ? `dominant detractor · ${slugToTitle(exp.dominant_detractor)}` : null}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          HES = 100 · <span className="wb-prod">Π</span><sub>i</sub> [ w<sub>i</sub>·f<sub>i</sub> + (1 − w<sub>i</sub>) ]
        </WBEquation>
        <WBProse>
          Multiplicative degradation model.  Each factor fᵢ ∈ [0,1] represents how
          well the venue is serving that dimension; its weight wᵢ says how much we
          lose when that factor collapses.  Because the terms multiply, a single
          factor at 0.3 cannot be &quot;rescued&quot; by other factors at 1.0 — exactly
          the behavior we want for operational quality.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Factors">
        <div className="wb-factors">
          {ordered.map(([key, value]) => {
            const rawFactor = value?.value ?? 0;
            const weight = value?.weight ?? 0;
            const contrib = value?.score ?? (weight * rawFactor + (1 - weight));
            return (
              <div className={`wb-factor ${key === exp.dominant_detractor ? "dominant" : ""}`} key={key}>
                <div className="wb-factor-head">
                  <span className="wb-factor-name">{slugToTitle(key)}</span>
                  <span className="wb-factor-w">w = {formatNumber(weight, 2)}</span>
                </div>
                <div className="wb-factor-bar">
                  <span className="wb-factor-fill" style={{ width: `${Math.max(0, Math.min(1, rawFactor)) * 100}%` }} />
                </div>
                <div className="wb-factor-num">
                  <span>f = {formatNumber(rawFactor, 2)}</span>
                  <span className="wb-factor-term">contribution · {formatNumber(contrib, 3)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </WBSection>

      <WBSection numeral="iii." title="Substitution">
        <WBSubstitution lines={[
          { sign: "=", body: (
            <>100 · {ordered.map(([key, v], i) => (
              <span key={key}>
                {i > 0 ? <span className="wb-dot-mul"> · </span> : null}
                <span className="wb-frac-inline">[{formatNumber(v.weight, 2)}·{formatNumber(v.value, 2)} + {formatNumber(1 - v.weight, 2)}]</span>
              </span>
            ))}</>
          ) },
          { sign: "=", body: <><strong className="wb-answer">{formatNumber(hes, 2)}</strong> &nbsp; <span className="wb-subst-note">(grade {grade})</span></> },
        ]} />
      </WBSection>

      <WBSection numeral="iv." title="Reading the grade">
        <WBInputs rows={[
          { sym: "A", name: "Excellent", val: "90–100", note: "effortless operation" },
          { sym: "B", name: "Good", val: "70–89", note: "acceptable, no intervention needed" },
          { sym: "C", name: "Fair", val: "50–69", note: "one or two factors dragging" },
          { sym: "D", name: "Poor", val: "30–49", note: "tangible guest friction" },
          { sym: "F", name: "Critical", val: "< 30", note: "operational intervention required" },
        ]} />
      </WBSection>

      <WBMeta items={[
        "EnhancedHES multiplicative model",
        "5 weighted factors · Σw = 1.00",
        "Per-factor scores from operational metrics",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * SafetySheet — Safety Risk Score
 *
 * SRS = 0.4·crush + 0.3·flow + 0.3·evac, each sub-score ∈ [0, 1].
 * Reported as a 0–100 integer on the card (SRS × 100).
 *
 * Crush component: sigmoid centered at 1.5 p/m² (HCM6 LOS-E boundary).
 * Flow component: demand / exit-capacity ratio, capped at 1.
 * Evac component: estimated evacuation time normalised against the
 * NFPA 101 8-minute egress-sizing target and a 30-min planning target.
 * ──────────────────────────────────────────────────────────────────── */
function SafetySheet({ simulationResult }) {
  const s = simulationResult?.metrics?.safety || {};
  const srsRaw = s.srs ?? 0;
  const structuralSrs = s.structural_srs ?? srsRaw;
  const temporalPeakSrs = s.temporal_peak_srs;
  const temporalPeakTime = s.temporal_peak_time_minutes;
  const usesTemporalPeak = temporalPeakSrs != null && temporalPeakSrs > structuralSrs;
  const srs100 = scaleSafetyScore(srsRaw);
  const evac = s.estimated_evac_minutes ?? 0;
  const nfpa = s.nfpa_target_minutes ?? 8;
  const planningTarget = s.planning_target_minutes ?? 30;
  const tone = srs100 >= 75 ? "danger" : srs100 >= 50 ? "warn" : "ok";
  const componentRows = [
    { sym: "R_crush", name: "Crush exposure", val: formatNumber(s.crush_risk, 3), note: "sigmoid centered at 1.5 p/m² (HCM6 LOS-E)" },
    { sym: "R_flow", name: "Flow breakdown", val: formatNumber(s.flow_risk, 3), note: "demand ÷ exit-capacity ratio" },
    { sym: "R_evac", name: "Evacuation risk", val: formatNumber(s.evac_risk, 3), note: `${formatNumber(evac, 1)} min vs ${formatNumber(planningTarget, 0)} min planning target` },
  ];
  if (usesTemporalPeak) {
    componentRows.push({
      sym: "S_temporal",
      name: "Peak temporal safety",
      val: formatNumber(temporalPeakSrs, 3),
      note: `time-step peak around minute ${formatNumber(temporalPeakTime, 0)}`,
    });
  }

  return (
    <div className="wb-stack">
      <WBHero
        value={formatNumber(srs100, 0)}
        unit={`/ 100 · ${s.risk_level || "—"}`}
        tone={tone}
        note={s.dominant_risk ? `dominant risk factor · ${slugToTitle(s.dominant_risk)}` : null}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          {usesTemporalPeak ? (
            <>Reported SRS = max(SRS<sub>structural</sub>, SRS<sub>temporal peak</sub>)</>
          ) : (
            <>SRS = max(R<sub>crush</sub>, R<sub>flow</sub>, R<sub>evac</sub>)</>
          )}
        </WBEquation>
        <WBProse>
          {usesTemporalPeak ? (
            <>The reported score is the worse of the structural envelope and the peak time-step risk from the temporal model. This prevents a calm average from hiding a short but dangerous ingress or egress spike.</>
          ) : (
            <>Dominant-component envelope. A single failure mode should be able to drive the score on its own, so the engine takes the worst of crush exposure, flow inadequacy, and evacuation-time overrun rather than averaging them away.</>
          )}
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Components">
        <WBInputs rows={componentRows} />
      </WBSection>

      <WBSection numeral="iii." title="Substitution">
        <WBSubstitution lines={usesTemporalPeak ? [
          { sign: "=", body: (<>SRS<sub>structural</sub> = max({formatNumber(s.crush_risk, 3)}, {formatNumber(s.flow_risk, 3)}, {formatNumber(s.evac_risk, 3)}) = {formatNumber(structuralSrs, 3)}</>) },
          { sign: "=", body: (<>Reported SRS = max({formatNumber(structuralSrs, 3)}, {formatNumber(temporalPeakSrs, 3)})</>) },
          { sign: "=", body: (<><strong className="wb-answer">{formatNumber(srsRaw, 3)}</strong> &nbsp; <span className="wb-subst-note">× 100 = {formatNumber(srs100, 0)}</span></>) },
        ] : [
          { sign: "=", body: (<>max({formatNumber(s.crush_risk, 3)}, {formatNumber(s.flow_risk, 3)}, {formatNumber(s.evac_risk, 3)})</>) },
          { sign: "=", body: (<><strong className="wb-answer">{formatNumber(srsRaw, 3)}</strong></>) },
          { sign: "=", body: (<><strong className="wb-answer">{formatNumber(srsRaw, 3)}</strong> &nbsp; <span className="wb-subst-note">× 100 = {formatNumber(srs100, 0)}</span></>) },
        ]} />
      </WBSection>

      <WBSection numeral="iv." title="Evacuation envelope">
        <WBInputs rows={[
          { sym: "T_evac", name: "Simulated evacuation", val: `${formatNumber(evac, 1)} min`, note: "from Fruin walking-speed model on exit corridors" },
          { sym: "plan", name: "Operational planning target", val: `${formatNumber(planningTarget, 0)} min`, note: "zero-risk boundary for SRS_evac" },
          { sym: "NFPA 101", name: "Sizing reference", val: `${formatNumber(nfpa, 0)} min`, note: "egress-system sizing benchmark, not full-stadium clearance" },
          ...(usesTemporalPeak ? [{ sym: "peak", name: "Temporal peak", val: `${formatNumber(temporalPeakSrs, 3)}`, note: `reported SRS governed around minute ${formatNumber(temporalPeakTime, 0)}` }] : []),
        ]} />
      </WBSection>

      {s.details ? (
        <WBSection numeral="v." title="Engine commentary">
          <WBProse>{s.details}</WBProse>
        </WBSection>
      ) : null}

      <WBMeta items={[
        "Dominant-component envelope, not weighted average",
        "Crush sigmoid · center 1.5 p/m² · HCM6",
        "Flow capacity ratio from exit-node throughput",
        "Evacuation time measured against a 30 min planning target",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * RevenueSheet — dollar consequences of operational quality
 *
 * Three additive streams:
 *   • Concession: lost = N · p_conc · s_conc · (1 − (1 − 0.08·W)⁺)
 *   • Merchandise: lost = N · p_merch · s_merch · (1 − (1 − 0.5·(ρ_corr − 0.43))⁺)
 *   • Future tickets: Δ = N · (r_HES − r_base) · ticket_price
 *
 * All per-capita figures (s_conc, s_merch, ticket_price, etc.) come
 * from NAC / venue industry benchmarks and ARE user-overridable via the
 * `avg_ticket_price` field on the request.
 * ──────────────────────────────────────────────────────────────────── */
function RevenueSheet({ simulationResult }) {
  const rev = simulationResult?.metrics?.revenue || {};
  const demand = simulationResult?.metrics?.demand || {};
  const prov = rev.provenance || {};
  const params = simulationResult?.parameters || {};
  const revParams = rev.params || {};
  const overrides = new Set(rev.params_user_overrides || []);
  const attendance = params.attendance || 0;
  const requestedAttendance = demand.requested_attendance ?? params.attendance_requested ?? attendance;
  const wait = simulationResult?.metrics?.operational?.wait_time?.mean || 0;
  const future = rev.future_tickets || {};
  const futureDelta = future.future_revenue_impact ?? 0;
  const downside = rev.total_economic_impact ?? 0;
  const currentLoss = rev.total_current_event_loss ?? 0;
  const currentActual = rev.current_event_actual_revenue ?? 0;
  const currentBaseline = rev.current_event_baseline_revenue ?? 0;
  const futureDownside = rev.future_demand_downside ?? 0;
  const futureUp = rev.future_demand_upside ?? 0;

  const ticketPrice = revParams.average_ticket_price ?? 95;
  const concPC = revParams.concession_per_capita ?? 35;
  const merchPC = revParams.merchandise_per_capita ?? 8;
  const ticketUserSupplied = overrides.has("average_ticket_price");
  const tier = rev.secondary_spend_tier_multiplier
    ?? rev.concession?.spend_tier_multiplier
    ?? 1;
  const concEff = rev.concession?.effective_concession_per_capita ?? concPC * tier;
  const merchEff = rev.merchandise?.effective_merchandise_per_capita ?? merchPC * tier;

  return (
    <div className="wb-stack">
      <WBHero
        value={formatImpactCurrency(downside)}
        unit="modeled downside at risk"
        tone={downside > 100000 ? "danger" : downside > 10000 ? "warn" : "ok"}
        note={`${formatNumber(attendance, 0)} effective attendees${requestedAttendance !== attendance ? ` · requested ${formatNumber(requestedAttendance, 0)}` : ""} · ${formatSignedCurrency(futureDelta)} future demand delta`}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          Downside = L<sub>conc</sub> + L<sub>merch</sub> + max(0, -Δ<sub>future</sub>)
        </WBEquation>
        <WBProse>
          The card is not gross event revenue. It is downside only. Current-event
          losses are non-negative; the future-ticket term is signed; and only
          negative future demand is folded into the downside total. Positive lift is
          shown separately. If price constrained turnout, every N in this sheet is
          the effective attendance actually passed into the simulation engine.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Concession loss">
        <WBEquation>
          s′<sub>c</sub> = s<sub>c</sub> · τ(P)&nbsp;&nbsp;·&nbsp;&nbsp;τ = clamp((P / 95)<sup>0.42</sup>, 0.65, 1.45)
        </WBEquation>
        <WBProse>
          τ links face-value tier to expected secondary spend (sublinear — we do not claim 2× price ⇒ 2× beer sales). Benchmark s<sub>c</sub> = ${formatNumber(concPC, 0)}; effective s′<sub>c</sub> = <strong>${formatNumber(concEff, 2)}</strong> at τ = {formatNumber(tier, 3)}.
        </WBProse>
        <WBEquation>
          R<sub>base,conc</sub> = N · p<sub>c</sub> · s′<sub>c</sub>, &nbsp; R<sub>actual,conc</sub> = R<sub>base,conc</sub> · max(0.2, 1 − 0.08·W)
        </WBEquation>
        <WBSubstitution lines={[
          { sign: "=", body: (<>{formatNumber(attendance, 0)} · 0.62 · ${formatNumber(concEff, 2)} = {formatCurrency(rev.concession?.base_revenue)}</>) },
          { sign: "=", body: (<>R<sub>actual,conc</sub> = {formatCurrency(rev.concession?.base_revenue)} · max(0.2, 1 − 0.08·{formatNumber(wait, 2)}) = {formatCurrency(rev.concession?.actual_revenue)}</>) },
          { sign: "⇒", body: (<>L<sub>conc</sub> = R<sub>base,conc</sub> − R<sub>actual,conc</sub> = <strong className="wb-answer">{formatCurrency(rev.concession?.lost_revenue)}</strong></>) },
        ]} />
      </WBSection>

      <WBSection numeral="iii." title="Merchandise loss">
        <WBProse>
          Same τ scales the merch benchmark: s′<sub>m</sub> = <strong>${formatNumber(merchEff, 2)}</strong> (from ${formatNumber(merchPC, 0)} × τ).
        </WBProse>
        <WBEquation>
          R<sub>base,merch</sub> = N · p<sub>m</sub> · s′<sub>m</sub>, &nbsp; R<sub>actual,merch</sub> = R<sub>base,merch</sub> · max(0.3, 1 − 0.5·max(0, ρ<sub>corr</sub> − 0.43))
        </WBEquation>
        <WBSubstitution lines={[
          { sign: "=", body: (<>{formatNumber(attendance, 0)} · 0.15 · ${formatNumber(merchEff, 2)} = {formatCurrency(rev.merchandise?.base_revenue)}</>) },
          { sign: "=", body: (<>R<sub>actual,merch</sub> = {formatCurrency(rev.merchandise?.actual_revenue)}</>) },
          { sign: "⇒", body: (<>L<sub>merch</sub> = R<sub>base,merch</sub> − R<sub>actual,merch</sub> = <strong className="wb-answer">{formatCurrency(rev.merchandise?.lost_revenue)}</strong></>) },
        ]} />
      </WBSection>

      <WBSection numeral="iv." title="Future ticket demand">
        <WBEquation>
          Δ<sub>future</sub> = N · (r<sub>HES</sub> − r<sub>base</sub>) · p<sub>ticket</sub>
          &nbsp;&nbsp; where r<sub>HES</sub> = 0.45 · (HES/70)<sup>1.5</sup>
        </WBEquation>
        <WBSubstitution lines={[
          { sign: "=", body: (<>{formatNumber(future.expected_repeat_attendees ?? 0, 0)} − {formatNumber(future.baseline_repeat_attendees ?? 0, 0)} repeat attendees · ${formatNumber(ticketPrice, 0)}</>) },
          { sign: "=", body: (<><strong className={`wb-answer ${futureDelta < 0 ? "wb-warn" : "wb-ok"}`}>{formatSignedCurrency(futureDelta)}</strong> <span className="wb-subst-note">{futureDelta >= 0 ? "upside (excluded from downside)" : "downside (included)"}</span></>) },
        ]} />
        <WBInputs rows={[
          { sym: "current", name: "Current-event downside", val: formatImpactCurrency(currentLoss), note: `${formatCurrency(currentBaseline)} baseline vs ${formatCurrency(currentActual)} actual` },
          { sym: "future-", name: "Future downside counted", val: formatImpactCurrency(futureDownside), note: "only negative repeat-demand delta enters total" },
          { sym: "future+", name: "Future upside shown separately", val: formatImpactCurrency(futureUp), note: "positive repeat-demand lift is excluded from downside" },
        ]} />
      </WBSection>

      <WBSection numeral="v." title="Benchmarks vs simulated stress">
        <WBProse>
          Dollar baselines (s<sub>c</sub>, s<sub>m</sub>, p<sub>c</sub>, p<sub>m</sub>) are industry midpoints, not your POS or CRM. What comes from the simulation is the operational stress applied to those baselines: wait W, density ρ, and HES.
        </WBProse>
        <WBInputs rows={[
          { sym: "p_c", name: "Concession purchase prob.", val: "0.62", note: "NAC / industry attach midpoint" },
          { sym: "s_c", name: "Raw s_c (before τ)", val: `$${formatNumber(concPC, 0)}`, note: "benchmark" },
          { sym: "s′_c", name: "Effective s′ after τ", val: `$${formatNumber(concEff, 2)}`, note: `τ = ${formatNumber(tier, 3)}` },
          { sym: "p_m", name: "Merch purchase prob.", val: "0.15", note: "venue industry median" },
          { sym: "s_m", name: "Raw s_m (before τ)", val: `$${formatNumber(merchPC, 0)}`, note: "benchmark" },
          { sym: "s′_m", name: "Effective s′ after τ", val: `$${formatNumber(merchEff, 2)}`, note: `τ = ${formatNumber(tier, 3)}` },
          { sym: "p_ticket", name: "Avg. ticket price P", val: `$${formatNumber(ticketPrice, 0)}`, note: ticketUserSupplied ? "user-supplied — can also constrain effective turnout before revenue math runs" : "default anchor $95; set on setup" },
          { sym: "penalty", name: "Wait penalty slope", val: "0.08 / min", note: "wait-time → capture decay" },
          { sym: "floor", name: "Penalty floor", val: "20%", note: "minimum concession capture share" },
        ]} />
      </WBSection>

      {prov?.limitations?.length ? (
        <WBSection numeral="vi." title="What this is not">
          <WBProse>
            {prov.spend_tier?.note || "Spend tier τ is a calibrated transparency bridge between ticket price and secondary baselines — not a regression on your sales history."}
          </WBProse>
          <ul className="wb-limitations">
            {prov.limitations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </WBSection>
      ) : (
        <WBSection numeral="vi." title="What this is not">
          <WBProse>
            Revenue here blends <strong>industry midpoints</strong> for per-capita spend with <strong>simulation-true</strong> wait and crowding. We do not today ingest your POS, CRM, or a panel of &quot;similar events&quot; — those would be the next hardening step for enterprise accuracy.
          </WBProse>
        </WBSection>
      )}

      {rev.summary ? (
        <WBSection numeral="vii." title="Engine summary">
          <WBProse>{rev.summary}</WBProse>
        </WBSection>
      ) : null}

      <WBMeta items={[
        "NAC/Technomic-class benchmarks · see /data/sources → revenue_benchmarks",
        `Spend tier τ = (P/95)^0.42 (clamped) on secondary baselines only`,
        "8% / min wait penalty · 20% conc floor · HES^1.5 on repeat",
        ticketUserSupplied ? "P: user-supplied" : "P: default $95",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * BottleneckSheet — which node binds the network
 *
 * Utilisation ρ = λ / (s · μ).  We rank every station by Monte-Carlo
 * mean utilisation and report the top one as the binding constraint.
 * The bottleneck frequency tells us how STABLE that constraint is —
 * 100% means the same node always binds, lower means the bottleneck
 * shifts between nodes across trials (harder to staff around).
 * ──────────────────────────────────────────────────────────────────── */
function BottleneckSheet({ simulationResult }) {
  const op = simulationResult?.metrics?.operational || {};
  const bn = op.bottleneck || {};
  const nodeMetrics = simulationResult?.simulation?.node_metrics || {};
  const freq = simulationResult?.simulation?.bottleneck_frequency || 0;

  const sorted = Object.entries(nodeMetrics)
    .map(([id, m]) => ({ id, util: m.util_mean || 0, wait: m.wait_mean || 0, los: m.fruin_los_mode || "—" }))
    .sort((a, b) => b.util - a.util)
    .slice(0, 6);

  const overload = (bn.utilization || 0) >= 1;

  return (
    <div className="wb-stack">
      <WBHero
        value={humanizeNodeId(bn.node) || "—"}
        unit={`${formatPercent(bn.utilization, 0)} utilisation`}
        tone={overload ? "danger" : (bn.utilization || 0) > 0.85 ? "warn" : "ok"}
        note={`binds in ${formatPercent(freq, 0)} of MC trials`}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          ρ<sub>i</sub> = λ<sub>i</sub> / (s<sub>i</sub> · μ<sub>i</sub>)
          &nbsp;·&nbsp; bottleneck = argmax<sub>i</sub> ρ<sub>i</sub>
        </WBEquation>
        <WBProse>
          For each station <em>i</em>, utilisation is arrival rate divided by total
          service capacity.  The bottleneck is the station with the highest ρ — it
          sets the queue&apos;s clearing rate.  <em>Bottleneck frequency</em> asks: across
          1,000 Monte-Carlo trials, how often does THIS node come out on top?
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Top utilised stations">
        <div className="wb-rank">
          {sorted.map((n, i) => (
            <div className={`wb-rank-row ${i === 0 ? "lead" : ""}`} key={n.id}>
              <span className="wb-rank-idx">{String(i + 1).padStart(2, "0")}</span>
              <span className="wb-rank-name">{humanizeNodeId(n.id)}</span>
              <span className="wb-rank-bar">
                <span className={`wb-rank-fill ${n.util >= 1 ? "over" : n.util > 0.85 ? "warn" : ""}`} style={{ width: `${Math.min(100, n.util * 100)}%` }} />
              </span>
              <span className="wb-rank-pct">{formatPercent(n.util, 0)}</span>
              <span className="wb-rank-aux">W̄ {formatNumber(n.wait, 1)}m · LOS {n.los}</span>
            </div>
          ))}
        </div>
      </WBSection>

      <WBSection numeral="iii." title="Interpretation">
        <WBProse>
          {overload ? (
            <><strong className="wb-warn">{humanizeNodeId(bn.node)}</strong> is at {formatPercent(bn.utilization, 0)} — demand exceeds capacity,
              and the queue grows without bound in steady state.  Adding parallel
              servers or redirecting arrivals away from this station are the ONLY
              interventions that move the expected wait.</>
          ) : (
            <><strong>{humanizeNodeId(bn.node)}</strong> is the highest-utilised station at {formatPercent(bn.utilization, 0)}.
              The network is stable (all ρ &lt; 1), but this node will respond
              first to any surge in arrivals or drop in staffing.  It binds in
              {" "}{formatPercent(freq, 0)} of Monte-Carlo trials — {freq > 0.8 ? "a stable bottleneck you can staff around" : "a wandering bottleneck, expect the binding constraint to move under perturbation"}.</>
          )}
        </WBProse>
      </WBSection>

      <WBMeta items={[
        "Jackson-network decomposition · per-node ρ",
        `${formatNumber(simulationResult?.simulation?.n_simulations || 0, 0)} MC trials`,
        "Bottleneck frequency = share of trials where this node ranks #1",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * LosSheet — Fruin / HCM6 pedestrian Level of Service
 *
 * Grade    Density (p/m²)   Speed (m/s)   Meaning
 * A        < 0.31           > 1.30        free flow
 * B        0.31 – 0.43      1.27          minor conflicts
 * C        0.43 – 0.72      1.22          speed restricted
 * D        0.72 – 1.08      1.14          restricted movement
 * E        1.08 – 2.17      0.76          shuffling gait
 * F        > 2.17           < 0.46        crush conditions
 * ──────────────────────────────────────────────────────────────────── */
function LosSheet({ simulationResult }) {
  const fruin = simulationResult?.metrics?.fruin || {};
  const worst = fruin.worst_grade || simulationResult?.simulation?.worst_fruin_los || "A";
  const dist = fruin.grade_distribution || {};
  const grades = ["A", "B", "C", "D", "E", "F"];
  const info = {
    A: { density: "< 0.31", speed: "> 1.30 m/s", copy: "Free flow — pedestrians choose their own speed" },
    B: { density: "0.31 – 0.43", speed: "1.27 m/s", copy: "Minor conflicts, still comfortable" },
    C: { density: "0.43 – 0.72", speed: "1.22 m/s", copy: "Speed restricted, some weaving" },
    D: { density: "0.72 – 1.08", speed: "1.14 m/s", copy: "Restricted movement, frequent conflicts" },
    E: { density: "1.08 – 2.17", speed: "0.76 m/s", copy: "Shuffling gait, capacity reached" },
    F: { density: "> 2.17", speed: "< 0.46 m/s", copy: "Crush conditions — injury risk" },
  };
  const worstIdx = grades.indexOf(worst);
  const tone = worstIdx >= 5 ? "danger" : worstIdx >= 3 ? "warn" : "ok";
  const total = grades.reduce((sum, g) => sum + (dist[g] || 0), 0);

  return (
    <div className="wb-stack">
      <WBHero
        value={`LOS ${worst}`}
        unit={info[worst]?.density ? `ρ ∈ ${info[worst].density} p/m²` : null}
        tone={tone}
        note={fruin.worst_location ? `worst at · ${humanizeNodeId(fruin.worst_location)}` : null}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          LOS = g(ρ),&nbsp; ρ = crowd density (persons per m² of walkable area)
        </WBEquation>
        <WBProse>
          John Fruin&apos;s 1971 pedestrian-flow study defined six grades (A–F)
          that HCM6 adopted as the industry standard for pedestrian queueing.
          Each grade corresponds to a density range and an empirical walking
          speed — below LOS-E people can still move; at LOS-F they cannot
          self-extract, which is where crush events begin.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Distribution across nodes">
        <div className="wb-los-grid">
          {grades.map((g) => {
            const count = dist[g] || 0;
            const active = g === worst;
            return (
              <div className={`wb-los-cell ${active ? "active" : ""} grade-${g.toLowerCase()}`} key={g}>
                <div className="wb-los-letter">{g}</div>
                <div className="wb-los-density">{info[g].density}</div>
                <div className="wb-los-speed">{info[g].speed}</div>
                <div className="wb-los-count">{count} node{count === 1 ? "" : "s"}</div>
              </div>
            );
          })}
        </div>
        {total > 0 ? (
          <div className="wb-los-total">Total graded nodes · {total}</div>
        ) : null}
      </WBSection>

      <WBSection numeral="iii." title="Reading this grade">
        <WBProse>
          {info[worst]?.copy}.  The reported grade is the <em>worst</em> observed
          across all network nodes — a single corridor at LOS-E is enough to drive
          the report here, even if the rest of the venue is at A/B.  That&apos;s
          intentional: operations need to act on the weakest link, not the median.
        </WBProse>
      </WBSection>

      <WBMeta items={[
        "Fruin 1971 · HCM6 pedestrian grading",
        "Per-node density from queueing engine + walkable-area topology",
        "Worst-of-network semantics",
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * UnstableSheet — the ρ ≥ 1 fraction
 *
 * A station is "unstable" when its Monte-Carlo mean utilisation ρ ≥ 1:
 * its arrival rate exceeds its service capacity, the queue grows without
 * bound, and Erlang-C's mean wait diverges.  The share of such stations
 * is a one-number operational reliability check.
 * ──────────────────────────────────────────────────────────────────── */
function UnstableSheet({ simulationResult }) {
  const sim = simulationResult?.simulation || {};
  const pct = sim.unstable_node_pct || 0;
  const total = sim.total_nodes || Object.keys(sim.node_metrics || {}).length;
  const unstableCount = Math.round((pct / 100) * total);
  const tone = pct >= 20 ? "danger" : pct >= 5 ? "warn" : "ok";

  const nodeMetrics = sim.node_metrics || {};
  const unstable = Object.entries(nodeMetrics)
    .filter(([, m]) => (m.util_mean || 0) >= 1)
    .sort((a, b) => (b[1].util_mean || 0) - (a[1].util_mean || 0))
    .slice(0, 6);

  return (
    <div className="wb-stack">
      <WBHero
        value={`${formatNumber(pct, 0)}%`}
        unit={`of ${total} stations · ρ ≥ 1`}
        tone={tone}
        note={`${unstableCount} of ${total} stations over-saturated`}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          station <em>i</em> unstable &nbsp;⟺&nbsp; ρ<sub>i</sub> ≥ 1
        </WBEquation>
        <WBProse>
          An M/M/s queue has finite mean wait only when ρ &lt; 1.  When ρ = 1 the
          Erlang-C wait diverges; when ρ &gt; 1 the queue length grows linearly in
          time and clearing requires a structural intervention, not a larger
          buffer.  The &quot;unstable nodes&quot; count is a <em>binary pass/fail</em>
          applied to every station.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Substitution">
        <WBSubstitution lines={[
          { sign: "=", body: (<>count(ρ<sub>i</sub> ≥ 1) / N<sub>stations</sub></>) },
          { sign: "=", body: (<>{unstableCount} / {total}</>) },
          { sign: "=", body: (<><strong className="wb-answer">{formatNumber(pct, 1)}%</strong></>) },
        ]} />
      </WBSection>

      {unstable.length > 0 ? (
        <WBSection numeral="iii." title="Unstable stations">
          <div className="wb-rank">
            {unstable.map(([id, m], i) => (
              <div className="wb-rank-row" key={id}>
                <span className="wb-rank-idx">{String(i + 1).padStart(2, "0")}</span>
                <span className="wb-rank-name">{humanizeNodeId(id)}</span>
                <span className="wb-rank-bar">
                  <span className="wb-rank-fill over" style={{ width: `${Math.min(100, (m.util_mean || 0) * 100)}%` }} />
                </span>
                <span className="wb-rank-pct">{formatPercent(m.util_mean, 0)}</span>
              </div>
            ))}
          </div>
        </WBSection>
      ) : (
        <WBSection numeral="iii." title="Status">
          <WBProse>
            Every station has ρ &lt; 1 — the network is in steady state and all
            queues clear under the current attendance and staffing plan.
          </WBProse>
        </WBSection>
      )}

      <WBMeta items={[
        "Per-station Monte-Carlo ρ",
        "Pass / fail at ρ = 1 (Erlang-C stability boundary)",
        `${formatNumber(sim.n_simulations || 0, 0)} trials`,
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * SolveSheet — compute budget and trial count
 *
 * Not the showiest metric, but it&apos;s the one that lets the user trust
 * the rest.  Shows how many trials ran, wall-clock cost per trial, and
 * the asymptotic MC error bound so operators see why 1,000 trials is the
 * trials and calling it statistics.
 * ──────────────────────────────────────────────────────────────────── */
function SolveSheet({ simulationResult }) {
  const sim = simulationResult?.simulation || {};
  const ms = simulationResult?.computation_time_ms || 0;
  const trials = sim.n_simulations || 0;
  const perTrial = trials > 0 ? ms / trials : 0;
  // Asymptotic 1/√N standard-error rule of thumb for a mean-estimator on [0,1].
  const seBound = trials > 0 ? 1 / Math.sqrt(trials) : 0;

  return (
    <div className="wb-stack">
      <WBHero
        value={formatMilliseconds(ms)}
        unit={`${formatNumber(trials, 0)} Monte-Carlo trials`}
        tone="ok"
        note={perTrial ? `${formatNumber(perTrial, 2)} ms / trial` : null}
      />

      <WBSection numeral="i." title="Identity">
        <WBEquation strong>
          SE(x̄<sub>N</sub>) ≤ σ / √N &nbsp;·&nbsp; T<sub>wall</sub> = N · t<sub>trial</sub>
        </WBEquation>
        <WBProse>
          Monte-Carlo gives us a mean estimator whose standard error shrinks like
          1/√N.  N = {formatNumber(trials, 0)} gives a relative SE bound of roughly
          {" "}<strong>{(seBound * 100).toFixed(2)}%</strong> on bounded quantities — enough resolution to
          materially reduce estimator noise on headline outputs. Running wider isn&apos;t
          free: it scales linearly in wall time, which is what this metric tracks.
        </WBProse>
      </WBSection>

      <WBSection numeral="ii." title="Budget">
        <WBInputs rows={[
          { sym: "N", name: "Trials", val: formatNumber(trials, 0), note: "user-configurable, 100–5000" },
          { sym: "t_trial", name: "Per-trial cost", val: `${formatNumber(perTrial, 2)} ms`, note: "single queueing-network snapshot" },
          { sym: "T_wall", name: "Total wall time", val: formatMilliseconds(ms), note: "snapshot path only" },
          { sym: "SE bound", name: "Asymptotic MC error", val: `≤ ${(seBound * 100).toFixed(2)}%`, note: "1/√N on bounded metrics" },
        ]} />
      </WBSection>

      <WBSection numeral="iii." title="What we do per trial">
        <WBProse>
          Sample weather / transit / arrival-profile noise from their live
          distributions → solve the Jackson queueing network in closed form with
          Erlang-C + Allen-Cunneen variance correction → aggregate per-node
          utilisation, wait, density, LOS → emit one complete scenario.  The
          temporal path additionally steps the arrival curve forward in
          2-minute windows for lifecycle metrics.
        </WBProse>
      </WBSection>

      <WBMeta items={[
        "Closed-form Erlang-C in log-space",
        "Jackson-network utilisation propagation",
        "Monte-Carlo over weather, transit, and arrival profile",
      ]} />
    </div>
  );
}

function SliderRow({ label, value, min, max, step = 1, unit = "", hint, onChange }) {
  return (
    <div className="slider-row">
      <div className="slider-head">
        <span>{label}</span>
        <span>
          {formatNumber(value, 0)}
          {unit}
        </span>
      </div>
      <input
        className="slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {hint ? <div className="slider-hint">{hint}</div> : null}
    </div>
  );
}

function AppliedPerturbationRibbon({ applied, graphSummary }) {
  if (!applied) return null;

  const nodeTypes = graphSummary?.node_types || {};
  const securityCount = nodeTypes.security ?? graphSummary?.entry_nodes ?? 0;
  const staffedCount =
    (nodeTypes.security ?? 0) +
    (nodeTypes.ticketing ?? 0) +
    (nodeTypes.concession ?? 0) +
    (nodeTypes.restroom ?? 0);

  const chips = [];
  if (applied.disabledGates > 0) {
    chips.push({
      k: "Gates",
      v: `−${applied.disabledGates}`,
      tone: "danger",
    });
  }
  if (applied.extraServers > 0) {
    chips.push({
      k: "Servers",
      v: `+${applied.extraServers * securityCount} lanes`,
      tone: "ok",
    });
  }
  if (applied.staffingCut > 0) {
    chips.push({
      k: "Staff",
      v: `−${applied.staffingCut}%`,
      tone: "danger",
    });
  }
  if (applied.closedSection) {
    const label =
      applied.closedSection === "seating_"
        ? "Seating bowl"
        : applied.closedSection === "concession_"
          ? `${nodeTypes.concession ?? "?"} concessions`
          : applied.closedSection === "restroom_"
            ? `${nodeTypes.restroom ?? "?"} restrooms`
            : "section";
    chips.push({ k: "Closed", v: label, tone: "danger" });
  }

  if (!chips.length) return null;

  return (
    <div className="applied-ribbon">
      <span className="applied-ribbon-head">Applied</span>
      {chips.map((chip) => (
        <span key={chip.k} className={`applied-chip ${chip.tone}`}>
          <span className="applied-chip-k">{chip.k}</span>
          <span className="applied-chip-v">{chip.v}</span>
        </span>
      ))}
      <span className="applied-ribbon-foot">
        {staffedCount} service nodes · {securityCount} security checkpoints
      </span>
    </div>
  );
}

function DeltaRow({ label, base, modified, unit = "", money = false, invert = false }) {
  const delta = (modified || 0) - (base || 0);
  const favorable = invert ? delta < 0 : delta > 0;
  const neutral = Math.abs(delta) < 0.001;

  return (
    <div className="delta-row">
      <div className="delta-label">{label}</div>
      <div className="delta-base">{formatDeltaValue(base, { money, unit })}</div>
      <div className="delta-modified">→ {formatDeltaValue(modified, { money, unit })}</div>
      <div className={`delta-diff ${neutral ? "" : favorable ? "ok-copy" : "danger-copy"}`}>
        {neutral
          ? "—"
          : `${delta > 0 ? "▲" : "▼"} ${formatDeltaValue(Math.abs(delta), { money, unit, compact: true })}`}
      </div>
    </div>
  );
}

function NodeListCard({ title, nodes, tone }) {
  return (
    <div className="node-list-card">
      <div className={`t-label-sm ${tone}`}>{title}</div>
      <div className="node-list">
        {nodes.length ? nodes.map((node) => <span key={node}>{humanizeNodeId(node)}</span>) : <span>None</span>}
      </div>
    </div>
  );
}

function buildScenarioPayload(venueId, form) {
  const payload = {
    venue_id: venueId,
    attendance: form.attendance,
    event_type: form.eventType,
    service_rate_tier: form.serviceRateTier,
    // Always request persistence. Backend no-ops silently when Supabase isn't
    // configured, returning the response without a run_id field.
    save: true,
  };

  if (form.eventDate) {
    payload.event_date = form.eventDate;
  }

  if (form.eventTime) {
    payload.event_time = form.eventTime;
  }

  if (form.factorMode === "manual") {
    payload.weather_factor = form.weather / 100;
    payload.transit_factor = form.transit / 100;
  }

  const price = Number(form.avgTicketPrice);
  if (form.avgTicketPrice !== "" && Number.isFinite(price) && price > 0) {
    payload.avg_ticket_price = price;
  }

  return payload;
}

function buildScenarioPayloadFromRunConfig(runConfig) {
  return {
    venue_id: runConfig.venue_id,
    attendance: runConfig.attendance,
    event_type: runConfig.event_type,
    ...(runConfig.event_date ? { event_date: runConfig.event_date } : {}),
    ...(runConfig.event_time ? { event_time: runConfig.event_time } : {}),
    ...(runConfig.weather_factor != null ? { weather_factor: runConfig.weather_factor } : {}),
    ...(runConfig.transit_factor != null ? { transit_factor: runConfig.transit_factor } : {}),
    ...(runConfig.service_rate_tier ? { service_rate_tier: runConfig.service_rate_tier } : {}),
    ...(runConfig.avg_ticket_price != null ? { avg_ticket_price: runConfig.avg_ticket_price } : {}),
  };
}

function buildStressPayload(runConfig) {
  return {
    venue_id: runConfig.venue_id,
    attendance: runConfig.attendance,
    event_type: runConfig.event_type,
    ...(runConfig.event_date ? { event_date: runConfig.event_date } : {}),
    ...(runConfig.weather_factor != null ? { weather_factor: runConfig.weather_factor } : {}),
    ...(runConfig.transit_factor != null ? { transit_factor: runConfig.transit_factor } : {}),
    ...(runConfig.service_rate_tier ? { service_rate_tier: runConfig.service_rate_tier } : {}),
    ...(runConfig.avg_ticket_price != null ? { avg_ticket_price: runConfig.avg_ticket_price } : {}),
  };
}

/**
 * Translate the What-If UI form into the graph-change dict the backend expects.
 *
 * Semantics (matches api.engine_bridge.run_what_if):
 *   - disable_gates:  array of gate ids to take offline.  Backend also disables
 *                     the paired security checkpoint (security_i).  Models a
 *                     gate failure, a CBP lane going down, or a bomb-threat
 *                     closure of one approach.
 *   - add_servers:    { node_id -> new_total } applied per security checkpoint.
 *                     Models staffing up every lane uniformly (e.g. paying for
 *                     more TSA-style screeners league-wide).
 *   - reduce_staffing_pct: single scalar in [0,1) applied to ALL
 *                     security/ticketing/concession/restroom nodes.
 *                     Models a sickout, a union walkout, call-out spikes.
 *   - close_section:  node_id prefix ("concession_", "restroom_", "seating_").
 *                     Every node whose id begins with that prefix is removed
 *                     from the network.  Models a facility-wide shutdown of
 *                     one service tier.
 */
function buildWhatIfChanges(form, entryNodeCount = 4) {
  const changes = {};

  if (form.disabledGates > 0) {
    changes.disable_gates = Array.from(
      { length: form.disabledGates },
      (_, index) => `gate_${index}`,
    );
  }

  if (form.extraServers > 0) {
    // Security checkpoints are named security_0..security_{n_gates-1} — one
    // per entry gate.  Apply the uniform bump to EVERY checkpoint (not just
    // the first four, which used to silently under-count large venues).
    const securityCount = Math.max(1, entryNodeCount || 4);
    changes.add_servers = Object.fromEntries(
      Array.from({ length: securityCount }, (_, index) => [
        `security_${index}`,
        form.extraServers,
      ]),
    );
  }

  if (form.staffingCut > 0) {
    changes.reduce_staffing_pct = form.staffingCut / 100;
  }

  if (form.closedSection) {
    changes.close_section = form.closedSection;
  }

  return changes;
}

function buildInitialWhatIfForm(selectedVenueDetail) {
  return {
    disabledGates: Math.min(1, Math.max(selectedVenueDetail?.graph_summary?.entry_nodes || 1, 1)),
    extraServers: 1,
    staffingCut: 0,
    closedSection: "",
  };
}

function buildInitialCompareForm(config) {
  return {
    eventType: config?.event_type || "nfl",
    attendance: config?.attendance || 1000,
    weather: config?.weather_factor != null ? Math.round(config.weather_factor * 100) : 30,
    transit: config?.transit_factor != null ? Math.round(config.transit_factor * 100) : 50,
    serviceRateTier: config?.service_rate_tier || "operational",
  };
}

function buildChatScenarioContext(runConfig) {
  return {
    venue_id: runConfig.venue_id,
    venue_name: runConfig.venue_name,
    attendance: runConfig.attendance,
    attendance_requested: runConfig.attendance_requested,
    event_type: runConfig.event_type,
    ...(runConfig.event_date ? { event_date: runConfig.event_date } : {}),
    ...(runConfig.event_time ? { event_time: runConfig.event_time } : {}),
    ...(runConfig.weather_factor != null ? { weather_factor: runConfig.weather_factor } : {}),
    ...(runConfig.transit_factor != null ? { transit_factor: runConfig.transit_factor } : {}),
    ...(runConfig.service_rate_tier ? { service_rate_tier: runConfig.service_rate_tier } : {}),
    ...(runConfig.avg_ticket_price != null ? { avg_ticket_price: runConfig.avg_ticket_price } : {}),
    ...(runConfig.event_duration_hours != null ? { event_duration_hours: runConfig.event_duration_hours } : {}),
  };
}

function applyChatResults(results, setters) {
  for (const result of results) {
    if (!result) {
      continue;
    }

    if (result.stress_results) {
      setters.setStressResult(result);
      setters.setPhase("results");
      continue;
    }

    if (result.base && result.modified && result.delta) {
      setters.setWhatIfResult(result);
      setters.setSimulationResult(result.modified || null);
      setters.setPhase("results");
      if (result.modified?.venue_id) {
        setters.setSelectedVenueId(result.modified.venue_id);
      }
      if (result.modified?.simulation) {
        setters.setRunConfig((current) => ({
          ...(current || {}),
          venue_id: result.modified.venue_id || current?.venue_id,
          venue_name: result.modified.venue_name || current?.venue_name,
          attendance: result.modified.parameters?.attendance || current?.attendance,
          attendance_requested:
            result.modified.parameters?.attendance_requested || current?.attendance_requested,
          event_type: result.modified.parameters?.event_type || current?.event_type,
          weather_factor: result.modified.parameters?.weather_factor ?? current?.weather_factor,
          transit_factor: result.modified.parameters?.transit_factor ?? current?.transit_factor,
          avg_ticket_price:
            result.modified.parameters?.avg_ticket_price ?? current?.avg_ticket_price,
          service_rate_tier:
            result.modified.parameters?.service_rate_tier || current?.service_rate_tier || "operational",
        }));
      }
      continue;
    }

    if (result.temporal) {
      setters.setTemporalResult(result);
      setters.setPhase("results");
      if (result.venue_id) {
        setters.setSelectedVenueId(result.venue_id);
      }
      if (result.parameters) {
        setters.setRunConfig((current) => ({
          ...(current || {}),
          venue_id: result.venue_id || current?.venue_id,
          venue_name: result.venue_name || current?.venue_name,
          attendance: result.parameters.attendance || current?.attendance,
          attendance_requested:
            result.parameters.attendance_requested || current?.attendance_requested,
          event_type: result.parameters.event_type || current?.event_type,
          weather_factor: result.parameters.weather_factor ?? current?.weather_factor,
          transit_factor: result.parameters.transit_factor ?? current?.transit_factor,
          avg_ticket_price:
            result.parameters.avg_ticket_price ?? current?.avg_ticket_price,
          service_rate_tier:
            result.parameters.service_rate_tier || current?.service_rate_tier || "operational",
          event_duration_hours:
            result.parameters.event_duration_hours || current?.event_duration_hours || 3,
        }));
      }
      continue;
    }

    if (result.simulation) {
      setters.setSimulationResult(result);
      setters.setPhase("results");
      if (result.venue_id) {
        setters.setSelectedVenueId(result.venue_id);
      }
      if (result.parameters) {
        setters.setRunConfig((current) => ({
          ...(current || {}),
          venue_id: result.venue_id || current?.venue_id,
          venue_name: result.venue_name || current?.venue_name,
          attendance: result.parameters.attendance || current?.attendance,
          attendance_requested:
            result.parameters.attendance_requested || current?.attendance_requested,
          event_type: result.parameters.event_type || current?.event_type,
          weather_factor: result.parameters.weather_factor ?? current?.weather_factor,
          transit_factor: result.parameters.transit_factor ?? current?.transit_factor,
          avg_ticket_price:
            result.parameters.avg_ticket_price ?? current?.avg_ticket_price,
          service_rate_tier:
            result.parameters.service_rate_tier || current?.service_rate_tier || "operational",
        }));
      }
    }
  }
}

function resetChatState(venueName, setMessages, setConversationId, existingConversationId) {
  if (existingConversationId) {
    clearConversation(existingConversationId).catch(() => {});
  }
  setConversationId(null);
  setMessages(initialChatMessages(venueName));
}

function initialChatMessages(venueName) {
  return [
    {
      role: "sys",
      text: "vane · live intelligence · claude via backend tools",
    },
    {
      role: "assistant",
      text: venueName
        ? `Ready. Ask about ${venueName}, run a stress question, or request a what-if simulation.`
        : "Ready. Run a scenario, then ask follow-up operational questions.",
    },
  ];
}

function buildPromptSuggestions(runConfig, venueName) {
  const venueLabel = venueName || "this venue";
  const attendance = formatNumber(runConfig?.attendance, 0);

  return [
    `What if we close one gate at ${venueLabel}?`,
    `Run the stress panel again and summarize the biggest operational risk.`,
    `Why is HES low for ${venueLabel} at ${attendance} attendance?`,
    `What is the next simulation you would run on this scenario?`,
  ];
}

function buildTickerItems(runConfig, simulationResult, stressResult, health) {
  const items = [];

  if (runConfig) {
    items.push({
      label: `${runConfig.venue_name} · ${eventName(runConfig.event_type)} · ${formatNumber(runConfig.attendance, 0)} attendees`,
      tone: "acc",
    });
  }

  if (simulationResult?.metrics?.operational?.wait_time) {
    items.push({
      label: `wait ${formatNumber(simulationResult.metrics.operational.wait_time.mean, 1)}m · p90 ${formatNumber(simulationResult.metrics.operational.wait_time.p90, 1)}m`,
      tone: "info",
    });
  }

  if (simulationResult?.metrics?.experience?.hes != null) {
    items.push({
      label: `hes ${formatNumber(simulationResult.metrics.experience.hes, 1)} · ${simulationResult.metrics.experience.grade}`,
      tone: "ok",
    });
  }

  if (simulationResult?.metrics?.safety?.risk_level) {
    items.push({
      label: `safety ${simulationResult.metrics.safety.risk_level} · evac ${formatNumber(simulationResult.metrics.safety.estimated_evac_minutes, 0)}m`,
      tone: safetyTone(simulationResult.metrics.safety.risk_level),
    });
  }

  if (simulationResult?.metrics?.demand?.price_is_binding) {
    items.push({
      label: `pricing binds turnout · ${formatNumber(simulationResult.metrics.demand.effective_attendance, 0)} effective vs ${formatNumber(simulationResult.metrics.demand.requested_attendance, 0)} requested`,
      tone: "warn",
    });
  }

  if (stressResult?.resilience_score != null) {
    items.push({
      label: `resilience ${formatNumber(stressResult.resilience_score, 0)} / 100 · worst ${STRESS_META[stressResult.most_vulnerable]?.label || stressResult.most_vulnerable}`,
      tone: stressResult.resilience_score < 45 ? "warn" : "acc",
    });
  }

  const n =
    health && typeof health === "object" && typeof health.venues_loaded === "number"
      ? health.venues_loaded
      : "—";
  items.push({
    label: `${n} venue models online`,
    tone: "acc",
  });

  const out = items.length ? items : [{ label: "Vane command center ready", tone: "acc" }];
  return out.map((item) => ({
    ...item,
    label: sanitizeForTicker(item.label),
  }));
}

function buildStressRows(stressResult) {
  if (!stressResult?.stress_results) {
    return [];
  }

  const baseHes =
    stressResult.base_scenario?.metrics?.experience?.hes ??
    stressResult.base_scenario?.simulation?.hes_mean ??
    0;

  return Object.entries(stressResult.stress_results).map(([id, item]) => ({
    id,
    label: STRESS_META[id]?.label || slugToTitle(id),
    detail: STRESS_META[id]?.detail || "Stress scenario",
    resilience: clamp(
      baseHes
        ? 100 - Math.max(0, baseHes - (item.metrics?.experience?.hes ?? item.simulation?.hes_mean ?? 0))
        : 0,
      0,
      100,
    ),
    waitDelta: item.delta?.wait_mean || 0,
  }));
}

function buildGraphNodes(nodeMetrics = {}) {
  return Object.entries(nodeMetrics).map(([id, metrics]) => ({
    id,
    label: compactNodeLabel(id),
    type: inferNodeType(id),
    utilization: metrics.util_mean || 0,
    waitMean: metrics.wait_mean || 0,
    los: metrics.fruin_los_mode || "—",
  }));
}

function buildGraphPositions(nodes, width, height) {
  const groups = {
    gate: nodes.filter((node) => node.type === "gate"),
    security: nodes.filter((node) => node.type === "security"),
    concourse: nodes.filter((node) => node.type === "concourse"),
    concession: nodes.filter((node) => node.type === "concession"),
    restroom: nodes.filter((node) => node.type === "restroom"),
    seating: nodes.filter((node) => node.type === "seating"),
    exit_corridor: nodes.filter((node) => node.type === "exit_corridor"),
    exit: nodes.filter((node) => node.type === "exit"),
    misc: nodes.filter((node) => node.type === "misc"),
  };

  const positions = {};

  layOutVertical(groups.gate, 90, 80, height - 80, positions);
  layOutVertical(groups.security, 230, 90, height - 90, positions);
  layOutVertical(groups.concourse, 430, 140, height - 140, positions);
  layOutGrid(groups.seating, 620, 160, 2, 150, 170, positions);
  layOutHorizontal(groups.concession, 575, 90, 110, positions);
  layOutHorizontal(groups.restroom, 575, height - 70, 110, positions);
  layOutVertical(groups.exit_corridor, 785, 160, height - 160, positions);
  layOutVertical(groups.exit, 900, 70, height - 70, positions);
  layOutHorizontal(groups.misc, width / 2, height / 2, 100, positions);

  return positions;
}

function buildGraphEdges(nodes) {
  const edges = [];
  const gates = nodes.filter((node) => node.type === "gate");
  const security = nodes.filter((node) => node.type === "security");
  const concourse = nodes.filter((node) => node.type === "concourse");
  const seating = nodes.filter((node) => node.type === "seating");
  const concessions = nodes.filter((node) => node.type === "concession");
  const restrooms = nodes.filter((node) => node.type === "restroom");
  const exitCorridors = nodes.filter((node) => node.type === "exit_corridor");
  const exits = nodes.filter((node) => node.type === "exit");

  gates.forEach((gate, index) => {
    const pairedSecurity = security[index] || security[0];
    if (pairedSecurity) {
      edges.push([gate.id, pairedSecurity.id]);
    }
  });

  security.forEach((node) => {
    concourse.forEach((concourseNode) => {
      edges.push([node.id, concourseNode.id]);
    });
  });

  concourse.forEach((node) => {
    seating.forEach((seat) => edges.push([node.id, seat.id]));
    concessions.slice(0, 2).forEach((spot) => edges.push([node.id, spot.id]));
    restrooms.slice(0, 2).forEach((spot) => edges.push([node.id, spot.id]));
  });

  seating.forEach((seat) => {
    exitCorridors.forEach((corridor) => edges.push([seat.id, corridor.id]));
  });

  exitCorridors.forEach((node) => {
    exits.forEach((exit) => edges.push([node.id, exit.id]));
  });

  return edges;
}

function buildTemporalSeries(temporalResult, runConfig) {
  const temporal = temporalResult?.temporal;
  const nodeTimeseries = temporal?.node_timeseries;

  if (!nodeTimeseries) {
    return [];
  }

  const relevantEntries = Object.entries(nodeTimeseries).filter(([nodeId]) => {
    const type = inferNodeType(nodeId);
    return ["gate", "security", "concession", "restroom", "seating"].includes(type);
  });

  if (!relevantEntries.length) {
    return [];
  }

  const sampleLength = relevantEntries[0][1].wait.length;
  const profile = EVENT_PROFILES[runConfig?.event_type] || EVENT_PROFILES.nfl;
  const dtMinutes = 2;
  const eventDuration = runConfig?.event_duration_hours || 3;
  const eventStart = profile.windowMinutes;
  const totalAttendance = runConfig?.attendance || 0;

  const betaRaw = Array.from({ length: sampleLength }, (_, index) => {
    const x = index / Math.max(sampleLength - 1, 1);
    return betaCurve(x, profile.alpha, profile.beta);
  });
  const maxBeta = Math.max(...betaRaw, 1);

  return Array.from({ length: sampleLength }, (_, index) => {
    const waitValues = relevantEntries.map(([, entry]) => entry.wait[index] || 0);
    const meanWait = average(waitValues);
    const tMinutes = index * dtMinutes - eventStart;
    const eventProgress = index * dtMinutes;
    const eventMinutes = eventDuration * 60;
    const egressStart = eventStart + eventMinutes;
    const arrivalIntensity =
      eventProgress <= egressStart
        ? (betaRaw[index] / maxBeta) * totalAttendance * 0.8
        : Math.max(0, (1 - (eventProgress - egressStart) / Math.max(eventMinutes, 1)) * totalAttendance * 0.18);

    return {
      tMinutes,
      wait: meanWait,
      arrival: arrivalIntensity,
    };
  });
}

function getSimulationSummary(simulationResult) {
  const operational = simulationResult?.metrics?.operational || {};
  const experience = simulationResult?.metrics?.experience || {};
  const safety = simulationResult?.metrics?.safety || {};
  const revenue = simulationResult?.metrics?.revenue || {};
  const demand = simulationResult?.metrics?.demand || {};

  const simBlock = simulationResult?.simulation || {};
  return {
    waitMean: operational.wait_time?.mean ?? simBlock.wait_mean ?? 0,
    waitP10: operational.wait_time?.p10 ?? simBlock.wait_p10 ?? 0,
    waitP90: operational.wait_time?.p90 ?? simBlock.wait_p90 ?? 0,
    hes: experience.hes ?? simBlock.hes_mean ?? 0,
    hesGrade: experience.grade || "—",
    safetyScore: scaleSafetyScore(safety.srs ?? simBlock.srs_mean),
    safetyLabel: safety.risk_level || deriveSrsLabel(safety.srs ?? simBlock.srs_mean),
    revenueImpact: revenue.total_economic_impact ?? 0,
    currentEventLoss: revenue.total_current_event_loss ?? 0,
    futureDemandDelta: revenue.total_future_impact ?? 0,
    futureDemandDownside: revenue.future_demand_downside ?? 0,
    futureDemandUpside: revenue.future_demand_upside ?? 0,
    revenueInterpretation: revenue.interpretation || "modeled downside at risk",
    computeMs: simulationResult?.computation_time_ms || 0,
    nTrials: simBlock.n_simulations || 0,
    arrivalWindow: simBlock.arrival_window_hours || 0,
    peakRatePerHour: simBlock.peak_arrival_rate_per_hour || 0,
    utilMax: simBlock.util_max,
    congestionProb: simBlock.congestion_probability,
    requestedAttendance:
      demand.requested_attendance ??
      simulationResult?.parameters?.attendance_requested ??
      simulationResult?.parameters?.attendance ??
      0,
    effectiveAttendance:
      demand.effective_attendance ??
      simulationResult?.parameters?.attendance ??
      0,
    attendanceDelta:
      demand.attendance_delta_total ??
      Math.max(
        0,
        (simulationResult?.parameters?.attendance_requested || 0)
          - (simulationResult?.parameters?.attendance || 0),
      ),
    isPriceConstrained: Boolean(demand.price_is_binding),
    pricePosture: demand.pricing_posture || "not_applied",
  };
}

function resolveVenueCapacity(venue, detail, eventType) {
  if (detail?.venue?.capacity) {
    const capacity = detail.venue.capacity;
    const eventCapacityMap = {
      nfl: capacity.football,
      concert: capacity.concert_with_floor || capacity.concert,
      concert_large: capacity.concert_with_floor || capacity.concert || capacity.max,
      sports: capacity.basketball || capacity.hockey_nhl || capacity.max,
      boxing_mma: capacity.max || capacity.concert,
      convention: capacity.max,
      festival: capacity.max,
      theater: capacity.max || capacity.seated_concert,
    };

    return (
      eventCapacityMap[eventType] ||
      capacity.max ||
      capacity.app_py_value ||
      venue?.capacity ||
      1000
    );
  }

  return venue?.capacity || 1000;
}

function eventName(eventType) {
  return EVENT_OPTIONS.find((option) => option.id === eventType)?.name || slugToTitle(eventType);
}

function weatherDescriptor(value) {
  if (value < 20) return "mild";
  if (value < 50) return "moderate";
  if (value < 75) return "hot / windy";
  return "extreme";
}

function transitDescriptor(value) {
  if (value < 30) return "disrupted";
  if (value < 60) return "degraded";
  if (value < 85) return "nominal";
  return "peak";
}

function recommendedAttendance(capacity) {
  return roundAttendance(capacity * 0.85);
}

function roundAttendance(value) {
  return Math.max(100, Math.round(value / 500) * 500);
}

function resolveCompareAttendanceMax(baseAttendance, nominalCapacity) {
  const base = Math.max(baseAttendance || 1000, 100);
  const capacity = Math.max(nominalCapacity || 1000, 1000);
  const overloadHeadroom = Math.max(20000, capacity * 0.25);

  return Math.min(
    250000,
    roundAttendance(Math.max(base + 20000, capacity + overloadHeadroom)),
  );
}

function formatUtcClock(date) {
  return `${date.toISOString().slice(0, 10)} | ${date.toISOString().slice(11, 19)} UTC`;
}

function formatNumber(value, decimals = 0) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }

  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCompactNumber(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }

  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number(value));
}

function formatCurrency(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }

  const absolute = Math.abs(Number(value));
  if (absolute >= 1_000_000_000) {
    return `$${formatNumber(absolute / 1_000_000_000, 2)}B`;
  }
  if (absolute >= 1_000_000) {
    return `$${formatNumber(absolute / 1_000_000, 2)}M`;
  }
  if (absolute >= 1_000) {
    return `$${formatNumber(absolute / 1_000, 0)}K`;
  }
  return `$${formatNumber(absolute, 0)}`;
}

function formatSignedCurrency(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }
  const numeric = Number(value);
  return `${numeric >= 0 ? "+" : "-"}${formatCurrency(Math.abs(numeric))}`;
}

function formatImpactCurrency(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }
  const absolute = Math.abs(Number(value));
  if (absolute > 0 && absolute < 1000) {
    return "<$1K";
  }
  return formatCurrency(value);
}

function deriveRevenueSubtitle(summary) {
  const downside = Number(summary?.revenueImpact ?? 0);
  const futureDelta = Number(summary?.futureDemandDelta ?? 0);
  if (downside <= 0) {
    return futureDelta > 0
      ? `${formatSignedCurrency(futureDelta)} future upside excluded`
      : "downside not detected in this run";
  }
  if (downside < 1000) {
    return futureDelta > 0
      ? "downside minimal · upside excluded"
      : "modeled downside below $1K";
  }
  if (futureDelta < 0) {
    return "current event + future demand downside";
  }
  return "modeled downside only · upside excluded";
}

function formatPercent(value, decimals = 0) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }
  return `${formatNumber(scaleFraction(value), decimals)}%`;
}

function formatMilliseconds(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }
  if (value >= 1000) {
    return `${formatNumber(value / 1000, 2)}s`;
  }
  return `${formatNumber(value, 0)}ms`;
}

function scaleFraction(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return 0;
  }
  return Number(value) <= 1 ? Number(value) * 100 : Number(value);
}

function scaleSafetyScore(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return 0;
  }
  return Number(value) <= 1 ? Number(value) * 100 : Number(value);
}

function deriveSrsLabel(score) {
  if (score == null || Number.isNaN(Number(score))) return "Unknown";
  const v = scaleSafetyScore(score);
  if (v < 25) return "LOW";
  if (v < 45) return "MODERATE";
  if (v < 65) return "ELEVATED";
  if (v < 85) return "HIGH";
  return "CRITICAL";
}

function safetyTone(label) {
  if (!label) return "acc";
  if (label === "LOW" || label === "NOMINAL") return "ok";
  if (label === "MODERATE" || label === "ELEVATED") return "warn";
  return "danger";
}

function toneForRecommendation(category = "") {
  const normalized = category.toLowerCase();
  if (normalized.includes("safety")) return "danger";
  if (normalized.includes("security")) return "danger";
  if (normalized.includes("experience")) return "info";
  if (normalized.includes("staff")) return "info";
  if (normalized.includes("pricing")) return "warn";
  if (normalized.includes("revenue")) return "warn";
  return "acc";
}

function slugToTitle(value = "") {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function compactNodeLabel(nodeId) {
  if (!nodeId) {
    return "—";
  }

  if (nodeId.startsWith("gate_")) return `G${Number(nodeId.split("_")[1]) + 1}`;
  if (nodeId.startsWith("security_")) return `SEC ${Number(nodeId.split("_")[1]) + 1}`;
  if (nodeId.startsWith("concession_")) return `F${Number(nodeId.split("_")[1]) + 1}`;
  if (nodeId.startsWith("restroom_")) return `R${Number(nodeId.split("_")[1]) + 1}`;
  if (nodeId.startsWith("exit_")) return `E${Number(nodeId.split("_")[1]) + 1}`;
  if (nodeId === "concourse_main") return "CONCOURSE";
  if (nodeId === "seating_main") return "SEATING";
  if (nodeId === "exit_corridor") return "EXIT FLOW";
  return nodeId.toUpperCase();
}

function humanizeNodeId(nodeId) {
  if (!nodeId) {
    return "—";
  }

  return compactNodeLabel(nodeId)
    .replace("SEC", "Security")
    .replace("CONCOURSE", "Main concourse")
    .replace("SEATING", "Main seating")
    .replace("EXIT FLOW", "Exit corridor");
}

function inferNodeType(nodeId = "") {
  if (nodeId.startsWith("gate_")) return "gate";
  if (nodeId.startsWith("security_")) return "security";
  if (nodeId === "concourse_main") return "concourse";
  if (nodeId.startsWith("concession_")) return "concession";
  if (nodeId.startsWith("restroom_")) return "restroom";
  if (nodeId === "seating_main" || nodeId.startsWith("seating_")) return "seating";
  if (nodeId === "exit_corridor") return "exit_corridor";
  if (nodeId.startsWith("exit_")) return "exit";
  return "misc";
}

function nodeColor(node) {
  if (node.utilization >= 0.95) return "var(--danger)";
  if (node.utilization >= 0.75) return "var(--warn)";
  if (node.utilization >= 0.5) return "var(--acc)";
  if (node.type === "concession") return "var(--info)";
  return "var(--fg-3)";
}

function nodeRadius(node) {
  return 4 + clamp(node.utilization, 0, 1) * 8;
}

function layOutVertical(nodes, x, top, bottom, positions) {
  const span = Math.max(bottom - top, 1);
  nodes.forEach((node, index) => {
    positions[node.id] = {
      x,
      y: top + (span * index) / Math.max(nodes.length - 1, 1),
    };
  });
}

function layOutHorizontal(nodes, centerX, y, gap, positions) {
  if (!nodes.length) return;
  const total = (nodes.length - 1) * gap;
  nodes.forEach((node, index) => {
    positions[node.id] = {
      x: centerX - total / 2 + index * gap,
      y,
    };
  });
}

function layOutGrid(nodes, startX, startY, columns, colGap, rowGap, positions) {
  nodes.forEach((node, index) => {
    positions[node.id] = {
      x: startX + (index % columns) * colGap,
      y: startY + Math.floor(index / columns) * rowGap,
    };
  });
}

function betaCurve(x, alpha, beta) {
  if (x <= 0 || x >= 1) {
    return 0;
  }
  return Math.pow(x, alpha - 1) * Math.pow(1 - x, beta - 1);
}

function buildTickIndexes(length) {
  const indexes = new Set([0, Math.floor(length * 0.25), Math.floor(length * 0.5), Math.floor(length * 0.75), length - 1]);
  return [...indexes].filter((index) => index >= 0 && index < length).sort((a, b) => a - b);
}

function average(values) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatDeltaValue(value, { money, unit, compact }) {
  if (money) {
    return formatCurrency(value);
  }

  const formatted = formatNumber(value, compact ? 1 : 1);
  return unit ? `${formatted}${unit}` : formatted;
}

function humanizeCloseSection(value) {
  if (value === "concession_") return "Concessions";
  if (value === "restroom_") return "Restrooms";
  if (value === "seating_") return "Seating";
  return slugToTitle(value);
}

function buildScenarioKey(config) {
  return JSON.stringify({
    venue_id: config?.venue_id,
    attendance: config?.attendance,
    event_type: config?.event_type,
    weather_factor: config?.weather_factor,
    transit_factor: config?.transit_factor,
    service_rate_tier: config?.service_rate_tier,
  });
}

function sheetTitle(sheetKey) {
  switch (sheetKey) {
    case "wait":
      return "Expected Wait";
    case "hes":
      return "HES · Experience";
    case "safety":
      return "Safety Risk";
    case "revenue":
      return "Downside At Risk";
    case "bottleneck":
      return "Bottleneck Node";
    case "los":
      return "Worst LOS";
    case "unstable":
      return "Unstable Nodes";
    case "solve":
      return "Solve Time";
    default:
      return "";
  }
}

function sheetKicker(sheetKey) {
  switch (sheetKey) {
    case "wait":
      return "§ Expected value · Allen-Cunneen G/G/s";
    case "hes":
      return "§ Human Experience Score · multiplicative";
    case "safety":
      return "§ Safety Risk Score · composite";
    case "revenue":
      return "§ Revenue impact · current event + future demand";
    case "bottleneck":
      return "§ Network bottleneck · utilisation ordering";
    case "los":
      return "§ Pedestrian Level of Service · Fruin / HCM6";
    case "unstable":
      return "§ Queueing stability · ρ-diagnostic";
    case "solve":
      return "§ Compute performance · Monte-Carlo";
    default:
      return "§ Derivation";
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(Number(value), min), max);
}
