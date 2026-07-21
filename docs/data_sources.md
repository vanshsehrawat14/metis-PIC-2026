# Data Sources

Master list of all external data sources used in the Vane simulation platform.

Last updated: 2026-04-23

---

## Key

| Column | Meaning |
|--------|---------|
| **Type** | Category: `weather`, `traffic`, `venue`, `service_rate`, `ridership`, `climate_normal` |
| **Coverage** | Temporal and/or spatial scope |
| **Update Frequency** | How often the source is refreshed |
| **License / Access** | Terms of use |
| **Used In** | Which Vane module consumes this source |

---

## Sources

| Source Name | Type | Provider | URL | Coverage | Update Frequency | License / Access | Notes | Used In |
|------------|------|----------|-----|----------|-----------------|-----------------|-------|---------|
| Open-Meteo ERA5 Historical Weather API | weather | Open-Meteo (ECMWF ERA5 reanalysis) | https://open-meteo.com/en/docs/historical-weather-api | Las Vegas NV (36.17, -115.14); 2022–2024 hourly | Historical archive updated with ~5-day lag | CC BY 4.0 | ERA5 reanalysis blends observations + NWP model. 0.25° spatial resolution (~25 km). Precipitation uncertain in arid regions; wind gusts are modeled. | `data/sources/weather.py`, `data/calibration/calibration_pipeline.py` |
| Open-Meteo Forecast API | weather | Open-Meteo | https://open-meteo.com/en/docs | Las Vegas NV; up to 16 days ahead | Model-dependent, refreshed multiple times per day | CC BY 4.0 | Used for future event forecasting. Open-Meteo’s default forecast blends underlying models with update cadence that varies by provider. | `data/sources/weather.py` (forecast_fetch) |
| NOAA Las Vegas Climate Normals 1991–2020 | climate_normal | NOAA National Centers for Environmental Information | https://www.ncei.noaa.gov/access/us-climate-normals/ | Las Vegas, NV (KLAS) | 10-year update cycle | Public domain (U.S. Government) | Calibration-only fallback when the local ERA5 cache is absent. This is not the runtime weather path for event simulations. | `data/calibration/calibration_pipeline.py` (fallback) |
| Nevada DOT Traffic Records: HPMS | traffic | Nevada Department of Transportation, Traffic Records Unit | https://ndot.nv.gov/Programs/Traffic/TrafficData/ | 6 Las Vegas key corridors; 2023 AADT | Annual | Public domain (state government) | AADT counts for I-15 at Russell Rd, Las Vegas Blvd at Tropicana/Spring Mountain/Sahara, Koval/Sands, Frank Sinatra Dr. Some segments estimated from Traffic Flow Maps (confidence: low). | `data/sources/traffic.py`, `data/sources/ndot_counts.json` |
| Clark County Public Works Traffic Data | traffic | Clark County Department of Public Works | https://www.clarkcountynv.gov/government/departments/public_works/traffic_engineering | Las Vegas arterial count stations | Annual | Public records (Clark County open data) | Supplements NDOT data for non-freeway corridors. Used for Las Vegas Blvd segment counts. | `data/sources/ndot_counts.json` |
| Las Vegas Stadium Authority: EIS / EIR Documents | venue / traffic | Las Vegas Stadium Authority (Nevada Legislature) | https://lvstadiumauthority.com/ | Allegiant Stadium; 2016–2020 | Static (project approval documents) | Public records | AB 1 (30th Special Session 2016) approval documentation. Capacity: 65,000 NFL / 72,000 concert. Traffic: ~14,000–18,000 vehicle trips per game. | `data/venues/vegas_venues.json` |
| RTC Southern Nevada Annual Reports | ridership | Regional Transportation Commission of Southern Nevada | https://www.rtcsnv.com/ | Las Vegas MSA transit system; FY2019–FY2023 | Annual | Public records | Per-route ridership not always published separately. Route-level estimates derived from system totals and frequency ratios. | `data/sources/rtc_transit.json`, `data/sources/traffic.py` |
| Las Vegas Monorail / LVCVA Operational Reports | ridership | Las Vegas Convention & Visitors Authority | https://www.lvmonorail.com/ | Las Vegas Strip monorail; 2019–2023 | Irregular (post-bankruptcy reporting) | Public records | Went bankrupt Jan 2020; LVCVA acquired Jul 2020. Pre-COVID 2019: ~15,800/day. Post-COVID 2023: ~7,500/day (estimated). | `data/sources/rtc_transit.json`, `data/sources/traffic.py` |
| DHS Best Practices for Venue Security Screening | service_rate | U.S. Department of Homeland Security | https://www.dhs.gov/publication/best-practices-venue-security | U.S. large venues; 2018 | Static (policy document) | U.S. Government public domain | Magnetometer only: 250–350 persons/lane/hr. Magnetometer + bag check: 180–250. Enhanced (pat-down): 120–160. Table 2-1 and 2-2. | `data/sources/service_rates.py`, `data/calibration/calibration_pipeline.py` |
| Highway Capacity Manual 6th Edition (HCM6): Chapter 24 | service_rate | Transportation Research Board (TRB) | https://www.mytrb.org/OnlinePublications/PDF/HCM6E_Chapter24.pdf | Pedestrian flow; U.S. design standard | 6-year update cycle | Proprietary (TRB); widely cited | Free flow: 1.2 m/s. LOS C: 0.72 p/m², 1.0 m/s. LOS E: 2.17 p/m², 0.5 m/s. Stairway: ×0.60. Counter-flow: ×0.70. | `data/sources/service_rates.py` |
| Fruin, J.J.: Pedestrian Planning and Design (1987) + Crowd Safety (1993) | service_rate | J.J. Fruin / Metropolitan Association of Urban Designers | https://www.crowddynamics.com/Main/Frain%20article.pdf | Foundational crowd management benchmarks | Static (foundational literature) | Academic publication | Restroom: ~2.5 min/stall/patron. Arrival patterns: 40–60% in peak hour. Throughput degradation with density. | `data/sources/service_rates.py`, `data/calibration/calibration_pipeline.py` |
| IAAM Venue Operations Manual (2007) | service_rate | International Association of Assembly Managers (now IAVM) | https://www.iavm.org/ | U.S. arena and stadium operations benchmarks | Static (industry manual) | Industry publication (IAVM membership) | Ticketing: 15–20 persons/min/turnstile (barcode). Concession: 0.8–1.2 transactions/min/register (full menu). | `data/sources/service_rates.py` |
| Whitt, W. (1993): Approximations for the GI/G/m Queue | service_rate | Operations Research journal | DOI: 10.1287/opre.41.3.442 | Queueing theory | Static (peer-reviewed literature) | Academic journal (INFORMS) | c_a² ≈ 1.2–1.5 for event ingress (hyper-Poisson). Used for arrival process characterization. | `data/calibration/calibration_pipeline.py` |
| Vane human-adjustment heuristic | service_rate | Internal calibration note | `data/calibration/calibration_pipeline.py` | Human behavior adjustment | Static | Internal heuristic | Low-confidence planning scalar applied to raw Kingman waits to reflect adaptive staffing and patron self-sorting. Explicitly not derived from Las Vegas venue logs or a verified crowd meta-analysis. | `data/calibration/calibration_pipeline.py` |
| Venue Operator Official Specifications | venue | Various (MGM Resorts, AEG, Caesars, UNLV, Boyd Gaming, Genting, Wynn, Sphere Entertainment, LVCVA, Virgin Hotels, Las Vegas Stadium Authority, Speedway Motorsports Inc) | See individual entries in data/venues/vegas_venues.json | 17 Las Vegas venue profiles | Static (per-venue; updated when venues publish new specs) | Public records / press releases | Capacities marked `high` or `medium` confidence sourced from official documentation, venue operator materials, or well-reported public figures. Infrastructure (gates, security lanes) is often `medium` or `low` confidence because building plans are not public for most venues. | `data/venues/vegas_venues.json`, `data/calibration/calibration_pipeline.py` |

---

## Data Quality Summary

| Dimension | Status |
|-----------|--------|
| Weather (ERA5) | **High confidence**: reanalysis product, well-validated for Las Vegas flat terrain |
| Traffic (NDOT AADT) | **Medium confidence**: official counts for main corridors; 2 of 6 corridors estimated |
| Venue capacities | **High confidence** for 10/17 profiles; **medium confidence** for 7/17. No venue capacity in the current file is tagged `low`. |
| Gate/infrastructure counts | **Mostly low-medium confidence**. Gate counts are `medium` for 5 venues, `low` for 10, `n/a` for The Venetian Expo, and one legacy duplicate profile (Michelob Ultra Arena) lacks structured infrastructure fields. |
| Service rates (DHS/HCM6) | **High confidence**: peer-reviewed and regulatory sources |
| Queue wait times | **No direct measurement**: wait outputs are theory-derived from the queueing network and only lightly back-checked against public event reporting |
| Transit ridership | **Medium confidence**: system totals available; per-route estimates for some routes |

---

## What We Do Not Have

- Direct measurement of queue wait times at any Las Vegas venue
- Event-day vehicle counts (only baseline AADT available from NDOT)
- Actual gate counts verified from Clark County building plans for most venues
- Real-time traffic sensor data (would require NDOT API access or TomTom/HERE license)
- Ticketing scan throughput data from venue operators
- Post-event crowd dispersal time measurements

These gaps set the boundary on model confidence. See
[`BENCHMARKS_AND_VALIDATION.md`](BENCHMARKS_AND_VALIDATION.md) for the validation readout
and [`MATH.md`](MATH.md) for the model.
