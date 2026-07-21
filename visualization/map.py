"""
map.py — PyDeck 3D column maps for Vane.
  build_vegas_map()   — All major Las Vegas venues (city-wide view)
  build_f1_map()      — Las Vegas F1 Strip circuit (12 key locations)
  build_city_map()    — Generic city crown for non-Vegas locations
"""
import math
import pydeck as pdk

_CARTO_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"

_TOOLTIP_STYLE = {
    "background"   : "#08091a",
    "color"        : "#4a90d9",
    "font-family"  : "Computer Modern Serif, Georgia, serif",
    "font-size"    : "12px",
    "padding"      : "8px 12px",
    "border"       : "1px solid #1c1d3a",
    "border-radius": "4px",
}


def _risk_color(risk: float) -> list:
    """Blue (low) → Amber (medium) → Red (high). Returns [R, G, B, A]."""
    risk = max(0.0, min(1.0, risk))
    if risk < 0.5:
        # Clean Blue #4a90d9 → Amber #c49030
        t = risk * 2
        r = int(74 + t * 122)    # 74 → 196
        g = int(144 - t * 0)     # 144 → 144
        b = int(217 - t * 169)   # 217 → 48
    else:
        # Amber #c49030 → Red #d45050
        t = (risk - 0.5) * 2
        r = int(196 + t * 16)    # 196 → 212
        g = int(144 - t * 64)    # 144 → 80
        b = int(48 + t * 32)     # 48 → 80
    return [r, g, b, 200]


# ── All major Las Vegas venues ───────────────────────────────────────────────
VEGAS_VENUES = {
    "Allegiant Stadium"           : {"lat": 36.0909, "lon": -115.1833, "max_cap": 65000,  "type": "Stadium",  "transit": 0.70, "outdoor_factor": 0.10},
    "T-Mobile Arena"              : {"lat": 36.1028, "lon": -115.1781, "max_cap": 20000,  "type": "Arena",    "transit": 0.85, "outdoor_factor": 0.00},
    "MSG Sphere"                  : {"lat": 36.1212, "lon": -115.1617, "max_cap": 20000,  "type": "Arena",    "transit": 0.70, "outdoor_factor": 0.00},
    "Las Vegas Convention Center" : {"lat": 36.1339, "lon": -115.1519, "max_cap": 150000, "type": "Expo",     "transit": 0.80, "outdoor_factor": 0.00},
    "Las Vegas Festival Grounds"  : {"lat": 36.1425, "lon": -115.1614, "max_cap": 85000,  "type": "Outdoor",  "transit": 0.60, "outdoor_factor": 1.00},
    "Thomas & Mack Center"        : {"lat": 36.1016, "lon": -115.1399, "max_cap": 19000,  "type": "Arena",    "transit": 0.55, "outdoor_factor": 0.00},
    "MGM Grand Garden Arena"      : {"lat": 36.1017, "lon": -115.1700, "max_cap": 16800,  "type": "Arena",    "transit": 0.82, "outdoor_factor": 0.00},
    "Mandalay Bay Events Center"  : {"lat": 36.0901, "lon": -115.1748, "max_cap": 12000,  "type": "Arena",    "transit": 0.65, "outdoor_factor": 0.00},
    "Caesars Palace Colosseum"    : {"lat": 36.1162, "lon": -115.1745, "max_cap": 4300,   "type": "Theater",  "transit": 0.88, "outdoor_factor": 0.00},
    "Resorts World Amphitheatre"  : {"lat": 36.1380, "lon": -115.1529, "max_cap": 5000,   "type": "Outdoor",  "transit": 0.75, "outdoor_factor": 0.90},
    "Las Vegas Motor Speedway"    : {"lat": 36.2720, "lon": -115.0146, "max_cap": 180000, "type": "Speedway", "transit": 0.30, "outdoor_factor": 1.00},
    "Michelob Ultra Arena"        : {"lat": 36.1020, "lon": -115.1720, "max_cap": 20000,  "type": "Arena",    "transit": 0.80, "outdoor_factor": 0.00},
}


def build_vegas_map(
    attendance: int,
    weather_risk: float,
    traffic_stress: float,
    selected_venue: str = None,
    congestion_mean: float = 0.5,
) -> pdk.Deck:
    """
    Full Las Vegas map showing all major venues as 3D columns.
    Color = fit-risk blend: blue = ideal capacity match, amber = moderate, red = over/under.
    Selected venue is highlighted in blue and rendered taller.
    Hover to see capacity, fill rate, and stress index.
    """
    rows = []
    for vname, v in VEGAS_VENUES.items():
        utilization = attendance / max(v["max_cap"], 1)

        # Capacity fit risk — optimal range is 60–90% utilization
        if utilization > 1.0:
            fit_risk = min(1.0, 0.55 + (utilization - 1.0) * 1.8)
        elif utilization > 0.90:
            fit_risk = 0.40 + (utilization - 0.90) * 1.5
        elif utilization > 0.60:
            fit_risk = 0.05 + (utilization - 0.60) / 0.30 * 0.20
        elif utilization > 0.30:
            fit_risk = 0.15
        else:
            fit_risk = max(0.05, 0.28 - utilization * 0.5)

        local_risk = (
            fit_risk                                * 0.50
            + weather_risk * v["outdoor_factor"]    * 0.25
            + (1.0 - v["transit"]) * traffic_stress * 0.25
        )
        local_risk = min(1.0, max(0.0, local_risk))

        is_selected = (vname == selected_venue)
        radius      = 160 if is_selected else 95
        col_height  = 40 + local_risk * 340
        if is_selected:
            col_height = max(col_height * 1.8, 220)
            color = [74, 144, 217, 230]   # clean blue for selected venue
        else:
            color = _risk_color(local_risk)

        rows.append({
            "position"   : [v["lon"], v["lat"]],
            "name"       : vname,
            "capacity"   : f"{v['max_cap']:,}",
            "utilization": f"{min(utilization * 100, 999):.0f}%",
            "type"       : v["type"],
            "risk_pct"   : round(local_risk * 100, 1),
            "elevation"  : col_height,
            "color"      : color,
            "radius"     : radius,
        })

    layer = pdk.Layer(
        "ColumnLayer",
        data=rows,
        get_position="position",
        get_elevation="elevation",
        elevation_scale=1,
        get_radius="radius",
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
        extruded=True,
    )
    view = pdk.ViewState(latitude=36.1300, longitude=-115.1400, zoom=10.8, pitch=48, bearing=-8)
    return pdk.Deck(
        layers=[layer],
        initial_view_state=view,
        map_style=_CARTO_DARK,
        tooltip={
            "html": (
                "<b>{name}</b><br/>"
                "Type: {type} &nbsp;·&nbsp; Max Capacity: {capacity}<br/>"
                "Your event fills: <b>{utilization}</b><br/>"
                "Stress index: <b>{risk_pct}%</b>"
            ),
            "style": _TOOLTIP_STYLE,
        },
    )


# ── 12 key locations along the Las Vegas Grand Prix circuit ──────────────────
_F1_CIRCUIT = [
    {"name": "Start/Finish — Koval Lane",  "lat": 36.1024, "lon": -115.1702, "outdoor": 1.00, "transit": 0.65},
    {"name": "Turn 1 — Sands Ave",         "lat": 36.1106, "lon": -115.1704, "outdoor": 1.00, "transit": 0.72},
    {"name": "Wynn Chicane",               "lat": 36.1272, "lon": -115.1684, "outdoor": 0.90, "transit": 0.78},
    {"name": "MSG Sphere — Paddock",        "lat": 36.1303, "lon": -115.1617, "outdoor": 0.75, "transit": 0.70},
    {"name": "Strip — Flamingo Rd",         "lat": 36.1162, "lon": -115.1726, "outdoor": 0.95, "transit": 0.80},
    {"name": "Caesars Palace Complex",      "lat": 36.1162, "lon": -115.1745, "outdoor": 0.80, "transit": 0.85},
    {"name": "Bellagio Fountain Corner",    "lat": 36.1126, "lon": -115.1767, "outdoor": 0.85, "transit": 0.88},
    {"name": "MGM Grand Gate",              "lat": 36.1022, "lon": -115.1707, "outdoor": 0.70, "transit": 0.82},
    {"name": "Mandalay Bay Hairpin",        "lat": 36.0906, "lon": -115.1721, "outdoor": 0.95, "transit": 0.60},
    {"name": "Tropicana Interchange",       "lat": 36.0989, "lon": -115.1716, "outdoor": 0.90, "transit": 0.74},
    {"name": "Park MGM Straight",           "lat": 36.1027, "lon": -115.1734, "outdoor": 1.00, "transit": 0.76},
    {"name": "Harmon Ave Kink",             "lat": 36.1079, "lon": -115.1723, "outdoor": 1.00, "transit": 0.71},
]


def build_f1_map(
    weather_risk: float,
    traffic_stress: float,
    attendance_fraction: float,
    congestion_mean: float,
) -> pdk.Deck:
    """3D column map of the F1 Las Vegas Strip circuit."""
    rows = []
    for loc in _F1_CIRCUIT:
        local_risk = (
            loc["outdoor"] * weather_risk      * 0.30
            + (1 - loc["transit"]) * traffic_stress * 0.30
            + attendance_fraction  * congestion_mean * 0.40
        )
        local_risk = min(max(local_risk, 0.0), 1.0)
        rows.append({
            "position" : [loc["lon"], loc["lat"]],
            "name"     : loc["name"],
            "risk_pct" : round(local_risk * 100, 1),
            "elevation": 60 + local_risk * 380,
            "color"    : _risk_color(local_risk),
        })
    layer = pdk.Layer(
        "ColumnLayer", data=rows,
        get_position="position", get_elevation="elevation",
        elevation_scale=1, radius=55, get_fill_color="color",
        pickable=True, auto_highlight=True, extruded=True,
    )
    view = pdk.ViewState(latitude=36.1100, longitude=-115.1720, zoom=14.2, pitch=52, bearing=-15)
    return pdk.Deck(
        layers=[layer], initial_view_state=view, map_style=_CARTO_DARK,
        tooltip={"html": "<b>{name}</b><br/>Risk: {risk_pct}%", "style": _TOOLTIP_STYLE},
    )


def build_city_map(
    lat: float, lon: float,
    weather_risk: float, traffic_stress: float,
    attendance_fraction: float, congestion_mean: float = None,
    location_name: str = "",
) -> pdk.Deck:
    """Generic city crown map for non-Vegas locations."""
    if congestion_mean is None:
        congestion_mean = attendance_fraction * 0.85

    R_inner, R_outer = 0.0018, 0.0054
    rows = []

    center_risk = min(1.0, attendance_fraction * 0.55 + congestion_mean * 0.45)
    rows.append({
        "position" : [lon, lat], "name": location_name or "Venue Center",
        "risk_pct" : round(center_risk * 100, 1),
        "elevation": 80 + center_risk * 460, "color": _risk_color(center_risk),
    })
    for i in range(8):
        angle = 2 * math.pi * i / 8
        dir_w = 0.65 + 0.35 * abs(math.cos(angle))
        dir_t = 0.65 + 0.35 * abs(math.sin(angle))
        risk  = min(1.0,
            weather_risk    * 0.30 * dir_w
            + traffic_stress  * 0.35 * dir_t
            + attendance_fraction * 0.35)
        rows.append({
            "position" : [lon + R_inner * math.sin(angle), lat + R_inner * math.cos(angle)],
            "name": f"Zone {i+1}", "risk_pct": round(risk * 100, 1),
            "elevation": 30 + risk * 300, "color": _risk_color(risk),
        })
    for i in range(12):
        angle = 2 * math.pi * i / 12
        risk  = min(1.0,
            weather_risk    * 0.35 * (0.5 + 0.5 * abs(math.cos(angle)))
            + traffic_stress  * 0.35 * (0.5 + 0.5 * abs(math.sin(angle)))
            + attendance_fraction * 0.30)
        rows.append({
            "position" : [lon + R_outer * math.sin(angle), lat + R_outer * math.cos(angle)],
            "name": f"Perimeter {i+1}", "risk_pct": round(risk * 100, 1),
            "elevation": 15 + risk * 140, "color": _risk_color(risk),
        })

    layer = pdk.Layer(
        "ColumnLayer", data=rows,
        get_position="position", get_elevation="elevation",
        elevation_scale=1, radius=60, get_fill_color="color",
        pickable=True, auto_highlight=True, extruded=True,
    )
    zoom = 14.0 if abs(lat) > 0.1 else 2.0
    view = pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom, pitch=52, bearing=10)
    return pdk.Deck(
        layers=[layer], initial_view_state=view, map_style=_CARTO_DARK,
        tooltip={"html": "<b>{name}</b><br/>Risk: {risk_pct}%", "style": _TOOLTIP_STYLE},
    )
