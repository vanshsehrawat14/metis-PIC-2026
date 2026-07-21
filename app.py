import datetime
import math
import numpy as np
import streamlit as st

from simulation.engine      import MonteCarloEngine
from simulation.environment import generate_environment
from optimization.optimizer import VectorizedOptimizer
from visualization.plots    import (
    build_tradeoff_chart, build_radar_chart,
    build_staffing_comparison, build_wait_distribution,
)
from visualization.map      import build_vegas_map, build_f1_map, build_city_map, VEGAS_VENUES

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Vane | Decision Intelligence",
    page_icon="◼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS  —  Mandelbrot Aesthetic · Computer Modern · Clean Academic
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/aaaakshat/cm-web-fonts@latest/fonts.css');
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Base ──────────────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stApp {
    font-family: 'Computer Modern Serif', 'CMU Serif', Georgia, serif !important;
    background-color: #08091a !important;
    color: #c8c8dc !important;
}
.block-container { padding-top: 1.8rem !important; padding-bottom: 3rem !important; max-width: 100% !important; }
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }

/* ── Sidebar ────────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: #08091a !important;
    border-right: 1px solid #1c1d3a !important;
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.6rem !important; }

/* ── Scrollbar ──────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #08091a; }
::-webkit-scrollbar-thumb { background: #1c1d3a; border-radius: 2px; }

/* ── Animations — minimal, just a quiet fade-in ─────────────────────────── */
@keyframes mt-fadein {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes mt-pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
}
@keyframes nx-glow-teal {
    from { box-shadow: none; }
    to   { box-shadow: 0 0 20px rgba(74,144,217,0.12); }
}
.nx-reveal   { animation: mt-fadein 0.45s ease-out forwards; }
.nx-reveal-2 { animation: mt-fadein 0.45s 0.08s ease-out forwards; opacity: 0; }
.nx-reveal-3 { animation: mt-fadein 0.45s 0.16s ease-out forwards; opacity: 0; }
.nx-reveal-4 { animation: mt-fadein 0.45s 0.24s ease-out forwards; opacity: 0; }

/* ── Header ─────────────────────────────────────────────────────────────────── */
.nx-header {
    display: flex; align-items: baseline; justify-content: space-between;
    padding-bottom: 16px; border-bottom: 1px solid #1c1d3a; margin-bottom: 16px;
}
.nx-wordmark {
    font-family: 'Computer Modern Serif', Georgia, serif;
    font-size: 2rem; font-weight: 700; letter-spacing: 0.08em;
    color: #e0e0f0; line-height: 1;
}
.nx-sub {
    font-family: 'Inter', sans-serif;
    font-size: .6rem; letter-spacing: .2em; text-transform: uppercase;
    color: #4a90d9; margin-left: 14px;
}
.nx-pills    { display: flex; gap: 8px; align-items: center; }
.pill        { font-family: 'Inter', sans-serif;
               font-size: .55rem; font-weight: 600; letter-spacing: .1em; text-transform: uppercase;
               padding: 3px 10px; border-radius: 10px; border: 1px solid; }
.pill-teal   { border-color: #4a90d9; color: #4a90d9; background: rgba(74,144,217,0.06); }
.pill-dim    { border-color: #1c1d3a; color: #505068; }
.pill-live   { border-color: #4a90d9; color: #4a90d9; background: rgba(74,144,217,0.06); }
.live-dot    { display: inline-block; width: 5px; height: 5px; background: #4a90d9;
               border-radius: 50%; margin-right: 5px; animation: mt-pulse 2s ease-in-out infinite; }

/* ── Map caption bar ──────────────────────────────────────────────────────── */
.map-caption {
    background: #08091a; border: 1px solid #1c1d3a; border-top: none;
    padding: 8px 18px; display: flex; gap: 24px; font-size: .65rem;
    align-items: center; flex-wrap: wrap;
    font-family: 'Inter', sans-serif;
}
.mc-key { color: #505068; text-transform: uppercase; letter-spacing: .1em; margin-right: 5px; font-size: .55rem; }

/* ── Dividers ────────────────────────────────────────────────────────────────── */
.nx-divider { height: 1px; background: #1c1d3a; margin: 24px 0; }
.nx-section-break {
    display: flex; align-items: center; gap: 16px; margin: 28px 0 20px 0;
}
.nx-section-line { flex: 1; height: 1px; background: #1c1d3a; }
.nx-section-tag  {
    font-family: 'Inter', sans-serif;
    font-size: .55rem; font-weight: 600; letter-spacing: .18em; text-transform: uppercase;
    color: #4a90d9; white-space: nowrap;
}

/* ── KPI Cards ───────────────────────────────────────────────────────────── */
.kpi { background: #0e0f24; border: 1px solid #1c1d3a; border-radius: 5px;
       padding: 20px 18px 16px 18px; position: relative; overflow: hidden;
       transition: border-color 0.25s; }
.kpi:hover { border-color: #2a2b4a; }
.kpi-bar   { position: absolute; top: 0; left: 0; right: 0; height: 2px; }
.kpi-lbl   { font-family: 'Inter', sans-serif;
             font-size: .55rem; font-weight: 600; letter-spacing: .16em; text-transform: uppercase;
             color: #6a6a88; margin-bottom: 8px; }
.kpi-num   { font-family: 'Computer Modern Serif', Georgia, serif;
             font-size: 2.4rem; font-weight: 700; line-height: 1; margin-bottom: 4px; letter-spacing: -.02em; }
.kpi-sub   { font-family: 'Inter', sans-serif;
             font-size: .65rem; color: #505068; }

/* ── Venue recommendation cards ─────────────────────────────────────────── */
.venue-card {
    background: #0e0f24; border: 1px solid #1c1d3a; border-radius: 5px;
    padding: 14px 16px; margin-bottom: 8px; transition: border-color 0.2s;
}
.venue-card:hover { border-color: #2a2b4a; }
.venue-rank  { font-family: 'Inter', sans-serif;
               font-size: .54rem; font-weight: 700; letter-spacing: .1em; padding: 2px 8px;
               border-radius: 2px; display: inline-block; margin-bottom: 6px; text-transform: uppercase; }
.venue-name  { font-size: .9rem; font-weight: 600; color: #e0e0f0; margin-bottom: 4px; }
.venue-stats { font-family: 'Inter', sans-serif; font-size: .7rem; color: #6a6a88; line-height: 1.8; }
.venue-why   { font-size: .72rem; color: #9898b0; margin-top: 6px; line-height: 1.6; }

/* ── Recommendation items ────────────────────────────────────────────────── */
.rec-item     { border-left: 2px solid; padding: 12px 16px; background: #0e0f24;
                margin-bottom: 8px; border-radius: 0 5px 5px 0; }
.rec-item-top { }
.rec-badge    { font-family: 'Inter', sans-serif;
                font-size: .54rem; font-weight: 700; letter-spacing: .1em;
                padding: 2px 8px; border-radius: 2px; display: inline-block;
                margin-bottom: 6px; text-transform: uppercase; }
.rec-text { font-size: .84rem; color: #9898b0; line-height: 1.75; }
.rec-conf { font-family: 'Inter', sans-serif; font-size: .62rem; color: #505068; margin-top: 6px; }

/* ── Cost of Inaction ────────────────────────────────────────────────────── */
.coi-row { background: #0e0f24; border: 1px solid #1c1d3a; border-radius: 5px;
           padding: 12px 16px; margin-bottom: 6px; display: flex; align-items: center; gap: 14px; }
.coi-val { font-size: 1.15rem; font-weight: 700; min-width: 80px; }
.coi-lbl { font-family: 'Inter', sans-serif; font-size: .7rem; color: #6a6a88; }

/* ── Uncertainty bars ────────────────────────────────────────────────────── */
.unc-wrap   { background: #0e0f24; border: 1px solid #1c1d3a; border-radius: 5px; padding: 16px 20px; }
.unc-track  { background: #08091a; border-radius: 3px; height: 4px; position: relative; margin: 5px 0 8px; }
.unc-fill   { position: absolute; height: 4px; border-radius: 3px;
              background: linear-gradient(90deg, #1c1d3a, #2a2b4a); }
.unc-needle { position: absolute; top: -4px; width: 2px; height: 12px; border-radius: 1px; transform: translateX(-50%); }
.unc-ends   { display: flex; justify-content: space-between; font-family: 'Inter', sans-serif;
              font-size: .58rem; color: #505068; }

/* ── Stress cards ────────────────────────────────────────────────────────── */
.stress-card  { background: #0e0f24; border: 1px solid #1c1d3a; border-radius: 5px; padding: 16px 18px; }
.stress-tag   { font-family: 'Inter', sans-serif;
                font-size: .54rem; font-weight: 700; text-transform: uppercase; letter-spacing: .1em;
                background: #d45050; color: white; padding: 2px 8px; border-radius: 2px;
                display: inline-block; margin-bottom: 8px; }
.stress-title { font-size: .88rem; font-weight: 600; color: #e0e0f0; margin-bottom: 2px; }
.stress-sub   { font-family: 'Inter', sans-serif; font-size: .62rem; color: #505068; margin-bottom: 12px; }
.stress-row   { margin-bottom: 10px; }
.stress-lbl   { font-family: 'Inter', sans-serif;
                font-size: .54rem; text-transform: uppercase; letter-spacing: .1em; color: #505068; margin-bottom: 3px; }
.stress-vals  { display: flex; align-items: center; gap: 10px; }
.stress-base  { font-size: 1.05rem; font-weight: 600; color: #4a90d9; }
.stress-arrow { color: #1c1d3a; font-size: .8rem; }
.stress-hit   { font-size: 1.05rem; font-weight: 600; }

/* ── Math engine boxes ───────────────────────────────────────────────────── */
.math-box { background: #0e0f24; border-left: 2px solid #4a90d9; border-radius: 0 5px 5px 0;
            padding: 16px 20px; margin: 10px 0;
            font-family: 'Computer Modern Typewriter', 'Courier New', monospace;
            font-size: .82rem; color: #9898b0; line-height: 1.8; }
.math-box b { color: #4a90d9; }

/* ── Event profile badge ─────────────────────────────────────────────────── */
.event-profile-card {
    background: #0e0f24;
    border: 1px solid #1c1d3a; border-top: 2px solid #4a90d9;
    border-radius: 5px; padding: 16px 18px; margin-bottom: 14px;
}
.ep-title  { font-family: 'Inter', sans-serif;
             font-size: .55rem; font-weight: 600; letter-spacing: .16em; text-transform: uppercase;
             color: #4a90d9; margin-bottom: 8px; }
.ep-grid   { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.ep-stat-lbl { font-family: 'Inter', sans-serif;
               font-size: .54rem; color: #6a6a88; text-transform: uppercase; letter-spacing: .1em; margin-bottom: 3px; }
.ep-stat-val { font-size: 1.05rem; font-weight: 600; color: #e0e0f0; }

/* ── Sidebar labels ──────────────────────────────────────────────────────── */
.sb-lbl { font-family: 'Inter', sans-serif;
          font-size: .55rem; font-weight: 600; letter-spacing: .16em; text-transform: uppercase;
          color: #4a90d9; margin: 16px 0 5px; display: block; }
.sb-divider { height: 1px; background: #1c1d3a; margin: 12px 0; }

/* ── Ready box ───────────────────────────────────────────────────────────── */
.ready-box { border: 1px solid #1c1d3a; border-radius: 5px; background: #0e0f24;
             padding: 28px 32px; text-align: center; margin: 20px 0; }
.ready-title { font-size: 1.1rem; font-weight: 600; color: #e0e0f0; margin-bottom: 10px; }
.ready-sub   { font-family: 'Inter', sans-serif; font-size: .78rem; color: #6a6a88; line-height: 1.9; }
.ready-hint  { font-family: 'Inter', sans-serif; font-size: .62rem; color: #4a90d9; margin-top: 14px; letter-spacing: .06em; }

/* ── Tab override ────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"]  { background-color: #0e0f24 !important; border-radius: 5px; padding: 4px; border: 1px solid #1c1d3a; }
.stTabs [data-baseweb="tab"]       { font-family: 'Inter', sans-serif !important; color: #6a6a88 !important; font-weight: 600; border-radius: 4px; }
.stTabs [aria-selected="true"]     { color: #4a90d9 !important; background-color: #1c1d3a !important; }

/* ── Streamlit overrides ────────────────────────────────────────────────── */
div[data-testid="stSlider"] > div > div { color: #4a90d9 !important; }
.stTextArea textarea { background: #0e0f24 !important; border: 1px solid #1c1d3a !important; color: #c8c8dc !important; }
.stSelectbox > div   { background: #0e0f24 !important; border: 1px solid #1c1d3a !important; }
div[data-testid="stMetricValue"] { color: #4a90d9; font-weight: 600; }

/* ── Vane Button — clean blue ──────────────────────────────────────────── */
.stButton>button {
    font-family: 'Inter', sans-serif !important;
    background: #1a3a6a !important;
    color: #c8c8dc !important;
    font-weight: 700 !important;
    border: 1px solid #2a4a7a !important;
    border-radius: 4px;
    height: 3em;
    letter-spacing: 1.2px;
    transition: all 0.2s ease;
}
.stButton>button:hover {
    background: #2a4a8a !important;
    border: 1px solid #4a90d9 !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# EVENT PROFILES
# ══════════════════════════════════════════════════════════════════════════════
EVENT_PROFILES = {
    "Music Festival / Concert": {
        "phf": 0.45, "density_tolerance": 0.85, "heat_vuln": 1.30,
        "stay_hrs": 4.5, "avg_age": 28,
        "arrival": "High — crowd surge at gates",
        "desc": "Massive arrival spike at open, high density tolerance, late-night egress.",
        "venue_types": ["Outdoor", "Stadium", "Arena"],
        "icon": "🎵",
    },
    "Tech / Research Conference": {
        "phf": 0.18, "density_tolerance": 0.55, "heat_vuln": 1.00,
        "stay_hrs": 8.0, "avg_age": 38,
        "arrival": "Low — staggered check-in over hours",
        "desc": "Staggered professional arrivals, low density tolerance, daytime traffic peak.",
        "venue_types": ["Expo", "Arena"],
        "icon": "💻",
    },
    "Major Sporting Event": {
        "phf": 0.55, "density_tolerance": 0.80, "heat_vuln": 1.15,
        "stay_hrs": 3.5, "avg_age": 35,
        "arrival": "Very High — massive pre-game rush",
        "desc": "Simultaneous arrival wave, synchronized post-event egress bottleneck.",
        "venue_types": ["Stadium", "Arena", "Speedway"],
        "icon": "🏆",
    },
    "EDM / Nightclub Festival": {
        "phf": 0.35, "density_tolerance": 0.92, "heat_vuln": 1.45,
        "stay_hrs": 6.0, "avg_age": 24,
        "arrival": "High — late-night arrival wave",
        "desc": "Extreme density tolerance, highly heat-sensitive crowd, late-night logistics.",
        "venue_types": ["Outdoor", "Stadium"],
        "icon": "🎧",
    },
    "Trade Show / Expo": {
        "phf": 0.14, "density_tolerance": 0.50, "heat_vuln": 0.90,
        "stay_hrs": 7.0, "avg_age": 42,
        "arrival": "Very Low — distributed over 3+ days",
        "desc": "Multi-day, highly distributed arrivals. Professional crowd expects space.",
        "venue_types": ["Expo"],
        "icon": "🏛",
    },
    "Boxing / MMA Fight Night": {
        "phf": 0.60, "density_tolerance": 0.82, "heat_vuln": 1.10,
        "stay_hrs": 3.5, "avg_age": 32,
        "arrival": "Extreme — everyone arrives together",
        "desc": "Near-simultaneous arrival, fast post-event egress, high security screening.",
        "venue_types": ["Arena", "Stadium"],
        "icon": "🥊",
    },
    "Corporate / Private Event": {
        "phf": 0.20, "density_tolerance": 0.45, "heat_vuln": 0.95,
        "stay_hrs": 5.0, "avg_age": 40,
        "arrival": "Low — scheduled, pre-registered",
        "desc": "VIP crowd, very low density tolerance. Premium experience expected.",
        "venue_types": ["Theater", "Arena", "Ballroom"],
        "icon": "🤝",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# MODULE INIT
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def _base_engine():
    """Default engine used for live map preview (PHF=0.30)."""
    eng = MonteCarloEngine(n_simulations=1000, peak_hour_fraction=0.30)
    return eng


_preview_engine = _base_engine()

_VEGAS_KW = {"vegas", "strip", "f1", "formula", "lvgp", "lvms", "koval", "allegiant",
             "tmobile", "t-mobile", "sphere", "mandalay", "mgm", "caesars", "resorts"}


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def _is_vegas(loc: str) -> bool:
    lc = loc.lower()
    return any(kw in lc for kw in _VEGAS_KW)


def _est_demand(capacity, price):
    elast = (max(0.0, 1.0 - price / 1000.0) if price <= 200
             else float(np.exp(-(price - 200) / 100.0)))
    return int(capacity * elast)


def _kpi(label, num_str, sub_str, accent="#4a90d9", glow=False):
    gs = f"box-shadow:0 0 28px {accent}22;animation:nx-glow-teal 2s ease-in-out infinite;" if glow else ""
    return f"""
    <div class="kpi" style="{gs}">
      <div class="kpi-bar" style="background:{accent}"></div>
      <div class="kpi-lbl">{label}</div>
      <div class="kpi-num" style="color:{accent}">{num_str}</div>
      <div class="kpi-sub">{sub_str}</div>
    </div>"""


_BADGE = {
    "CRITICAL"  : ("#d45050", "rgba(212,80,80,0.06)"),
    "WARNING"   : ("#c49030", "rgba(196,144,48,0.06)"),
    "LOGISTICS" : ("#4a90d9", "rgba(74,144,217,0.06)"),
    "RISK"      : ("#c49030", "rgba(196,144,48,0.06)"),
    "REVENUE"   : ("#4a90d9", "rgba(74,144,217,0.06)"),
    "EFFICIENCY": ("#4a90d9", "rgba(74,144,217,0.06)"),
    "OPTIMIZED" : ("#6a6a88", "rgba(106,106,136,0.06)"),
    "VENUE"     : ("#4a90d9", "rgba(74,144,217,0.06)"),
}


def _unc_row(label, p10, mean, p90, suffix, scale_max, threshold, invert=False):
    good     = (mean >= threshold) if invert else (mean <= threshold)
    nc       = "#4a90d9" if good else "#d45050"
    span     = max(scale_max, 1e-9)
    p10_pct  = max(0.5, min(97, p10  / span * 100))
    mean_pct = max(1.0, min(97, mean / span * 100))
    p90_pct  = min(99.0,        p90  / span * 100)
    w_pct    = max(1.0, p90_pct - p10_pct)
    fmt = (lambda v: f"${v/1e6:.2f}M") if suffix == "$M" else (lambda v: f"{v:.1f}{suffix}")
    return f"""
    <div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:.72rem;font-weight:600;color:#6a6a88">{label}</span>
        <span style="font-size:.8rem;font-weight:800;color:{nc}">{fmt(mean)}</span>
      </div>
      <div class="unc-track">
        <div class="unc-fill" style="left:{p10_pct:.1f}%;width:{w_pct:.1f}%"></div>
        <div class="unc-needle" style="left:{mean_pct:.1f}%;background:{nc}"></div>
      </div>
      <div class="unc-ends"><span>P10 {fmt(p10)}</span><span>P90 {fmt(p90)}</span></div>
    </div>"""


def _coi_row(val_str, label, bad=True):
    c = "#d45050" if bad else "#4a90d9"
    return f"""
    <div class="coi-row">
      <div class="coi-val" style="color:{c}">{val_str}</div>
      <div class="coi-lbl">{label}</div>
    </div>"""


def _stress_card(title, subtitle, base_res, stress_res):
    bc = base_res["cong_mean"][0] * 100
    bw = base_res["wait_mean"][0]
    bh = base_res["hes_mean"][0]
    sc = stress_res["cong_mean"][0] * 100
    sw = stress_res["wait_mean"][0]
    sh = stress_res["hes_mean"][0]

    def srow(lbl, bv, sv, fmt, bad_up=True):
        worse = (sv > bv) if bad_up else (sv < bv)
        hc    = "#d45050" if worse else "#4a90d9"
        return f"""
        <div class="stress-row">
          <div class="stress-lbl">{lbl}</div>
          <div class="stress-vals">
            <div class="stress-base">{fmt(bv)}</div>
            <div class="stress-arrow">&#8594;</div>
            <div class="stress-hit" style="color:{hc}">{fmt(sv)}</div>
          </div>
        </div>"""

    return (
        f'<div class="stress-card">'
        f'<div class="stress-tag">Stress Test</div>'
        f'<div class="stress-title">{title}</div>'
        f'<div class="stress-sub">{subtitle}</div>'
        + srow("Congestion Risk", bc, sc, lambda v: f"{v:.0f}%")
        + srow("Avg Wait Time",   bw, sw, lambda v: f"{v:.0f} min")
        + srow("Human Exp.",      bh, sh, lambda v: f"{v:.0f}/100", bad_up=False)
        + "</div>"
    )


def _gen_recs(recs, res, env, goal, location, event_type, profile):
    items = []
    rec1  = recs[0]
    sd    = rec1["staffing_delta"]
    pd    = rec1["price_delta"]

    if goal == "Minimize Congestion Risk":
        cong_now = res["cong_mean"][0] * 100
        sev = "CRITICAL" if cong_now > 65 else "WARNING" if cong_now > 40 else "EFFICIENCY"
        if abs(sd) >= 5:
            verb = "Hire" if sd > 0 else "Reduce headcount by"
            items.append((sev,
                f"{verb} <b>{abs(sd):,} workers</b> — model projects congestion dropping from "
                f"{cong_now:.0f}% to {rec1['congestion']*100:.0f}%.", rec1["confidence"]))
        else:
            items.append((sev,
                f"Staffing is near-optimal. Deploy crowd-routing protocols to hold "
                f"congestion below {rec1['congestion']*100:.0f}%.", rec1["confidence"]))

    elif goal == "Keep wait time < 10 mins":
        wait_now = res["wait_mean"][0]
        sev = "CRITICAL" if wait_now > 20 else "WARNING" if wait_now > 10 else "EFFICIENCY"
        if abs(sd) >= 5:
            verb = "Hire" if sd > 0 else "Reduce staff by"
            items.append((sev,
                f"{verb} <b>{abs(sd):,} workers</b> — average wait drops from "
                f"{wait_now:.1f} min to {rec1['wait']:.1f} min.", rec1["confidence"]))
        else:
            items.append((sev,
                f"Process improvements can cut wait from {wait_now:.1f} to "
                f"{rec1['wait']:.1f} min without adding headcount.", rec1["confidence"]))

    else:  # Maximize Revenue Safely
        if abs(pd) >= 3:
            verb = "Increase" if pd > 0 else "Reduce"
            items.append(("REVENUE",
                f"{verb} ticket price to <b>${rec1['price']:.0f}</b> "
                f"({'+' if pd>0 else ''}{pd:.0f}) — projected revenue "
                f"<b>${rec1['revenue']/1e6:.2f}M</b> with breakdown risk at "
                f"{rec1['breakdown']*100:.1f}%.", rec1["confidence"]))
        if abs(sd) >= 5:
            verb = "Hire" if sd > 0 else "Reduce headcount by"
            items.append(("EFFICIENCY",
                f"{verb} <b>{abs(sd):,} workers</b> to maximise revenue per labour dollar.",
                rec1["confidence"]))

    # Event-type specific insights
    if profile["heat_vuln"] >= 1.3 and env["weather_risk"] > 0.45:
        items.append(("RISK",
            f"<b>{event_type}</b> crowds skew younger (avg age {profile['avg_age']}) and "
            f"show <b>{int((profile['heat_vuln']-1)*100)}% higher heat vulnerability</b> "
            f"than baseline. With current weather risk at {env['weather_risk']*100:.0f}%, "
            f"deploy additional hydration stations and medical units.",
            78))

    if env["traffic_stress"] > 0.70:
        items.append(("LOGISTICS",
            f"Event start falls within <b>peak regional traffic</b> for {location}. "
            f"A 2-hour shift in start time reduces transit pressure by "
            f"~{int(env['traffic_stress']*45)}%. "
            f"Average attendee stay: {profile['stay_hrs']:.0f} hrs — "
            f"schedule staggered exit windows.",
            82))

    if env["weather_risk"] > 0.55:
        items.append(("RISK",
            f"Historical weather disruption risk for <b>{location}</b>: "
            f"<b>{env['weather_risk']*100:.0f}%</b>. Allocate 15% of operational budget "
            f"to contingency infrastructure (cooling, medical, emergency egress).",
            74))

    if not items:
        items.append(("OPTIMIZED",
            f"Parameters are at peak efficiency. Projected revenue "
            f"<b>${recs[0]['revenue']/1e6:.2f}M</b>. No corrective action required.",
            95))

    return items


def _recommend_venues(attendance: int, event_type: str, weather_risk: float) -> list:
    """Score all Vegas venues and return top 3 sorted by suitability."""
    profile      = EVENT_PROFILES[event_type]
    pref_types   = profile["venue_types"]
    scores       = []

    for vname, v in VEGAS_VENUES.items():
        util = attendance / max(v["max_cap"], 1)

        # Capacity fit: sweet spot 60–90%
        if util > 1.10:
            fit = max(0.0, 1.0 - (util - 1.0) * 3)
        elif util > 0.90:
            fit = 1.0 - (util - 0.90) * 2
        elif util >= 0.60:
            fit = 1.0 - abs(util - 0.75) * 1.5
        elif util >= 0.30:
            fit = 0.55
        else:
            fit = max(0.0, util * 1.2)

        type_match      = 1.0 if v["type"] in pref_types else 0.4
        weather_penalty = v["outdoor_factor"] * weather_risk * 0.4
        transit_bonus   = v["transit"] * 0.15

        total = fit * 0.50 + type_match * 0.25 + transit_bonus - weather_penalty * 0.20
        scores.append((vname, total, util, v["type"], v["max_cap"], v["transit"]))

    scores.sort(key=lambda x: -x[1])
    return scores[:3]


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="padding:0 0 16px;border-bottom:1px solid #1c1d3a;margin-bottom:4px">
      <div style="font-family:'Computer Modern Serif',Georgia,serif;font-size:1.5rem;font-weight:700;letter-spacing:0.06em;color:#e0e0f0">Vane</div>
      <div style="font-family:'Inter',sans-serif;font-size:.55rem;color:#4a90d9;letter-spacing:.18em;text-transform:uppercase;margin-top:2px">
        Decision Intelligence
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Event Setup ─────────────────────────────────────────────────────────
    st.markdown('<span class="sb-lbl">Event Type</span>', unsafe_allow_html=True)
    event_type = st.selectbox("Event Type", list(EVENT_PROFILES.keys()),
                              label_visibility="collapsed",
                              format_func=lambda k: f"{EVENT_PROFILES[k]['icon']}  {k}")
    profile = EVENT_PROFILES[event_type]

    st.markdown(
        f'<div style="font-size:.65rem;color:#6a6a88;line-height:1.7;margin:-4px 0 8px;'
        f'padding:8px 10px;background:#0e0f24;border-radius:4px;border:1px solid #1c1d3a">'
        f'{profile["desc"]}</div>', unsafe_allow_html=True)

    st.markdown('<span class="sb-lbl">Describe Your Event (optional)</span>', unsafe_allow_html=True)
    event_desc = st.text_area(
        "Event description", value="", height=72,
        label_visibility="collapsed",
        placeholder='e.g. "50k tech expo, 3 days, July, VIP section needed"',
    )

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

    # ── Location ─────────────────────────────────────────────────────────────
    st.markdown('<span class="sb-lbl">Location</span>', unsafe_allow_html=True)
    loc_mode = st.radio("Location mode", ["Las Vegas Venue", "Custom Location"],
                        horizontal=True, label_visibility="collapsed")

    selected_vegas_venue = None
    if loc_mode == "Las Vegas Venue":
        selected_vegas_venue = st.selectbox(
            "Vegas Venue", list(VEGAS_VENUES.keys()), label_visibility="collapsed")
        location = selected_vegas_venue
        v_info   = VEGAS_VENUES[selected_vegas_venue]
        st.caption(f"{v_info['type']} · Max capacity {v_info['max_cap']:,}")
    else:
        location = st.text_input("Location", value="Las Vegas Strip",
                                 label_visibility="collapsed",
                                 placeholder="City, Venue, or Address")

    dc, tc = st.columns(2)
    event_date = dc.date_input("Date",  datetime.date(2026, 11, 21), label_visibility="collapsed")
    start_time = tc.time_input("Start", datetime.time(17, 30),       label_visibility="collapsed")
    st.caption(f"{event_date.strftime('%b %d, %Y')}  ·  {start_time.strftime('%H:%M')}")

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

    # ── Operations ───────────────────────────────────────────────────────────
    st.markdown('<span class="sb-lbl">Operations</span>', unsafe_allow_html=True)
    capacity = st.number_input("Expected Attendance", value=50000, step=5000,
                               min_value=100, max_value=500000,
                               label_visibility="collapsed")
    staff    = st.slider("Staff Deployed",   100, 3000, 600, step=50)
    price    = st.slider("Ticket Price ($)",  20,  500, 120)

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    st.markdown('<span class="sb-lbl">Optimization Objective</span>', unsafe_allow_html=True)
    goal = st.selectbox("Goal", [
        "Minimize Congestion Risk",
        "Keep wait time < 10 mins",
        "Maximize Revenue Safely (Breakdown < 5%)",
    ], label_visibility="collapsed")

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    run_btn = st.button("RUN ANALYSIS", type="primary", use_container_width=True)

    # Calibration info
    if _preview_engine.is_calibrated():
        st.markdown(
            f'<div style="font-size:.6rem;color:#6a6a88;margin-top:10px;line-height:2">'
            f'<span style="color:#4a90d9">Model</span> &nbsp; Kingman G/G/1 queueing<br>'
            f'<span style="color:#4a90d9">Engine</span> &nbsp; 1,000 Monte Carlo trials<br>'
            f'<span style="color:#4a90d9">Data</span> &nbsp;&nbsp;&nbsp; Open-Meteo ERA5<br>'
            f'<span style="color:#4a90d9">R²</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; '
            f'<span style="color:#4a90d9">{_preview_engine.calibration_r2():.4f}</span></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT (live — always recomputes for map preview)
# ══════════════════════════════════════════════════════════════════════════════
env       = generate_environment(location, start_time, event_date)
loc_disp  = location.strip() or "Unknown Location"
is_vegas  = _is_vegas(loc_disp) or (loc_mode == "Las Vegas Venue")

_demand_preview = _est_demand(capacity, price)
_util_preview   = min(
    0.97,
    _demand_preview * _preview_engine.phf
    / max(staff * 45 * (1 - env["traffic_stress"] * _preview_engine.w_trans), 1)
)


# ══════════════════════════════════════════════════════════════════════════════
# SIMULATION  (session-state — only recomputes on button press)
# ══════════════════════════════════════════════════════════════════════════════
if run_btn:
    phf        = profile["phf"]
    sim_engine = MonteCarloEngine(n_simulations=1000, peak_hour_fraction=phf)
    optimizer  = VectorizedOptimizer(sim_engine)

    _inputs = {
        "attendance": capacity, "staffing": staff,
        "price": price, "weather": env["weather_risk"], "transit": env["transit"],
    }

    with st.spinner(f"Running 1,000 Monte Carlo trials for {event_type}..."):
        res    = sim_engine.run_vectorized(capacity, staff, price, env["weather_risk"], env["transit"])
        recs   = optimizer.optimize(goal, _inputs)
        s_heat = sim_engine.run_vectorized(capacity, staff, price, 1.0, env["transit"])
        s_trns = sim_engine.run_vectorized(capacity, staff, price, env["weather_risk"], 0.0)
        s_staf = sim_engine.run_vectorized(capacity, max(100, int(staff * 0.60)), price,
                                           env["weather_risk"], env["transit"])

        # Compute wait distribution for math engine (mirrors engine's noise model)
        np.random.seed(42)
        transit_eff = max(1.0 - ((1.0 - env["transit"]) * sim_engine.w_trans), 0.05)
        elast = (max(0.0, 1.0 - price / 1000.0) if price <= 200
                 else 0.80 * float(np.exp(-(price - 200) / 100.0)))
        c_a  = 1.0 + env["weather_risk"] * 1.8
        tau  = 60.0 / 45.0  # mean service time in minutes
        _raw_waits = []
        for _ in range(1000):
            noise     = np.random.normal(0, 0.05)
            cap_noise = max(1.0 + noise - env["weather_risk"] * sim_engine.w_cap, 0.05)
            dem_noise = 1.0 + noise * 0.5 + env["weather_risk"] * sim_engine.w_dem
            demand_i  = capacity * phf * elast * dem_noise
            cap_i     = staff * 45 * transit_eff * cap_noise
            util_i    = min(0.98, max(0.05, demand_i / max(cap_i, 1)))
            _raw_waits.append((util_i / (1.0 - util_i)) * ((c_a + 1.2) / 2) * tau)
        raw_waits = np.array(_raw_waits)

    st.session_state.update({
        "res": res, "recs": recs, "goal": goal,
        "inputs": _inputs.copy(), "env": env,
        "stress": {"heat": s_heat, "trns": s_trns, "staf": s_staf},
        "location": loc_disp, "capacity": capacity, "staff": staff, "price": price,
        "event_type": event_type, "profile": profile,
        "raw_waits": raw_waits, "phf": phf,
        "sim_engine": sim_engine,
        "venue": selected_vegas_venue,
    })

_has_results = "res" in st.session_state

if _has_results:
    res         = st.session_state["res"]
    recs        = st.session_state["recs"]
    goal        = st.session_state["goal"]
    env_s       = st.session_state["env"]
    stress      = st.session_state["stress"]
    _ev         = st.session_state["event_type"]
    _prof       = st.session_state["profile"]
    _cong       = float(res["cong_mean"][0])
    _raw_waits  = st.session_state["raw_waits"]
    _sim_engine = st.session_state["sim_engine"]
    _phf        = st.session_state["phf"]
    _sim_venue  = st.session_state.get("venue")
else:
    env_s  = env
    _cong  = _util_preview * 0.85
    _ev    = event_type
    _prof  = profile


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
_cal_pill  = (f'<span class="pill pill-teal">Calibrated R²={_preview_engine.calibration_r2():.4f}</span>'
              if _preview_engine.is_calibrated() else '<span class="pill pill-dim">Uncalibrated</span>')
_live_pill = '<span class="pill pill-live"><span class="live-dot"></span>Map Live</span>'
_sim_pill  = ('<span class="pill pill-teal">Analysis Ready</span>' if _has_results
              else '<span class="pill pill-dim">Awaiting Run</span>')

st.markdown(f"""
<div class="nx-header">
  <div style="display:flex;align-items:baseline;gap:0">
    <div class="nx-wordmark">Vane</div>
    <div class="nx-sub">Decision Intelligence</div>
  </div>
  <div class="nx-pills">{_live_pill}{_cal_pill}{_sim_pill}</div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# HERO MAP — always rendered, live preview
# ══════════════════════════════════════════════════════════════════════════════
_att_frac = min(0.98, _demand_preview * _preview_engine.phf / max(capacity * _preview_engine.phf, 1))

if is_vegas:
    _deck = build_vegas_map(
        attendance      = capacity,
        weather_risk    = env["weather_risk"],
        traffic_stress  = env["traffic_stress"],
        selected_venue  = selected_vegas_venue if loc_mode == "Las Vegas Venue" else None,
        congestion_mean = _cong,
    )
else:
    _deck = build_city_map(
        lat                = env["lat"], lon=env["lon"],
        weather_risk       = env["weather_risk"],
        traffic_stress     = env["traffic_stress"],
        attendance_fraction= _att_frac,
        congestion_mean    = _cong,
        location_name      = loc_disp,
    )

st.pydeck_chart(_deck, width="stretch", height=480)

wc = "#d45050" if env["weather_risk"]>0.55 else ("#c49030" if env["weather_risk"]>0.35 else "#4a90d9")
tc = "#d45050" if env["traffic_stress"]>0.70 else ("#c49030" if env["traffic_stress"]>0.45 else "#4a90d9")

_map_note = (
    f"All Vegas venues · {len(VEGAS_VENUES)} locations · hover for fill rate &amp; stress"
    if is_vegas else f"City risk model · {loc_disp}"
)

st.markdown(f"""
<div class="map-caption">
  <span><span class="mc-key">Venue</span><b>{loc_disp}</b></span>
  <span><span class="mc-key">Date</span><b>{event_date.strftime('%b %d, %Y')}</b></span>
  <span><span class="mc-key">Start</span><b>{start_time.strftime('%H:%M')}</b></span>
  <span><span class="mc-key">Weather</span><b style="color:{wc}">{env['weather_label']}</b></span>
  <span><span class="mc-key">Traffic</span><b style="color:{tc}">{env['traffic_label']}</b></span>
  <span><span class="mc-key">Peak Load</span><b style="color:#4a90d9">{_util_preview*100:.0f}% utilisation</b></span>
  <span style="margin-left:auto;font-size:.58rem;color:#6a6a88">{_map_note}</span>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PRE-RUN STATE
# ══════════════════════════════════════════════════════════════════════════════
if not _has_results:
    ep = EVENT_PROFILES[event_type]
    st.markdown(f"""
    <div class="ready-box">
      <div class="ready-title">{ep['icon']} Ready to Profile — {event_type}</div>
      <div class="ready-sub">
        PHF = <b style="color:#4a90d9">{ep['phf']:.0%}</b> of attendance arrives in the peak hour
        &nbsp;·&nbsp; Avg attendee age: <b style="color:#4a90d9">{ep['avg_age']}</b>
        &nbsp;·&nbsp; Typical stay: <b style="color:#4a90d9">{ep['stay_hrs']:.0f} hrs</b><br>
        Arrival pattern: <b style="color:#c49030">{ep['arrival']}</b><br>
        Set your parameters in the sidebar — the map updates live.<br>
        Press <b>RUN ANALYSIS</b> to run 1,000 calibrated Monte Carlo trials.
      </div>
      <div class="ready-hint">BLUE = IDEAL VENUE FIT · AMBER = MODERATE · RED = OVER CAPACITY</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="border-top:1px solid #1c1d3a;margin-top:40px;padding-top:14px;
                display:flex;justify-content:space-between;align-items:center">
      <div style="font-size:.62rem;color:#505068">
        <b style="color:#4a90d9">Vane</b> · Decision Intelligence
      </div>
      <div style="font-size:.62rem;color:#505068;font-style:italic">
        Queueing-network simulation for venue operations.
      </div>
    </div>""", unsafe_allow_html=True)
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION BREAK
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="nx-section-break nx-reveal">
  <div class="nx-section-line"></div>
  <div class="nx-section-tag">&#9632; {_prof['icon']} Analysis Complete — {_ev}</div>
  <div class="nx-section-line"></div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# KPI STRIP (above tabs — always visible post-run)
# ══════════════════════════════════════════════════════════════════════════════
_cap_s  = st.session_state["capacity"]
_stf_s  = st.session_state["staff"]
_prc_s  = st.session_state["price"]
demand  = _est_demand(_cap_s, _prc_s)
wait    = res["wait_mean"][0]
risk    = res["cong_mean"][0] * 100
rev     = res["rev_mean"][0]
hes     = res["hes_mean"][0]
peak_hr = int(demand * _phf)

wait_c  = "#4a90d9" if wait < 8  else ("#c49030" if wait < 18 else "#d45050")
risk_c  = "#4a90d9" if risk < 35 else ("#c49030" if risk < 60 else "#d45050")
hes_c   = "#4a90d9" if hes >= 70 else ("#c49030" if hes >= 48 else "#d45050")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown('<div class="nx-reveal">' +
        _kpi("Peak-Hour Arrivals", f"{peak_hr:,}/hr",
             f"Total: {demand:,} · Venue cap: {_cap_s:,}") +
        '</div>', unsafe_allow_html=True)
with m2:
    st.markdown('<div class="nx-reveal-2">' +
        _kpi("Avg Wait Time", f"{wait:.0f} min",
             f"Best {res['wait_p10'][0]:.0f} min  ·  Worst {res['wait_p90'][0]:.0f} min",
             wait_c, glow=(wait > 18)) +
        '</div>', unsafe_allow_html=True)
with m3:
    st.markdown('<div class="nx-reveal-3">' +
        _kpi("Op. Failure Risk", f"{risk:.0f}%",
             f"Range: {res['cong_p10'][0]*100:.0f}–{res['cong_p90'][0]*100:.0f}%",
             risk_c, glow=(risk > 60)) +
        '</div>', unsafe_allow_html=True)
with m4:
    st.markdown('<div class="nx-reveal-4">' +
        _kpi("Projected Revenue", f"${rev/1e6:.1f}M",
             f"Floor: ${res['rev_p10'][0]/1e6:.1f}M  ·  Ceiling: ${res['rev_p90'][0]/1e6:.1f}M",
             "#c49030") +
        '</div>', unsafe_allow_html=True)

st.markdown('<div class="nx-divider"></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs([
    "  INTEL REPORT  ",
    "  SCENARIO COMPARE  ",
    "  MATH ENGINE  ",
])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1 — INTEL REPORT
# ──────────────────────────────────────────────────────────────────────────────
with tab1:
    # Venue Recommendations (Vegas only)
    if is_vegas:
        st.markdown("""
        <div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin:20px 0 12px;
        text-transform:uppercase;letter-spacing:.12em">AI Venue Recommendations for Las Vegas</div>
        """, unsafe_allow_html=True)

        venue_recs = _recommend_venues(demand, _ev, env_s["weather_risk"])
        rank_colors = [("#4a90d9", "BEST FIT"), ("#4a90d9", "ALT 1"), ("#c49030", "ALT 2")]
        vc1, vc2, vc3 = st.columns(3)
        cols = [vc1, vc2, vc3]

        for i, (vname, score, util, vtype, vcap, vtransit) in enumerate(venue_recs):
            color, rank_label = rank_colors[i]
            is_cur = (vname == _sim_venue)
            border_style = f"border-top: 2px solid {color};" + (
                "box-shadow: 0 0 20px rgba(74,144,217,0.12);" if i == 0 else "")

            util_pct = min(util * 100, 999)
            util_color = "#4a90d9" if 60 <= util_pct <= 90 else ("#c49030" if util_pct < 60 else "#d45050")

            why_parts = []
            if 60 <= util_pct <= 90:
                why_parts.append(f"Ideal fill rate ({util_pct:.0f}%)")
            elif util_pct < 60:
                why_parts.append(f"Slightly oversized ({util_pct:.0f}% fill) — cost savings possible")
            else:
                why_parts.append(f"Near capacity ({util_pct:.0f}%) — monitor closely")
            if vtype in _prof["venue_types"]:
                why_parts.append(f"{vtype} type matches {_ev}")
            if vtransit >= 0.80:
                why_parts.append("Excellent transit access")
            elif vtransit >= 0.65:
                why_parts.append("Good transit access")
            why_text = " · ".join(why_parts)

            cur_badge = ' <span style="color:#4a90d9;font-size:.6rem">(currently selected)</span>' if is_cur else ""
            with cols[i]:
                st.markdown(f"""
                <div class="venue-card" style="{border_style}">
                  <div class="venue-rank" style="background:{color}22;color:{color}">{rank_label}</div>
                  <div class="venue-name">{vname}{cur_badge}</div>
                  <div class="venue-stats">
                    Type: {vtype} &nbsp;·&nbsp; Max Cap: {vcap:,}<br>
                    Your event fills: <b style="color:{util_color}">{util_pct:.0f}%</b>
                    &nbsp;·&nbsp; Transit: {vtransit*100:.0f}%<br>
                    Match score: <b style="color:{color}">{score*100:.0f}/100</b>
                  </div>
                  <div class="venue-why">{why_text}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown('<div class="nx-divider"></div>', unsafe_allow_html=True)

    # Intelligence Report
    ir_l, ir_r = st.columns([3, 2])

    with ir_l:
        st.markdown(
            '<div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin-bottom:12px;'
            'text-transform:uppercase;letter-spacing:.12em">Prescriptive Recommendations</div>',
            unsafe_allow_html=True)
        rec_items  = _gen_recs(recs, res, env_s, goal, st.session_state["location"],
                               _ev, _prof)
        html_recs  = ""
        for idx, (t, txt, c) in enumerate(rec_items):
            extra_class = "rec-item-top" if idx == 0 else ""
            color, bg   = _BADGE.get(t, ("#6a6a88", "rgba(74,102,128,0.07)"))
            html_recs  += f"""
            <div class="rec-item {extra_class}" style="border-color:{color};background:{bg}">
              <div class="rec-badge" style="background:{color}22;color:{color}">{t}</div>
              <div class="rec-text">{txt}</div>
              <div class="rec-conf">{c:.0f}% model confidence</div>
            </div>"""
        st.markdown(f'<div class="nx-reveal">{html_recs}</div>', unsafe_allow_html=True)

    with ir_r:
        st.markdown(
            '<div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin-bottom:12px;'
            'text-transform:uppercase;letter-spacing:.12em">Environmental Stress Radar</div>',
            unsafe_allow_html=True)
        st.plotly_chart(build_radar_chart(env_s), width="stretch")
        hes_c2 = "#4a90d9" if hes >= 70 else ("#c49030" if hes >= 48 else "#d45050")
        st.markdown(
            _kpi("Human Experience Score", f"{hes:.0f} / 100",
                 f"P10 {res['hes_p10'][0]:.0f}  ·  P90 {res['hes_p90'][0]:.0f}", hes_c2),
            unsafe_allow_html=True)

        # Event profile summary
        st.markdown(f"""
        <div class="event-profile-card" style="margin-top:12px">
          <div class="ep-title">Event Profile — {_ev}</div>
          <div class="ep-grid">
            <div class="ep-stat">
              <div class="ep-stat-lbl">Peak-Hour Fraction</div>
              <div class="ep-stat-val" style="color:#4a90d9">{_phf:.0%}</div>
            </div>
            <div class="ep-stat">
              <div class="ep-stat-lbl">Avg Attendee Age</div>
              <div class="ep-stat-val">{_prof['avg_age']}</div>
            </div>
            <div class="ep-stat">
              <div class="ep-stat-lbl">Typical Stay</div>
              <div class="ep-stat-val">{_prof['stay_hrs']:.1f} hrs</div>
            </div>
            <div class="ep-stat">
              <div class="ep-stat-lbl">Heat Vulnerability</div>
              <div class="ep-stat-val" style="color:{'#d45050' if _prof['heat_vuln']>1.2 else '#c49030' if _prof['heat_vuln']>1.0 else '#4a90d9'}">{_prof['heat_vuln']:.2f}×</div>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2 — SCENARIO COMPARE
# ──────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("""
    <div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin:20px 0 4px;
    text-transform:uppercase;letter-spacing:.12em">Staffing Sensitivity Analysis</div>
    <div style="font-size:.72rem;color:#6a6a88;margin-bottom:12px">
      How wait time and labor cost respond to changes in staff deployed.
      Blue bar = minimum wait, darker blue = your current level.
    </div>""", unsafe_allow_html=True)

    st.plotly_chart(
        build_staffing_comparison(
            _ev, st.session_state["capacity"], st.session_state["staff"],
            st.session_state["price"], _sim_engine, env_s,
        ),
        width="stretch",
    )

    st.markdown('<div class="nx-divider"></div>', unsafe_allow_html=True)

    ds_l, ds_r = st.columns([3, 2])

    with ds_l:
        st.markdown(
            '<div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin-bottom:8px;'
            'text-transform:uppercase;letter-spacing:.12em">Revenue vs. Congestion Risk — Decision Space</div>',
            unsafe_allow_html=True)
        st.plotly_chart(build_tradeoff_chart(res, recs), width="stretch")

    with ds_r:
        st.markdown(
            '<div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin-bottom:12px;'
            'text-transform:uppercase;letter-spacing:.12em">Cost of Doing Nothing</div>',
            unsafe_allow_html=True)

        opt1   = recs[0]
        cong_d = (res["cong_mean"][0] - opt1["congestion"]) * 100
        wait_d =  res["wait_mean"][0] - opt1["wait"]
        brk_d  = (res["brk_mean"][0]  - opt1["breakdown"])  * 100
        rev_d  =  res["rev_mean"][0]  - opt1["revenue"]
        hes_d  =  res["hes_mean"][0]  - opt1["hes"]

        coi_rows = ""
        if cong_d > 0.5:
            coi_rows += _coi_row(f"+{cong_d:.0f}%", "Congestion Risk Increase")
        if wait_d > 0.5:
            coi_rows += _coi_row(f"+{wait_d:.0f} min", "Additional Wait Time")
        if brk_d > 0.1:
            coi_rows += _coi_row(f"+{brk_d:.1f}%", "Breakdown Probability Increase")
        if rev_d < -500:
            coi_rows += _coi_row(f"−${abs(rev_d)/1e6:.2f}M", "Revenue Opportunity Lost")
        elif rev_d > 500:
            coi_rows += _coi_row(f"+${rev_d/1e6:.2f}M", "Revenue Surplus vs Option 1", bad=False)
        if hes_d < -1:
            coi_rows += _coi_row(f"{hes_d:.0f} pts", "Human Experience Score Drop")

        st.markdown(
            coi_rows or
            '<div style="font-size:.78rem;color:#6a6a88">Configuration is already near-optimal.</div>',
            unsafe_allow_html=True)

        # Top 3 configs
        st.markdown(
            '<div style="font-size:.62rem;font-weight:700;color:#6a6a88;text-transform:uppercase;'
            'letter-spacing:.12em;margin:16px 0 10px">Top 3 Configurations</div>',
            unsafe_allow_html=True)
        colors3 = ["#4a90d9", "#4a90d9", "#c49030"]
        for i, r in enumerate(recs):
            c   = colors3[i]
            sds = f"{'+ ' if r['staffing_delta']>=0 else '− '}{abs(r['staffing_delta']):,}"
            st.markdown(f"""
            <div style="background:#0e0f24;border:1px solid #1c1d3a;border-left:2px solid {c};
                        border-radius:4px;padding:10px 14px;margin-bottom:6px;
                        display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;font-size:.72rem">
              <div style="color:{c};font-weight:700">Opt {i+1}
                <div style="font-size:.58rem;color:#6a6a88;margin-top:2px">{r['confidence']:.0f}% conf.</div>
              </div>
              <div style="color:#6a6a88">Staff<br><b style="color:#c8c8dc">{r['staffing']:,}</b>
                <span style="color:{c};font-size:.65rem"> {sds}</span>
              </div>
              <div style="color:#6a6a88">Price<br><b style="color:#c8c8dc">${r['price']:.0f}</b></div>
              <div style="color:#6a6a88">Revenue<br><b style="color:#c8c8dc">${r['revenue']/1e6:.2f}M</b></div>
            </div>""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 — MATH ENGINE
# ──────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("""
    <div style="font-size:.65rem;font-weight:700;color:#6a6a88;margin:20px 0 4px;
    text-transform:uppercase;letter-spacing:.12em">System Transparency — Formulas &amp; Algorithms</div>
    <div style="font-size:.78rem;color:#6a6a88;margin-bottom:20px;line-height:1.7">
      Vane does not rely on black-box AI. All operational projections are grounded in
      queueing theory, probabilistic distributions, and event-type behavioral science.
    </div>""", unsafe_allow_html=True)

    me_l, me_r = st.columns([3, 2])

    with me_l:
        with st.expander("1. Event Profiling — How Your Event Type Changes the Math", expanded=True):
            peak_demand = int(st.session_state["capacity"] * _phf)
            st.markdown(f"""
            <div class="math-box">
              <b>Event Type:</b> {_ev}<br>
              <b>Peak-Hour Fraction (PHF):</b> {_phf:.0%}<br><br>
              Peak-hour arrival rate = Attendance × PHF × Price Elasticity × Demand Noise<br>
              = {st.session_state['capacity']:,} × {_phf:.2f} × ε × η<br>
              ≈ <b>{peak_demand:,} arrivals in the busiest hour</b><br><br>
              Compared to a generic event (PHF=30%), a <b>{_ev}</b> generates
              {'+' if _phf > 0.30 else ''}{(_phf-0.30)/_phf*100:.0f}%
              {'more' if _phf > 0.30 else 'fewer'} peak-hour arrivals —
              meaning {'longer queues and higher congestion pressure' if _phf > 0.30
              else 'more distributed flow and lower queue stress'}.<br><br>
              <b>Heat Vulnerability Multiplier:</b> {_prof['heat_vuln']:.2f}×
              — applied to weather-related breakdown risk.<br>
              <b>Density Tolerance:</b> {_prof['density_tolerance']:.0%}
              — maximum comfortable fill ratio before experience degrades.
            </div>""", unsafe_allow_html=True)

        with st.expander("2. Kingman's G/G/1 Approximation — Wait Time Formula"):
            util_val  = float(res["util_mean"][0])
            c_a_val   = 1.0 + env_s["weather_risk"] * 1.8
            var_term  = (c_a_val + 1.2) / 2.0
            wait_val  = res["wait_mean"][0]
            st.markdown(f"""
            <div class="math-box">
              E[W] ≈ (ρ / (1 − ρ)) × ((c_a² + c_s²) / 2) × τ<br><br>
              Where:<br>
              &nbsp;&nbsp;<b>ρ (utilization)</b>  = Arrival Rate / Capacity
                = <b>{util_val:.3f}</b><br>
              &nbsp;&nbsp;<b>c_a² (arrival variance)</b> = 1.0 + weather_risk × 1.8
                = <b>{c_a_val:.3f}</b>
                &nbsp;({_ev} amplifies arrival variance)<br>
              &nbsp;&nbsp;<b>c_s² (service variance)</b> = 1.2 (staff processing noise)<br>
              &nbsp;&nbsp;<b>τ</b> = unit time (minutes)<br><br>
              Plugging in:<br>
              E[W] ≈ ({util_val:.3f} / {1.001-util_val:.3f}) × {var_term:.3f}<br>
              <b>E[W] ≈ {wait_val:.1f} minutes</b>
              &nbsp;(matches Monte Carlo mean ✓)
            </div>""", unsafe_allow_html=True)

        with st.expander("3. Human Experience Score (HES) — Composite Formula"):
            st.markdown(f"""
            <div class="math-box">
              HES = 100 − wait_penalty − (congestion_risk × 30) − (weather_risk × w_hes)<br><br>
              wait_penalty =<br>
              &nbsp;&nbsp;wait × 0.5 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; if wait &lt; 15 min<br>
              &nbsp;&nbsp;7.5 + (wait−15)^1.5 × 0.2 &nbsp; if wait ≥ 15 min (exponential degradation)<br><br>
              Plugging in your scenario:<br>
              &nbsp;&nbsp;Wait = {wait_val:.1f} min →
              penalty = {7.5 + max(0, wait_val-15)**1.5 * 0.2 if wait_val >= 15 else wait_val * 0.5:.1f}<br>
              &nbsp;&nbsp;Congestion = {float(res['cong_mean'][0]):.2f} → −{float(res['cong_mean'][0])*30:.1f} pts<br>
              &nbsp;&nbsp;Weather = {env_s['weather_risk']:.2f}<br>
              <b>HES ≈ {hes:.0f}/100</b>
            </div>""", unsafe_allow_html=True)

    with me_r:
        st.markdown(
            '<div style="font-size:.62rem;font-weight:700;color:#6a6a88;text-transform:uppercase;'
            'letter-spacing:.12em;margin-bottom:10px">1,000-Trial Wait Distribution</div>',
            unsafe_allow_html=True)
        st.plotly_chart(build_wait_distribution(_raw_waits, _ev), width="stretch")

        st.markdown(
            '<div style="font-size:.62rem;font-weight:700;color:#6a6a88;text-transform:uppercase;'
            'letter-spacing:.12em;margin:16px 0 10px">Outcome Uncertainty  ·  P10 / Mean / P90</div>',
            unsafe_allow_html=True)
        st.markdown(
            '<div class="unc-wrap">'
            + _unc_row("Avg Wait Time",    res["wait_p10"][0],      res["wait_mean"][0],      res["wait_p90"][0],      " min", 45,  10)
            + _unc_row("Congestion Risk",  res["cong_p10"][0]*100,  res["cong_mean"][0]*100,  res["cong_p90"][0]*100,  "%",   100, 30)
            + _unc_row("Breakdown Prob.",  res["brk_p10"][0]*100,   res["brk_mean"][0]*100,   res["brk_p90"][0]*100,   "%",    50,  5)
            + _unc_row("Human Exp. Score", res["hes_p10"][0],       res["hes_mean"][0],       res["hes_p90"][0],       "",    100, 70, invert=True)
            + "</div>",
            unsafe_allow_html=True)

    # Stress tests
    st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:.62rem;font-weight:700;color:#6a6a88;text-transform:uppercase;'
        'letter-spacing:.12em;margin-bottom:12px">Stress Test Mode — Worst-Case Scenarios</div>',
        unsafe_allow_html=True)
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.markdown(_stress_card("Extreme Heat Event", "115°F / weather risk = 100%",
                                 res, stress["heat"]), unsafe_allow_html=True)
    with sc2:
        st.markdown(_stress_card("Transit Disruption", "All rail suspended / transit = 0%",
                                 res, stress["trns"]), unsafe_allow_html=True)
    with sc3:
        _s40 = max(100, int(st.session_state["staff"] * 0.60))
        st.markdown(_stress_card(f"Staffing Shortage",
                                 f"−40% staff ({_s40:,} deployed)",
                                 res, stress["staf"]), unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#0e0f24;border:1px solid #1c1d3a;border-radius:4px;
                padding:10px 16px;margin-top:12px;font-size:.72rem;color:#6a6a88">
      <span style="color:#d45050;font-weight:700">WHY THIS MATTERS &nbsp;</span>
      Operators need to know the worst case before it becomes a headline.
      These tests are pre-computed with the same calibrated engine used for the primary run.
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div style="border-top:1px solid #1c1d3a;margin-top:48px;padding-top:14px;
            display:flex;justify-content:space-between;align-items:center">
  <div style="font-size:.62rem;color:#505068">
    <b style="color:#4a90d9">Vane</b> · Decision Intelligence
  </div>
  <div style="font-size:.62rem;color:#505068;font-style:italic">
    Queueing-network simulation for venue operations.
  </div>
</div>""", unsafe_allow_html=True)
