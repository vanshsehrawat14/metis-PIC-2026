"""
Visualization layer — charts styled for the Vane professional operations SaaS aesthetic.
"""
import numpy as np
import plotly.graph_objects as go

# ── Palette ───────────────────────────────────────────────────────────────────
_BG    = "#08091a"
_CARD  = "#0e0f24"
_PAPER = "rgba(0,0,0,0)"
_GRID  = "#1c1d3a"
_TEXT  = "#c8c8dc"
_MUTED = "#6a6a88"
_TEAL  = "#4a90d9"   # primary accent — clean blue
_CYAN  = "#3a7abd"   # secondary accent
_GOLD  = "#c49030"   # revenue / cost line
_RED   = "#d45050"   # high risk
_GRAY  = "#6a6a88"   # baseline / muted


def build_tradeoff_chart(current_res, top_recs):
    """
    Revenue vs. Congestion Risk scatter.
    Baseline (muted) · Optimized (teal) · High Revenue (gold).
    Dashed improvement arrow connects Baseline → Optimized.
    """
    fig = go.Figure()

    x_max    = max(current_res["cong_p90"][0] * 100 + 20, 90)
    all_revs = [current_res["rev_mean"][0]] + [r["revenue"] for r in top_recs]
    y_lo     = min(all_revs) * 0.82
    y_hi     = max(all_revs) * 1.18

    fig.add_shape(type="rect", x0=0,  x1=50,    y0=y_lo, y1=y_hi,
                  fillcolor="rgba(74,144,217,0.03)", line_width=0, layer="below")
    fig.add_shape(type="rect", x0=50, x1=x_max, y0=y_lo, y1=y_hi,
                  fillcolor="rgba(212,80,80,0.03)", line_width=0, layer="below")
    fig.add_vline(x=50, line_dash="dot", line_color=_GRID, line_width=1)

    opt = top_recs[0]
    bx, by = current_res["cong_mean"][0] * 100, current_res["rev_mean"][0]
    ox, oy = opt["congestion"] * 100, opt["revenue"]

    fig.add_annotation(
        x=ox, y=oy, ax=bx, ay=by,
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1.2, arrowwidth=1.5,
        arrowcolor=_TEAL, opacity=0.7,
    )
    dx_pct = bx - ox
    dy_m   = oy - by
    fig.add_annotation(
        x=(bx + ox) / 2, y=(by + oy) / 2 * 1.04,
        text=f"+${dy_m/1e6:.1f}M  −{dx_pct:.0f}% risk",
        showarrow=False, font=dict(size=9, color=_TEAL),
        bgcolor="rgba(8,9,26,0.85)", borderpad=3,
    )

    fig.add_trace(go.Scatter(
        x=[bx], y=[by],
        mode="markers+text", name="Baseline",
        text=["  Current"], textposition="middle right",
        textfont=dict(size=11, color=_GRAY),
        marker=dict(size=12, color=_GRAY, symbol="circle", line=dict(width=1, color=_BG)),
        customdata=[[current_res["wait_mean"][0], bx, by, current_res["brk_mean"][0]*100]],
        hovertemplate=(
            "<b>Current Config</b><br>Risk: %{x:.0f}%  Rev: $%{customdata[2]:,.0f}<br>"
            "Wait: %{customdata[0]:.0f} min  Failure: %{customdata[3]:.1f}%<extra></extra>"
        ),
    ))

    fig.add_trace(go.Scatter(
        x=[ox], y=[oy],
        mode="markers+text",
        name=f"Optimized [{opt['confidence']:.0f}% conf.]",
        text=["  Recommended"], textposition="middle right",
        textfont=dict(size=11, color=_TEAL),
        marker=dict(size=16, color=_TEAL, symbol="circle", line=dict(width=2, color=_BG)),
        error_y=dict(
            type="data", symmetric=False,
            array=[opt["rev_p90"] - oy], arrayminus=[oy - opt["rev_p10"]],
            color=_TEAL, thickness=1, width=5,
        ),
        customdata=[[opt["wait"], ox, oy, opt["breakdown"]*100]],
        hovertemplate=(
            "<b>Recommended Config</b><br>Risk: %{customdata[1]:.0f}%  Rev: $%{customdata[2]:,.0f}<br>"
            "Wait: %{customdata[0]:.0f} min  Failure: %{customdata[3]:.1f}%<extra></extra>"
        ),
    ))

    if len(top_recs) >= 3:
        high_rev = max(top_recs, key=lambda r: r["revenue"])
        if high_rev is not opt:
            fig.add_trace(go.Scatter(
                x=[high_rev["congestion"] * 100], y=[high_rev["revenue"]],
                mode="markers+text",
                name=f"High Revenue [{high_rev['confidence']:.0f}% conf.]",
                text=["  High Revenue (Higher Risk)"], textposition="middle right",
                textfont=dict(size=10, color=_GOLD),
                marker=dict(size=12, color=_GOLD, symbol="circle",
                            line=dict(width=1.5, color=_BG)),
            ))

    fig.update_layout(
        xaxis=dict(title="Congestion Risk →", range=[0, x_max],
                   gridcolor=_GRID, zeroline=False,
                   tickfont=dict(color=_MUTED, size=10),
                   title_font=dict(size=11, color=_MUTED)),
        yaxis=dict(title="Revenue ($) →", tickformat="$,.0f", range=[y_lo, y_hi],
                   gridcolor=_GRID, zeroline=False,
                   tickfont=dict(color=_MUTED, size=10),
                   title_font=dict(size=11, color=_MUTED)),
        plot_bgcolor=_CARD, paper_bgcolor=_PAPER,
        font=dict(color=_TEXT, family="Computer Modern Serif, Georgia, serif"),
        height=380, margin=dict(l=20, r=110, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10, color=_TEXT), bgcolor="rgba(0,0,0,0)"),
    )
    return fig


def build_radar_chart(env: dict):
    """Environmental stress radar — Weather Risk, Traffic, Parking Scarcity."""
    categories = ["Weather Risk", "Traffic Congestion", "Parking Scarcity"]
    values     = [env["weather_risk"], env["traffic_stress"], 1.0 - env["parking"]]

    fig = go.Figure(data=go.Scatterpolar(
        r=values + [values[0]], theta=categories + [categories[0]],
        fill="toself", fillcolor="rgba(74,144,217,0.09)",
        line=dict(color=_TEAL, width=2), marker=dict(size=5, color=_TEAL),
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=_CARD,
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False,
                            showgrid=True, gridcolor=_GRID, linecolor=_GRID),
            angularaxis=dict(tickfont=dict(color=_TEXT, size=11),
                             gridcolor=_GRID, linecolor=_GRID),
        ),
        showlegend=False, paper_bgcolor=_PAPER,
        margin=dict(l=30, r=30, t=30, b=30), height=280,
    )
    return fig


def build_staffing_comparison(
    event_type: str, attendance: int, current_staff: int,
    price: float, engine, env: dict,
) -> go.Figure:
    """
    Dual-axis chart: Bars = avg wait time, Line = labor cost,
    across 7 staffing levels from −40% to +60% of current.
    """
    levels = np.linspace(max(100, int(current_staff * 0.60)), int(current_staff * 1.60), 7, dtype=int)
    waits, costs = [], []
    for s in levels:
        r = engine.run_vectorized(attendance, int(s), price, env["weather_risk"], env["transit"])
        waits.append(float(r["wait_mean"][0]))
        costs.append(int(s) * 350)

    labels   = [f"{s:,}" for s in levels]
    curr_idx = int(np.argmin(np.abs(levels - current_staff)))
    min_idx  = int(np.argmin(waits))

    colors = [_MUTED] * len(levels)
    colors[min_idx]  = _TEAL
    colors[curr_idx] = _CYAN

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=waits, name="Avg Wait Time (min)",
        marker_color=colors, opacity=0.85,
        hovertemplate="Staff: %{x}<br>Wait: %{y:.1f} min<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=costs, name="Labor Cost ($)",
        yaxis="y2", mode="lines+markers",
        line=dict(color=_GOLD, width=2.5), marker=dict(size=7, color=_GOLD),
        hovertemplate="Staff: %{x}<br>Labor: $%{y:,.0f}<extra></extra>",
    ))
    # Annotate current and optimal
    for idx, label, color in [(curr_idx, "Current", _CYAN), (min_idx, "Optimal", _TEAL)]:
        if idx != curr_idx or label == "Current":
            fig.add_annotation(
                x=labels[idx], y=waits[idx],
                text=label, showarrow=True, arrowhead=2,
                arrowcolor=color, font=dict(size=9, color=color),
                ay=-35, bgcolor="rgba(8,9,26,0.85)",
            )

    fig.update_layout(
        title=dict(text=f"Staffing vs. Wait &amp; Labor Cost", font=dict(size=12, color=_TEXT), x=0),
        xaxis=dict(title="Staff Deployed", tickfont=dict(color=_MUTED, size=10),
                   gridcolor=_GRID, title_font=dict(size=10, color=_MUTED)),
        yaxis=dict(title="Avg Wait (min)", tickfont=dict(color=_TEAL, size=10),
                   gridcolor=_GRID, title_font=dict(size=10, color=_TEAL), zeroline=False),
        yaxis2=dict(title="Labor Cost ($)", tickformat="$,.0f",
                    tickfont=dict(color=_GOLD, size=10), title_font=dict(size=10, color=_GOLD),
                    anchor="x", overlaying="y", side="right", zeroline=False),
        plot_bgcolor=_CARD, paper_bgcolor=_PAPER,
        font=dict(color=_TEXT, family="Computer Modern Serif, Georgia, serif"),
        height=360, margin=dict(l=20, r=90, t=40, b=20), bargap=0.3,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10, color=_TEXT), bgcolor="rgba(0,0,0,0)"),
    )
    return fig


def build_wait_distribution(raw_waits: np.ndarray, event_type: str) -> go.Figure:
    """Probability distribution histogram of 1,000-trial Monte Carlo wait times."""
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=raw_waits, nbinsx=40,
        marker=dict(color=_TEAL, opacity=0.70, line=dict(color=_GRID, width=0.5)),
        hovertemplate="Wait: %{x:.1f} min<br>Count: %{y}<extra></extra>",
    ))
    mean_w = float(np.mean(raw_waits))
    p10_w  = float(np.percentile(raw_waits, 10))
    p90_w  = float(np.percentile(raw_waits, 90))

    for val, label, color in [
        (p10_w,  f"P10 · {p10_w:.1f} min",  _TEAL),
        (mean_w, f"Mean · {mean_w:.1f} min", _TEXT),
        (p90_w,  f"P90 · {p90_w:.1f} min",  _RED),
    ]:
        fig.add_vline(x=val, line_dash="dot", line_color=color, line_width=1.5)
        fig.add_annotation(
            x=val, y=0.97, yref="paper",
            text=label, showarrow=False,
            font=dict(size=8, color=color),
            bgcolor="rgba(8,9,26,0.8)", borderpad=3, xanchor="center",
        )

    fig.update_layout(
        title=dict(text=f"1,000-Trial Wait Distribution — {event_type}",
                   font=dict(size=12, color=_TEXT), x=0),
        xaxis=dict(title="Wait Time (min)", tickfont=dict(color=_MUTED, size=10),
                   gridcolor=_GRID, title_font=dict(size=10, color=_MUTED)),
        yaxis=dict(title="Frequency", tickfont=dict(color=_MUTED, size=10),
                   gridcolor=_GRID, title_font=dict(size=10, color=_MUTED)),
        plot_bgcolor=_CARD, paper_bgcolor=_PAPER,
        font=dict(color=_TEXT, family="Computer Modern Serif, Georgia, serif"),
        height=300, margin=dict(l=20, r=20, t=40, b=20), showlegend=False,
    )
    return fig
