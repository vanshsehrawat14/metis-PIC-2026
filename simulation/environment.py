"""
Synthetic environment generator.
Derives weather risk, traffic stress, and parking from location text + time + date.
Location is hashed for consistency — "Miami" always returns higher heat risk than "Denver".
Known cities have hand-tuned base profiles; unknown locations fall back to the hash.
"""
import datetime
import hashlib

# Hand-tuned climate/density profiles for common venues (includes lat/lon for map)
_PROFILES = {
    "miami":            {"weather": 0.65, "heat": True,  "lat": 25.7617,  "lon": -80.1918},
    "miami beach":      {"weather": 0.68, "heat": True,  "lat": 25.7907,  "lon": -80.1300},
    "las vegas":                    {"weather": 0.48, "heat": True,  "lat": 36.1147,  "lon": -115.1728},
    "las vegas strip":              {"weather": 0.52, "heat": True,  "lat": 36.1147,  "lon": -115.1728},
    "f1 las vegas":                 {"weather": 0.52, "heat": True,  "lat": 36.1147,  "lon": -115.1728},
    "formula 1 vegas":              {"weather": 0.52, "heat": True,  "lat": 36.1147,  "lon": -115.1728},
    "allegiant stadium":            {"weather": 0.52, "heat": True,  "lat": 36.0909,  "lon": -115.1833},
    "t-mobile arena":               {"weather": 0.50, "heat": True,  "lat": 36.1028,  "lon": -115.1781},
    "msg sphere":                   {"weather": 0.50, "heat": True,  "lat": 36.1212,  "lon": -115.1617},
    "las vegas convention center":  {"weather": 0.50, "heat": True,  "lat": 36.1339,  "lon": -115.1519},
    "las vegas festival grounds":   {"weather": 0.52, "heat": True,  "lat": 36.1425,  "lon": -115.1614},
    "thomas & mack center":         {"weather": 0.50, "heat": True,  "lat": 36.1016,  "lon": -115.1399},
    "mgm grand garden arena":       {"weather": 0.50, "heat": True,  "lat": 36.1017,  "lon": -115.1700},
    "mandalay bay events center":   {"weather": 0.50, "heat": True,  "lat": 36.0901,  "lon": -115.1748},
    "caesars palace colosseum":     {"weather": 0.50, "heat": True,  "lat": 36.1162,  "lon": -115.1745},
    "resorts world amphitheatre":   {"weather": 0.50, "heat": True,  "lat": 36.1380,  "lon": -115.1529},
    "las vegas motor speedway":     {"weather": 0.48, "heat": True,  "lat": 36.2720,  "lon": -115.0146},
    "michelob ultra arena":         {"weather": 0.50, "heat": True,  "lat": 36.1020,  "lon": -115.1720},
    "phoenix":          {"weather": 0.58, "heat": True,  "lat": 33.4484,  "lon": -112.0740},
    "houston":          {"weather": 0.62, "heat": True,  "lat": 29.7604,  "lon": -95.3698},
    "dallas":           {"weather": 0.54, "heat": True,  "lat": 32.7767,  "lon": -96.7970},
    "atlanta":          {"weather": 0.52, "heat": True,  "lat": 33.7490,  "lon": -84.3880},
    "dubai":            {"weather": 0.75, "heat": True,  "lat": 25.2048,  "lon":  55.2708},
    "singapore":        {"weather": 0.68, "heat": True,  "lat":  1.3521,  "lon": 103.8198},
    "sydney":           {"weather": 0.42, "heat": True,  "lat": -33.8688, "lon": 151.2093},
    "new york":         {"weather": 0.40, "heat": False, "lat": 40.7128,  "lon": -74.0060},
    "new york city":    {"weather": 0.40, "heat": False, "lat": 40.7128,  "lon": -74.0060},
    "nyc":              {"weather": 0.40, "heat": False, "lat": 40.7128,  "lon": -74.0060},
    "chicago":          {"weather": 0.50, "heat": False, "lat": 41.8781,  "lon": -87.6298},
    "los angeles":      {"weather": 0.30, "heat": False, "lat": 34.0522,  "lon": -118.2437},
    "san francisco":    {"weather": 0.28, "heat": False, "lat": 37.7749,  "lon": -122.4194},
    "seattle":          {"weather": 0.60, "heat": False, "lat": 47.6062,  "lon": -122.3321},
    "denver":           {"weather": 0.44, "heat": False, "lat": 39.7392,  "lon": -104.9903},
    "london":           {"weather": 0.55, "heat": False, "lat": 51.5074,  "lon":  -0.1278},
    "london o2":        {"weather": 0.55, "heat": False, "lat": 51.5030,  "lon":   0.0031},
    "paris":            {"weather": 0.42, "heat": False, "lat": 48.8566,  "lon":   2.3522},
    "berlin":           {"weather": 0.44, "heat": False, "lat": 52.5200,  "lon":  13.4050},
    "tokyo":            {"weather": 0.45, "heat": False, "lat": 35.6762,  "lon": 139.6503},
    "toronto":          {"weather": 0.48, "heat": False, "lat": 43.6532,  "lon": -79.3832},
    "montreal":         {"weather": 0.50, "heat": False, "lat": 45.5017,  "lon": -73.5673},
    "barcelona":        {"weather": 0.38, "heat": False, "lat": 41.3851,  "lon":   2.1734},
    "rome":             {"weather": 0.40, "heat": False, "lat": 41.9028,  "lon":  12.4964},
    "mexico city":      {"weather": 0.45, "heat": False, "lat": 19.4326,  "lon": -99.1332},
    "sao paulo":        {"weather": 0.55, "heat": True,  "lat": -23.5505, "lon": -46.6333},
    "abu dhabi":        {"weather": 0.72, "heat": True,  "lat": 24.4539,  "lon":  54.3773},
    "monza":            {"weather": 0.38, "heat": False, "lat": 45.6156,  "lon":   9.2811},
    "silverstone":      {"weather": 0.60, "heat": False, "lat": 52.0786,  "lon":  -1.0169},
    "spa":              {"weather": 0.62, "heat": False, "lat": 50.4437,  "lon":   5.9710},
    "spa-francorchamps":{"weather": 0.62, "heat": False, "lat": 50.4437,  "lon":   5.9710},
    "suzuka":           {"weather": 0.48, "heat": False, "lat": 34.8431,  "lon": 136.5411},
    "monaco":           {"weather": 0.32, "heat": False, "lat": 43.7347,  "lon":   7.4206},
    "monte carlo":      {"weather": 0.32, "heat": False, "lat": 43.7347,  "lon":   7.4206},
    "austin":           {"weather": 0.45, "heat": True,  "lat": 30.1328,  "lon": -97.6411},
    "cota":             {"weather": 0.45, "heat": True,  "lat": 30.1328,  "lon": -97.6411},
    "bahrain":          {"weather": 0.70, "heat": True,  "lat": 26.0325,  "lon":  50.5106},
    "jeddah":           {"weather": 0.65, "heat": True,  "lat": 21.6411,  "lon":  39.1040},
    "miami gardens":    {"weather": 0.68, "heat": True,  "lat": 25.9580,  "lon": -80.2389},
    "imola":            {"weather": 0.40, "heat": False, "lat": 44.3439,  "lon":  11.7167},
    "baku":             {"weather": 0.35, "heat": False, "lat": 40.3725,  "lon":  49.8533},
}


def _hash_coords(key: str):
    """Generate deterministic pseudo-lat/lon from location string hash."""
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    lat = ((h % 1800) - 900) / 10.0   # -90 to 90
    lon = ((h // 1800 % 3600) - 1800) / 10.0  # -180 to 180
    return lat, lon


def generate_environment(
    location: str,
    start_time: datetime.time,
    event_date: datetime.date,
) -> dict:
    """
    Returns a dict of synthesized environmental factors:
      weather_risk   (0-1): probability of weather disruption
      traffic_stress (0-1): 0 = clear roads, 1 = gridlock
      transit        (0-1): engine input (inverse of traffic_stress)
      parking        (0-1): parking availability fraction
      lat, lon       : best-guess coordinates for map
      weather_label  : human-readable weather description
      traffic_label  : human-readable traffic description
    """
    key = location.lower().strip()

    # ── Base weather from profile or location hash ─────────────────────────────
    if key in _PROFILES:
        base_weather = _PROFILES[key]["weather"]
        heat_city    = _PROFILES[key]["heat"]
        lat          = _PROFILES[key]["lat"]
        lon          = _PROFILES[key]["lon"]
    else:
        loc_hash     = int(hashlib.md5(key.encode()).hexdigest(), 16) % 100
        base_weather = 0.20 + (loc_hash / 100.0) * 0.50
        heat_city    = loc_hash > 55
        lat, lon     = _hash_coords(key)

    # ── Season modifier (hemisphere-aware) ───────────────────────────────────
    month = event_date.month
    southern = lat < 0  # flip seasons for Southern Hemisphere
    summer_months = [12, 1, 2] if southern else [6, 7, 8]
    winter_months = [6, 7, 8] if southern else [12, 1, 2]

    if heat_city and month in summer_months:
        season_bump = 0.25   # summer in a hot city
    elif heat_city and month in winter_months:
        season_bump = 0.05   # mild winter in a hot city
    elif not heat_city and month in winter_months:
        season_bump = 0.18   # winter in a temperate city
    else:
        season_bump = 0.00   # shoulder seasons

    weather_risk = float(min(1.0, base_weather + season_bump))

    # ── Traffic stress from time of day ────────────────────────────────────────
    # All 24 hours covered explicitly to prevent boundary discontinuities.
    hour = start_time.hour
    if hour == 0:
        traffic_stress = 0.18
    elif 1 <= hour <= 5:
        traffic_stress = 0.12   # dead night
    elif hour == 6:
        traffic_stress = 0.55   # pre-rush buildup
    elif 7 <= hour <= 9:
        traffic_stress = 0.85   # morning rush
    elif hour == 10:
        traffic_stress = 0.60   # post-morning transition
    elif 11 <= hour <= 14:
        traffic_stress = 0.55   # midday
    elif hour == 15:
        traffic_stress = 0.68   # pre-evening buildup
    elif 16 <= hour <= 19:
        traffic_stress = 0.90   # evening rush (peak)
    elif 20 <= hour <= 21:
        traffic_stress = 0.52   # early evening (post-rush)
    else:  # 22–23
        traffic_stress = 0.22   # late night / nightlife baseline

    # Weekends have less commuter traffic
    if event_date.weekday() >= 5:
        traffic_stress *= 0.72

    traffic_stress = float(min(1.0, traffic_stress))

    # ── Parking availability ───────────────────────────────────────────────────
    density_proxy = base_weather * 0.4   # denser cities tend to have worse parking
    parking       = float(max(0.08, 1.0 - traffic_stress * 0.65 - density_proxy * 0.35))

    # ── Human-readable labels ──────────────────────────────────────────────────
    if weather_risk >= 0.65:
        weather_label = "High Disruption Risk"
    elif weather_risk >= 0.40:
        weather_label = "Moderate Risk"
    else:
        weather_label = "Favorable Conditions"

    if traffic_stress >= 0.75:
        traffic_label = "Rush Hour — Severe"
    elif traffic_stress >= 0.55:
        traffic_label = "Moderate Congestion"
    elif traffic_stress >= 0.30:
        traffic_label = "Light Traffic"
    else:
        traffic_label = "Clear Roads"

    return {
        "weather_risk"  : weather_risk,
        "traffic_stress": traffic_stress,
        "transit"       : 1.0 - traffic_stress,   # engine input: 1=good, 0=gridlock
        "parking"       : parking,
        "lat"           : lat,
        "lon"           : lon,
        "weather_label" : weather_label,
        "traffic_label" : traffic_label,
        "heat_city"     : heat_city,
    }
