"""
data/sources/service_rates.py — Service rate parameters for venue queueing nodes.

All parameters sourced from published operations research and crowd management
literature. Each parameter stored with source citation, confidence level, and
notes on applicability.

Sources:
  DHS: U.S. Department of Homeland Security, "Best Practices for Venue Security
       Screening", 2018. https://www.dhs.gov/publication/best-practices-venue-security
  Fruin: Fruin, J.J. (1993). "The causes and prevention of crowd disasters."
         Crowd Safety and Risk Analysis, Engineering for Crowd Safety,
         Elsevier, pp. 99-108.
  HCM: Transportation Research Board, Highway Capacity Manual 6th Edition (HCM6),
       2016. Chapter 24: Pedestrians and Bicycles.
  IAAM: International Association of Assembly Managers, "Venue Operations Manual",
        2nd ed. (2007). Throughput benchmarks for ticketing and concessions.
  Mott MacDonald: Crowd Dynamics / Mott MacDonald technical reports on pedestrian
                  flow simulation methodology, publicly cited in venue design guides.
"""

from __future__ import annotations

from typing import Optional


# ── Parameter schema ──────────────────────────────────────────────────────────
# Each parameter dict has:
#   min        — lower bound of published range
#   max        — upper bound of published range
#   default    — point estimate for simulation (typically midpoint or conservative value)
#   unit       — unit of measurement
#   c_s_squared — coefficient of variation squared of service time (for Kingman G/G/1)
#   source     — citation
#   notes      — applicability conditions and caveats

_DB: dict[str, dict] = {}


# ── Security Screening ─────────────────────────────────────────────────────────

_DB["security_magnetometer_only"] = {
    "min"         : 250,
    "max"         : 350,
    "default"     : 300,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.5,
    "c_s_squared_range": (0.4, 0.6),
    "source"      : (
        "DHS (2018), 'Best Practices for Venue Security Screening', Table 2-1. "
        "Also consistent with conservative venue-screening planning guidance in "
        "Fruin-era crowd management literature."
    ),
    "confidence"  : "high",
    "notes"       : (
        "Walk-through magnetometer only, no bag check. Range reflects variation in "
        "patron compliance and pre-event rush behavior. c_s² ≈ 0.5 indicates "
        "approximately normal service time distribution (mean ~12 sec/person). "
        "Lower end (~250) for arenas with strict no-bag policies driving patron "
        "behavior toward compliance; upper end (~350) for experienced event venues "
        "with trained staff and efficient layout."
    ),
}

_DB["security_magnetometer_bag_check"] = {
    "min"         : 180,
    "max"         : 250,
    "default"     : 215,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.9,
    "c_s_squared_range": (0.8, 1.2),
    "source"      : (
        "DHS (2018), Table 2-1; supplemented by event operations research cited in "
        "Gwynne & Rosenbaum (2016), SFPE Handbook of Fire Protection Engineering, "
        "Chapter 64 (Egress Modeling)."
    ),
    "confidence"  : "high",
    "notes"       : (
        "Combined magnetometer + bag check (X-ray or manual). Higher c_s² reflects "
        "variance introduced by bags requiring secondary inspection. This is the "
        "most common configuration at large arenas and stadiums post-2001. "
        "Bottleneck typically the bag screening lane, not the magnetometer."
    ),
}

_DB["security_enhanced_pat_down"] = {
    "min"         : 120,
    "max"         : 160,
    "default"     : 140,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 1.0,
    "c_s_squared_range": (0.8, 1.4),
    "source"      : (
        "DHS (2018), Table 2-2 (enhanced screening protocols); NFL and NBA security "
        "operations guidelines (cited in DHS venue security assessments, 2019)."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Enhanced screening with pat-down capability (metal-detector wand + pat-down "
        "for alarms). High c_s² due to outlier searches (some patrons require 60+ sec). "
        "Used at high-profile events (Super Bowl, championship events). 120-160 p/lane/hr "
        "is a practical planning figure; actual throughput is environment-dependent."
    ),
}


# ── Ticket Scanning ────────────────────────────────────────────────────────────

_DB["ticketing_barcode_scan"] = {
    "min"         : 900,    # 15/min × 60
    "max"         : 1200,   # 20/min × 60
    "default"     : 1050,
    "unit"        : "persons/turnstile/hour",
    "c_s_squared" : 0.15,
    "c_s_squared_range": (0.10, 0.20),
    "source"      : (
        "IAAM Venue Operations Manual (2007), Section 4.3: Ticketing throughput benchmarks. "
        "Operational notes in venue-design literature support the same order of magnitude, "
        "but the IAAM benchmark is the primary cited basis here."
    ),
    "confidence"  : "high",
    "notes"       : (
        "Barcode scan (QR code / PDF ticket). Service time approximately deterministic "
        "(15-20 sec per scan including patron approaching, scanning, passing through). "
        "Low c_s² reflects near-constant mechanical scan time. Key bottleneck is patron "
        "readiness (ticket on phone, brightness, NFC toggle). IAAM benchmark is 15-20 "
        "persons/minute = 900-1200 persons/hour/turnstile."
    ),
}

_DB["ticketing_rfid_nfc"] = {
    "min"         : 1200,   # 20/min × 60
    "max"         : 1500,   # 25/min × 60
    "default"     : 1350,
    "unit"        : "persons/turnstile/hour",
    "c_s_squared" : 0.12,
    "c_s_squared_range": (0.08, 0.20),
    "source"      : (
        "Allegiant Stadium operations briefing materials cited in Las Vegas Stadium "
        "Authority public meeting records (2021); NFC/RFID throughput literature "
        "in IEEE Transactions on Intelligent Transportation Systems."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "RFID wristband or NFC tap (e.g., Apple Wallet Express mode). Faster than "
        "barcode — tap-and-go with no screen unlock required. c_s² lower than barcode "
        "due to tap requiring less physical dexterity than screen presentation. "
        "Upper bound (1,500/hr) achieved in controlled festival environments."
    ),
}

_DB["ticketing_manual_check"] = {
    "min"         : 480,    # 8/min × 60
    "max"         : 720,    # 12/min × 60
    "default"     : 600,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.30,
    "c_s_squared_range": (0.20, 0.45),
    "source"      : (
        "IAAM Venue Operations Manual (2007), Section 4.3; Fruin (1993) crowd "
        "management benchmarks for manual ticket inspection."
    ),
    "confidence"  : "high",
    "notes"       : (
        "Manual ticket inspection (tear-off stubs or visual check). Staff reviews "
        "and tears/stamps. Higher variance than scan due to occasional patron disputes, "
        "wrong-entry issues. Increasingly rare at major venues; common at smaller "
        "theaters and legacy venues."
    ),
}


# ── Concession Service ─────────────────────────────────────────────────────────

_DB["concession_full_menu"] = {
    "min"         : 48,     # 0.8/min × 60
    "max"         : 72,     # 1.2/min × 60
    "default"     : 60,
    "unit"        : "transactions/register/hour",
    "c_s_squared" : 1.25,
    "c_s_squared_range": (1.0, 1.5),
    "source"      : (
        "Stadia concession operations research: Muller, R. (2009), 'Optimizing "
        "Concession Stand Operations at Stadiums'. Journal of Foodservice Business "
        "Research, 12(3). Also: venue operations benchmarks in IAAM (2007) Section 6.2."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Full menu with cooking (hot dogs, nachos, burgers). High c_s² reflects "
        "exponential-like service times — most transactions are fast but a few "
        "(special orders, price disputes, payment issues) take much longer. "
        "0.8-1.2 transactions/minute = 48-72/hour/register. Bottleneck is typically "
        "cooking prep or payment, not order-taking."
    ),
}

_DB["concession_drinks_snacks"] = {
    "min"         : 90,     # 1.5/min × 60
    "max"         : 150,    # 2.5/min × 60
    "default"     : 120,
    "unit"        : "transactions/register/hour",
    "c_s_squared" : 1.10,
    "c_s_squared_range": (0.9, 1.4),
    "source"      : (
        "IAAM Venue Operations Manual (2007), Section 6.2. Stadia concession "
        "operations studies cited in venue design guidelines (Populous, 2015)."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Drinks and pre-packaged snacks only. No cooking; service limited to pour-and-go "
        "or grab-from-case. Faster than full menu but still high variance due to "
        "payment processing and multi-item orders."
    ),
}

_DB["concession_self_service"] = {
    "min"         : 180,    # 3/min × 60
    "max"         : 300,    # 5/min × 60
    "default"     : 240,
    "unit"        : "transactions/kiosk/hour",
    "c_s_squared" : 0.80,
    "c_s_squared_range": (0.6, 1.1),
    "source"      : (
        "Populous Architecture (2018), 'The Future of Stadium Concessions': "
        "self-service/mobile ordering kiosk throughput benchmarks. Also: "
        "Amazon Go / Just Walk Out technology spec sheets for venue deployments."
    ),
    "confidence"  : "low",
    "notes"       : (
        "Self-service kiosk or grab-and-go (patron selects, scans, pays autonomously). "
        "Emerging technology — published throughput benchmarks vary widely by "
        "technology provider and patron familiarity. Use as a planning figure only; "
        "actual throughput depends heavily on UI design and patron experience."
    ),
}


# ── Restroom Facilities ────────────────────────────────────────────────────────

_DB["restroom_stall"] = {
    "min"         : 2.0,
    "max"         : 3.0,
    "default"     : 2.5,
    "unit"        : "minutes/stall/patron",
    "c_s_squared" : 0.90,
    "c_s_squared_range": (0.7, 1.2),
    "source"      : (
        "Fruin, J.J. (1987). 'Pedestrian Planning and Design', revised ed. "
        "Metropolitan Association of Urban Designers and Environmental Planners. "
        "Chapter 8: Facility Design. Also: IPC (International Plumbing Code) "
        "restroom fixture count tables, which use ~2.5 min/user as design basis."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Average service time per stall per patron including occupancy + queue "
        "progression time. c_s² ≈ 0.9 indicates approximately exponential service "
        "times — consistent with empirical restroom queue studies. Women's facilities "
        "typically average 3.0-3.5 min (IPC adjusts fixture counts accordingly). "
        "This parameter affects restroom queue modeling more than congestion gating."
    ),
}


# ── Pedestrian Flow (Highway Capacity Manual 6th Edition) ─────────────────────

_DB["pedestrian_free_flow"] = {
    "min"         : 1.15,
    "max"         : 1.25,
    "default"     : 1.20,
    "unit"        : "m/s",
    "c_s_squared" : None,   # flow parameter, not service time
    "source"      : "HCM6, Chapter 24, Exhibit 24-1: Pedestrian free-flow speed.",
    "confidence"  : "high",
    "notes"       : "Free-flow speed (unimpeded). HCM6 default is 1.2 m/s (4.0 ft/s).",
}

_DB["pedestrian_los_c"] = {
    "min"         : 0.95,
    "max"         : 1.05,
    "default"     : 1.00,
    "unit"        : "m/s",
    "density_p_per_m2": 0.72,
    "c_s_squared" : None,
    "source"      : "HCM6, Chapter 24, Exhibit 24-2: Speed-flow-density relationships.",
    "confidence"  : "high",
    "notes"       : "Level of Service C: 0.72 persons/m². Comfortable walking, minor conflicts.",
}

_DB["pedestrian_los_e"] = {
    "min"         : 0.45,
    "max"         : 0.55,
    "default"     : 0.50,
    "unit"        : "m/s",
    "density_p_per_m2": 2.17,
    "c_s_squared" : None,
    "source"      : "HCM6, Chapter 24, Exhibit 24-2.",
    "confidence"  : "high",
    "notes"       : "Level of Service E: 2.17 persons/m². Constrained movement, frequent conflicts.",
}

_DB["pedestrian_stairway_factor"] = {
    "min"         : 0.55,
    "max"         : 0.65,
    "default"     : 0.60,
    "unit"        : "multiplier",
    "c_s_squared" : None,
    "source"      : "HCM6, Chapter 24, Section 24.3.1: Stairway adjustment factor.",
    "confidence"  : "high",
    "notes"       : "Multiply level-surface speed by 0.60 for stairway segments.",
}

_DB["pedestrian_ramp_factor"] = {
    "min"         : 0.82,
    "max"         : 0.88,
    "default"     : 0.85,
    "unit"        : "multiplier",
    "c_s_squared" : None,
    "source"      : "HCM6, Chapter 24, Section 24.3.2: Ramp adjustment factor.",
    "confidence"  : "high",
    "notes"       : "Multiply level-surface speed by 0.85 for ramp segments (≤8% grade).",
}

_DB["pedestrian_counter_flow_factor"] = {
    "min"         : 0.65,
    "max"         : 0.75,
    "default"     : 0.70,
    "unit"        : "multiplier",
    "c_s_squared" : None,
    "source"      : (
        "HCM6, Chapter 24, Section 24.4: Bi-directional pedestrian flow analysis. "
        "Fruin (1987), Chapter 5: Effects of counter-flow on pedestrian speed."
    ),
    "confidence"  : "high",
    "notes"       : "Multiply speed by 0.70 for corridors with significant opposing flow.",
}


# ── Operational service rates (planning defaults informed by public reporting) ──
#
# These rates are operational planning defaults informed by public event
# reporting, venue operations context, and literature upper bounds. They are
# intended to represent expected venue operations more closely than the fully
# conservative literature tier.
#
# The numbers are not calibrated from venue-owned scanner logs or direct lane
# throughput telemetry. Use tier='literature' for worst-case / conservative
# planning analysis. Use tier='operational' (default) for expected operations.

_OPERATIONAL_DB: dict[str, dict] = {}

_OPERATIONAL_DB["security_magnetometer_only"] = {
    "min"         : 400,
    "max"         : 650,
    "default"     : 500,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.3,
    "source"      : (
        "Operational planning default informed by public reporting on Super Bowl LVIII "
        "(2024-02-11) and UFC 306 at Sphere Las Vegas (2024-09-14), plus the DHS 2018 "
        "literature baseline of 300 pph/lane. Public reports suggest materially faster "
        "observed operations than conservative planning assumptions, but exact lane "
        "throughput is inferred rather than directly measured."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Reflects experienced venue security staff, pre-event credential validation "
        "at large venues (CLEAR, TSA PreCheck-style lanes), and optimised entry "
        "configurations. Literature rates assume untrained operators and worst-case "
        "compliance. Lower end (400) for inaugural events with staff learning curve; "
        "upper end (650) for mature venue operations with pre-screened lanes."
    ),
}

_OPERATIONAL_DB["security_magnetometer_bag_check"] = {
    "min"         : 300,
    "max"         : 500,
    "default"     : 380,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.4,
    "source"      : (
        "Same operational planning basis as security_magnetometer_only, with bag check "
        "modeled as a slower variant. Literature baseline (DHS 2018): 215 pph/lane. "
        "Operational default reflects public reporting plus literature-informed overhead "
        "for bag screening, not direct scanner telemetry."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Combined magnetometer + bag check. Higher throughput than literature reflects "
        "modern venues' optimised X-ray line management, pre-sorted bag bins, and "
        "trained staff who minimise dwell time per person. c_s² reduced from 0.9 "
        "to 0.4 reflecting more consistent service times with experienced staff."
    ),
}

_OPERATIONAL_DB["security_enhanced_pat_down"] = {
    "min"         : 180,
    "max"         : 320,
    "default"     : 250,
    "unit"        : "persons/lane/hour",
    "c_s_squared" : 0.6,
    "source"      : (
        "Operational planning default informed by Super Bowl LVIII public after-action "
        "reporting and the DHS 2018 literature figure of 140 pph/lane. The uplift vs. "
        "pure literature is an inferred planning adjustment, not a direct measurement."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Enhanced screening with pat-down. Even at highest scrutiny, professional "
        "security teams trained for specific events achieve higher throughput than "
        "literature's conservative estimates. c_s² reduced from 1.0 to 0.6 "
        "reflecting trained staff reducing outlier service times."
    ),
}

_OPERATIONAL_DB["ticketing_barcode_scan"] = {
    "min"         : 900,
    "max"         : 1500,
    "default"     : 1200,
    "unit"        : "persons/turnstile/hour",
    "c_s_squared" : 0.15,
    "source"      : (
        "IAAM Venue Operations Manual (2007) upper bound (1200) adopted as operational "
        "default, reflecting modern mobile ticket readiness and trained gate staff. "
        "Literature range: 900–1200; operational default matches IAAM upper bound."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Barcode scan with experienced gate staff and patron pre-notification campaigns "
        "(have ticket ready, brightness up). Modern venues achieve IAAM upper bound "
        "as standard operating performance, not exceptional performance."
    ),
}

_OPERATIONAL_DB["ticketing_rfid_nfc"] = {
    "min"         : 1200,
    "max"         : 1800,
    "default"     : 1500,
    "unit"        : "persons/turnstile/hour",
    "c_s_squared" : 0.1,
    "source"      : (
        "Las Vegas Stadium Authority public meeting references on NFC operations plus "
        "festival RFID throughput literature. Operational default 1500 reflects a fast "
        "tap-and-go planning assumption for pre-paired devices, not a venue-owned log extract. "
        "Literature baseline (IAAM): 1350."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "RFID wristband or NFC tap. Operational default matches upper literature "
        "range — tap-and-go is highly consistent when patrons are familiar with "
        "the technology (repeat attendees, pre-event digital onboarding)."
    ),
}

_OPERATIONAL_DB["concession_full_menu"] = {
    "min"         : 60,
    "max"         : 120,
    "default"     : 80,
    "unit"        : "transactions/register/hour",
    "c_s_squared" : 1.0,
    "source"      : (
        "Adjusted from Muller (2009) and IAAM (2007) literature range of 48–72. "
        "Modern POS systems, pre-event batch cooking, and trained concession staff "
        "achieve 80 transactions/hr as baseline. Upper end (120) for drinks-focused "
        "positions with minimal cooking overhead."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Full menu with modern POS and experienced concession teams. c_s² kept at 1.0 "
        "as food service times remain inherently variable (special orders, payment "
        "issues, supply replenishment). Bottleneck remains cooking/supply, not POS."
    ),
}

_OPERATIONAL_DB["concession_drinks_snacks"] = {
    "min"         : 100,
    "max"         : 180,
    "default"     : 140,
    "unit"        : "transactions/register/hour",
    "c_s_squared" : 0.8,
    "source"      : (
        "Adjusted from IAAM (2007) drinks-only range of 90–150. Operational default "
        "140 reflects trained pour-and-go operations. c_s² reduced from 1.1 to 0.8 "
        "for more consistent pre-poured/pre-packaged service."
    ),
    "confidence"  : "medium",
    "notes"       : (
        "Drinks and pre-packaged snacks. Faster than full menu with lower variance "
        "when staff pre-set drinks during lulls. Modern tap-to-pay adoption further "
        "reduces transaction time variance."
    ),
}


# ── Public API ─────────────────────────────────────────────────────────────────

class ServiceRateDatabase:
    """
    Container and accessor for all service rate parameters.

    Usage:
        db = ServiceRateDatabase()
        params = db.get("security_magnetometer_only")
        rate   = db.get_service_rate("security", screening_level="standard")
    """

    def __init__(self, tier: str = "operational") -> None:
        """
        Parameters
        ----------
        tier : 'operational' (default) — planning defaults informed by public
               event reporting and literature upper bounds; or 'literature' —
               conservative DHS/Fruin/HCM6/IAAM published values. Use
               'literature' for worst-case planning.
        """
        self._db = _DB
        self._tier = tier

    def get(self, key: str, tier: Optional[str] = None) -> dict:
        """
        Return parameter dict for a named service rate.

        Parameters
        ----------
        key  : service rate key (e.g. 'security_magnetometer_bag_check')
        tier : override instance tier for this call ('operational' or 'literature')
        """
        effective_tier = tier if tier is not None else self._tier
        if effective_tier == "operational" and key in _OPERATIONAL_DB:
            # Start from operational values, fill missing fields from literature
            result = _OPERATIONAL_DB[key].copy()
            for k, v in self._db.get(key, {}).items():
                if k not in result:
                    result[k] = v
            return result
        if key not in self._db:
            raise KeyError(f"Unknown service rate key: '{key}'. Available: {list(self._db.keys())}")
        return self._db[key].copy()

    def available_keys(self) -> list[str]:
        return list(self._db.keys())

    def get_service_rate(
        self,
        node_type: str,
        screening_level: str = "standard",
        service_type: str = "full_menu",
        tier: Optional[str] = None,
    ) -> dict:
        """
        Return service rate parameters for a queueing network node.

        Parameters
        ----------
        node_type : one of 'security', 'ticketing', 'concession', 'restroom', 'pedestrian'
        screening_level : for security — 'basic' | 'standard' | 'enhanced'
        service_type : for concession — 'full_menu' | 'drinks_snacks' | 'self_service'
                       for ticketing — 'barcode' | 'rfid' | 'manual'

        Parameters
        ----------
        node_type        : one of 'security', 'ticketing', 'concession', 'restroom', 'pedestrian'
        screening_level  : for security — 'basic' | 'standard' | 'enhanced'
        service_type     : for concession — 'full_menu' | 'drinks_snacks' | 'self_service'
                           for ticketing — 'barcode' | 'rfid' | 'manual'
        tier             : 'operational' (default) or 'literature'; overrides instance tier

        Returns
        -------
        dict with 'min', 'max', 'default', 'unit', 'c_s_squared', 'source', 'notes'
        """
        if node_type == "security":
            mapping = {
                "basic"    : "security_magnetometer_only",
                "standard" : "security_magnetometer_bag_check",
                "enhanced" : "security_enhanced_pat_down",
            }
            key = mapping.get(screening_level)
            if key is None:
                raise ValueError(f"Unknown screening_level: '{screening_level}'. "
                                 f"Use: {list(mapping.keys())}")

        elif node_type == "ticketing":
            mapping = {
                "barcode" : "ticketing_barcode_scan",
                "rfid"    : "ticketing_rfid_nfc",
                "manual"  : "ticketing_manual_check",
            }
            key = mapping.get(service_type, "ticketing_barcode_scan")

        elif node_type == "concession":
            mapping = {
                "full_menu"   : "concession_full_menu",
                "drinks_snacks": "concession_drinks_snacks",
                "self_service": "concession_self_service",
            }
            key = mapping.get(service_type, "concession_full_menu")

        elif node_type == "restroom":
            key = "restroom_stall"
            return self.get(key, tier=tier)

        elif node_type == "pedestrian":
            # Return a summary dict of HCM pedestrian flow parameters
            return {
                "free_flow_speed_m_s"   : self._db["pedestrian_free_flow"]["default"],
                "los_c_speed_m_s"       : self._db["pedestrian_los_c"]["default"],
                "los_e_speed_m_s"       : self._db["pedestrian_los_e"]["default"],
                "los_c_density_p_m2"    : self._db["pedestrian_los_c"]["density_p_per_m2"],
                "los_e_density_p_m2"    : self._db["pedestrian_los_e"]["density_p_per_m2"],
                "stairway_factor"       : self._db["pedestrian_stairway_factor"]["default"],
                "ramp_factor"           : self._db["pedestrian_ramp_factor"]["default"],
                "counter_flow_factor"   : self._db["pedestrian_counter_flow_factor"]["default"],
                "source"                : "HCM6, Chapter 24 (Transportation Research Board, 2016)",
            }
        else:
            raise ValueError(f"Unknown node_type: '{node_type}'. "
                             f"Use: security, ticketing, concession, restroom, pedestrian")

        return self.get(key, tier=tier)

    def kingman_wait(
        self,
        arrival_rate_per_hr: float,
        n_lanes: int,
        node_type: str,
        screening_level: str = "standard",
        service_type: str = "full_menu",
        c_a_squared: float = 1.0,
        tier: Optional[str] = None,
    ) -> dict:
        """
        Compute Kingman G/G/1 approximation for expected wait time.

        E[W] = (ρ / (1 - ρ)) × ((c_a² + c_s²) / 2) × (1 / μ)

        where:
          ρ = λ / (N × μ)   [server utilization]
          λ = arrival rate (persons/hr total)
          μ = service rate per lane (persons/hr)
          N = number of lanes
          c_a² = arrival coefficient of variation squared (default 1.0 = Poisson)
          c_s² = service coefficient of variation squared (from parameter database)

        Parameters
        ----------
        arrival_rate_per_hr : total arrivals per hour (all lanes combined)
        n_lanes             : number of parallel service lanes/servers
        node_type           : see get_service_rate()
        screening_level     : see get_service_rate()
        service_type        : see get_service_rate()
        c_a_squared         : arrival process variance (1.0 = Poisson)

        Returns
        -------
        dict with 'wait_min', 'utilization', 'is_stable', 'parameters'
        """
        params = self.get_service_rate(node_type, screening_level, service_type, tier=tier)
        if isinstance(params, dict) and "free_flow_speed_m_s" in params:
            raise ValueError("Pedestrian flow parameters cannot be used with Kingman formula.")

        mu = params["default"]          # service rate (persons/hr/lane)
        c_s2 = params["c_s_squared"]

        lam = arrival_rate_per_hr
        rho = lam / (n_lanes * mu)     # utilization

        if rho >= 1.0:
            return {
                "wait_min"   : float("inf"),
                "utilization": round(rho, 4),
                "is_stable"  : False,
                "parameters" : params,
            }

        wait_hr = (rho / (1.0 - rho)) * ((c_a_squared + c_s2) / 2.0) * (1.0 / mu)
        wait_min = wait_hr * 60.0

        return {
            "wait_min"   : round(wait_min, 2),
            "utilization": round(rho, 4),
            "is_stable"  : True,
            "parameters" : params,
        }


# Module-level singletons for convenience
_DEFAULT_DB = ServiceRateDatabase(tier="operational")   # operational planning tier (default)
_LITERATURE_DB = ServiceRateDatabase(tier="literature") # conservative literature rates


def get_service_rate(
    node_type: str,
    screening_level: str = "standard",
    service_type: str = "full_menu",
    tier: Optional[str] = None,
) -> dict:
    """
    Convenience wrapper — returns service rate parameters.

    Parameters
    ----------
    tier : 'operational' (default) or 'literature'. Defaults to 'operational'
           (planning defaults informed by public reporting and literature).
           Use 'literature' for conservative worst-case planning analysis.
    """
    db = _LITERATURE_DB if tier == "literature" else _DEFAULT_DB
    return db.get_service_rate(node_type, screening_level, service_type)


if __name__ == "__main__":
    db = ServiceRateDatabase()
    print("Security (standard):", db.get_service_rate("security", "standard"))
    print("\nTicketing (barcode):", db.get_service_rate("ticketing", service_type="barcode"))
    print("\nConcession (full):", db.get_service_rate("concession", service_type="full_menu"))

    # Kingman example: 50,000 pax entering over 2 hr via 8 gates × 6 lanes
    result = db.kingman_wait(
        arrival_rate_per_hr=50000 / 2,
        n_lanes=8 * 6,
        node_type="security",
        screening_level="standard",
    )
    print(f"\nKingman wait (50k pax, 48 lanes, 2hr window): {result['wait_min']:.1f} min "
          f"(ρ={result['utilization']:.3f})")
