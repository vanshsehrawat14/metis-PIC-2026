# Benchmarks and Validation

Measured from the code in this repository (last reviewed 2026-04-23). Runtimes are
local measurements on one machine, not cloud SLAs. The back-test is theory-grounded and
public-source-based, not instrumented validation from venue scanner or sensor logs.

## Runtime

### Snapshot Monte Carlo (1,000 trials per scenario)

| Venue | Event | Attendance | Runs (ms) | Mean (ms) |
|---|---|---|---|---|
| Thomas & Mack Center | concert | 17,000 | 1320.7 / 1351.7 / 1354.7 | 1342.4 |
| T-Mobile Arena | boxing/MMA | 18,000 | 1534.6 / 1560.7 / 1570.7 | 1555.3 |
| Allegiant Stadium | NFL | 61,000 | 2812.4 / 2792.2 / 2700.3 | 2768.3 |

### Temporal API (end-to-end /simulate/temporal response time)

| Venue | Event | Attendance | fast (ms) | deep (ms) |
|---|---|---|---|---|
| Thomas & Mack Center | concert | 17,000 | 446.4 | 4575.6 |
| Allegiant Stadium | NFL | 61,000 | 991.1 | 10982.9 |

Reading: "in seconds" holds for snapshot runs and fast temporal runs. Sub-two-second is
case-dependent (some arena-scale cases), not a universal claim. Deep temporal mode is
several seconds to low tens of seconds on larger venues.

## Historical back-test

Predicted wait bands (P10 to P90) against documented public reporting.

| Case | Predicted (min) | Documented (min) | Assessment |
|---|---|---|---|
| Super Bowl LVIII, Allegiant Stadium | 23 to 67 | 30 to 45 | Ingress band overlaps; modeled egress runs longer than documented. Strongest current comparison. |
| UFC 306, Sphere Las Vegas | 13 to 64 | 15 to 25 | Overlap, but the band is wide and the mean is high. Reasonable directional match, weaker precision than Allegiant. |
| CES 2024 peak day, LV Convention Center | 0 to 0 | 10 to 20 | Poor match. Convention registration and hall-to-hall flow are not well captured by the current aggregated topology. |

## Interpretation

- The model fits stadium and arena ingress better than convention-style registration
  flow.
- The back-test supports the statement "theory-grounded and back-tested against public
  event reporting." It does not support "fully validated" or "predicts every event
  accurately."
- The 1,000-trial Monte Carlo surfaces uncertainty (mean, P10, P90) on core operational
  outputs such as wait and congestion. Not every metric carries an uncertainty band.

## Limitations

- No instrument-measured queue data from any Las Vegas venue.
- Waits can be over-predicted where public topology understates real security or
  gate throughput.
- Outputs are decision support, not regulatory certification or emergency-egress
  approval.
