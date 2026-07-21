# Vane — Mathematical Model

This is the authoritative reference for the math Vane runs and where each piece lives
in code. Formulas here are verified against the implementation. Where the code applies
a heuristic or a calibrated constant rather than a first-principles result, this
document says so.

Scope: this document covers the queueing-network engine behind the web app
(`simulation/network.py`, `temporal.py`, `metrics.py`, `demand.py`). The Streamlit demo
(`app.py`) uses a simpler single-node Kingman Monte Carlo model in
`simulation/engine.py` and is not covered here.

## 1. What conditions a run

Every result depends on five inputs: the venue, the attendance, the event type, the
date and time, and any overrides (weather, transit, service-rate tier, ticket price).
Venue topology comes from `data/venues/vegas_venues.json`; weather, holiday, event,
and traffic context are resolved in `api/engine_bridge.py`. If an average ticket price
is supplied, Vane first resolves a price-feasible turnout ceiling (Section 8) before
running the queueing and revenue math.

The pipeline is: build the venue-specific queueing network, solve the traffic
equations for node arrival rates, compute per-node wait / queue / utilization /
bottlenecks, repeat under Monte Carlo noise for distributions, run a temporal pass for
timing, then convert the physical outputs into Fruin LOS, SRS, HES, revenue, and
recommendations.

## 2. Snapshot queueing network

`simulation/network.py`. Each gate, security bank, concession bank, restroom bank,
corridor, and exit is a service or flow node. The question the snapshot answers: at
peak-hour demand, where does the line form and how bad does it get?

### Traffic equations

Node arrival rates solve the open-network (Jackson-style) balance:

```
lambda = gamma + R^T lambda   =>   (I - R^T) lambda = gamma
```

`gamma` is the external arrival vector, `R` the routing matrix, `lambda` the resulting
per-node arrival rates. The solver pre-computes an LU factorization of `(I - R^T)` and
reuses it across Monte Carlo trials; it also checks `det(I - R^T)` and rejects a
singular routing graph rather than returning garbage.

### Per-node queueing

For a node with `s` servers each at rate `mu` and offered load `a = lambda / mu`,
utilization is `rho = a / s = lambda / (s * mu)`. The M/M/s probability of waiting is
Erlang-C:

```
C(s, a) = (a^s / s!) / (1 - rho)
          / [ sum_{k=0}^{s-1} a^k / k!  +  (a^s / s!) / (1 - rho) ]
```

Erlang-C is evaluated in log space (log-sum-exp over `log(a^k / k!)`) so it stays
stable for the large server counts real venues have. The base M/M/s wait is:

```
Wq = C(s, a) / (s * mu * (1 - rho))
```

Service and arrivals are rarely Poisson, so the wait is corrected toward G/G/s with
the Allen-Cunneen factor:

```
Wq_corrected = Wq * (c_a^2 + c_s^2) / 2
```

and queue length follows from Little's law, `Lq = lambda * Wq_corrected`.

### Variance propagation (Whitt QNA)

Queues in series are not independent: bursty upstream arrivals make the next stage
burstier. Instead of assuming Poisson at every node, the engine runs a Whitt QNA
fixed-point pass over the routing graph. The departure squared coefficient of
variation at node `i` is

```
c_d^2(i) = 1 + (1 - rho_i^2)(c_a^2(i) - 1) + (rho_i^2 / sqrt(s_i))(c_s^2(i) - 1)
```

and arrivals at node `j` recombine the upstream departure streams (QNA superposition,
Whitt 1983 eq. 4.22):

```
c_a^2(j) = sum_i p_ij [ q_ij * c_d^2(i) + (1 - q_ij) ]
```

External arrivals seed `c_a^2 = 1` (Poisson). This is why Vane is more than a set of
independent single-queue calculators.

### Throughput and bottlenecks

The same people pass through every ingress stage, so system throughput is bounded by
the slowest stage, not the sum of stage capacities. Stable-node throughput is
`min(lambda_i, s_i * mu_i)`; venue throughput is the minimum effective stage
throughput along the ingress chain. Bottleneck frequency is the share of Monte Carlo
trials in which a node is the tightest constraint, which is what makes "add lanes here,
not there" defensible.

## 3. Fruin level of service

`simulation/metrics.py` (`FruinLOS`). Corridor density is a queue-density proxy,
`density = Lq / area`, not a full spatial occupancy model. Density maps to HCM6 / Fruin
grades:

| Grade | Density (persons/m^2) |
|-------|-----------------------|
| A | < 0.31 |
| B | 0.31 to 0.43 |
| C | 0.43 to 0.72 |
| D | 0.72 to 1.08 |
| E | 1.08 to 2.17 |
| F | >= 2.17 |

Walking speed degrades with density (free-flow speed 1.2 m/s):

```
v(d) = 1.2 * max(0.1, 1 - 0.35 * d)   for d < 2.17
```

## 4. Monte Carlo layer

`simulation/network.py`. The snapshot default is 1,000 trials per scenario (what-if and
stress endpoints use fewer for interactivity). Each trial perturbs external arrivals,
per-node service rates, and weather / transit effects (weather-driven degradation is
strongest on security and concession nodes). Node metrics are aggregated into means and
P10 / P90 bands; uncertainty is reported on the core operational outputs (wait,
congestion), not on every metric.

## 5. Temporal lifecycle

`simulation/temporal.py`. The snapshot asks "how bad is the peak hour?"; the temporal
model asks "when does the pain happen, how long does it last, and what does egress look
like?"

- **Arrivals**: a scaled Beta profile per event type, `lambda(t) = N * Beta(x; alpha,
  beta) / T`, where `x` is the fraction of the arrival window elapsed. Each event type
  has its own `(alpha, beta, window_hours, early_leave_frac)` (for example NFL uses
  `alpha=2.5, beta=1.8`; concerts peak later with `alpha=3.5, beta=1.5`).
- **Early departures**: a uniform trickle over the final minutes, sized by the event's
  `early_leave_frac`.
- **Main egress**: exponential decay, `lambda_exit(t) = N_remaining * kappa *
  exp(-kappa * t)`, with an event-type egress rate `kappa`.
- **Background circulation**: in-event demand for concessions and restrooms, a fraction
  of the peak arrival rate.
- **Waiting burden**: `person_hours_waiting = integral Lq(t) dt / 60`.

Modes: `fast` is a deterministic lifecycle pass; `deep` adds Monte Carlo sweeps at the
arrival-phase critical checkpoints, where the snapshot approximation is strongest.

## 6. Safety Risk Score (SRS)

`simulation/metrics.py` (`SafetyRiskScore`). A planning score, not a regulatory
standard. It reports the dominant safety constraint as the max of three components.

- **Crush-density risk** (sigmoid on peak density, ~50% risk at 1.5 persons/m^2, deep
  in LOS E):

  ```
  SRS_crush = 1 / (1 + exp(-(d_max - 1.5) * 4))
  ```

- **Exit-flow capacity risk** against a 30-minute clearance target
  (`required_throughput = attendance * 60 / 30 = attendance * 2 per hour`):

  ```
  SRS_flow = max(0, 1 - exit_throughput / required_throughput)
  ```

- **Evacuation-time risk**, ramping from a 30-minute planning target to 90 minutes:

  ```
  evac_minutes = attendance / (exit_throughput / 60)
  SRS_evac     = clamp((evac_minutes - 30) / 60, 0, 1)
  ```

```
SRS = max(SRS_crush, SRS_flow, SRS_evac)
```

If the temporal peak is worse than the structural snapshot, the reported safety layer
takes the worse temporal peak. The 8-minute NFPA 101 figure is an egress-system sizing
reference, not an expected real-world evacuation time; the code uses 30 minutes as the
risk-scoring planning target and documents this distinction inline.

## 7. Human Experience Score (HES)

`simulation/metrics.py` (`EnhancedHES`). HES captures compounded discomfort: one bad
factor hurts, several compound. It is a weighted multiplicative composite on 0 to 100:

```
HES = 100 * product_i ( w_i * f_i + (1 - w_i) )
```

Default weights: wait 0.35, density 0.25, temperature 0.20, service 0.10, access 0.10.
Factor values:

- **Wait**: `f_wait = exp(-0.05 * max(0, mean_wait_minutes - 5))`
- **Density**: mapped from the worst Fruin grade
  (A 1.0, B 0.95, C 0.80, D 0.55, E 0.25, F 0.05)
- **Temperature**: comfort band 60F to 80F, penalized outside it
- **Service**: `f_service = max(0.2, 1 - 0.06 * max(0, concession_wait - 3))`
- **Access**: average of entry and exit convenience terms

## 8. Demand and revenue

`simulation/demand.py` and `simulation/metrics.py` (`RevenueImpact`). Revenue is modeled
as downside-at-risk for prioritization, not audited event P&L, and is the least
empirical layer without client POS/CRM data. Priors are labeled calibrated heuristics
in the code.

When a ticket price `P` is supplied, Vane first resolves a price-feasible fill fraction
against an event-class reference price and floor, then caps attendance:

```
fill_price = clamp(fill_ref * (P / P_ref)^(-epsilon), fill_floor, 1.0)
N_eff      = min(N_requested, capacity, capacity * fill_price)
```

All downstream revenue uses `N_eff`, so it is never computed off an impossible
sell-through. A spend-tier multiplier scales per-capita spend with price,
`tau = clamp((P / 95)^0.42, 0.65, 1.45)`. Concession and merchandise revenue apply
`N_eff`, purchase probabilities, per-capita spend, and `tau`, then a friction penalty:
concession scales down with concession wait, merchandise with corridor density.
Future-ticket demand is modeled as `repeat_prob = min(1, base_prob * (HES / 70)^1.5)`,
so a materially worse experience depresses repeat demand.

## 9. Service rates

`data/sources/service_rates.py`. Two tiers, each with explicit provenance:

- **Literature**: DHS, HCM6, and Fruin published values (conservative, citable).
- **Operational**: planning defaults informed by public event reporting and literature
  upper bounds.

The tier is a request parameter and is echoed back in the response provenance, so every
number in the UI carries its lineage. See [`data_sources.md`](data_sources.md).
