"""Port Typhoon Risk Simulator — Streamlit frontend.

Launch (mock mode):  PTS_MOCK=1 streamlit run src/app_streamlit.py
Launch (real mode):  streamlit run src/app_streamlit.py
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backend.configs.feature_flags import USE_MOCK_PIPELINE
from backend.pipeline import run_single_scenario_pipeline
from frontend.state import f_state
from frontend.state_schema import AppState
from frontend.view_models import (
    _MOCK_RESULTS_VM,
    HistoricalTyphoonRow,
    ResultsViewModel,
    build_results_viewmodel,
    build_typhoon_info_viewmodel,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PORT_LAT = 21.800   # NPT — illustrative location (demo, not a real terminal)
PORT_LON = 113.100

# Arco Design tokens
_C_PRIMARY   = "#165DFF"
_C_TEXT      = "#1d2129"
_C_TEXT_SEC  = "#4e5969"
_C_TEXT_AUX  = "#86909c"
_C_BG        = "#f2f3f5"
_C_CARD      = "#ffffff"
_C_BORDER    = "#e5e6eb"
_C_NAV       = "#125993"
_C_PASS      = "#00B42A"
_C_FAIL      = "#F53F3F"
_C_WARN      = "#FF7D00"


def _inject_css() -> None:
    st.markdown(f"""
<style>
/* ── Arco Design token alignment ──────────────────────────────────────── */
.stApp {{ background-color: {_C_BG}; }}

[data-testid="stSidebar"] {{
    background-color: {_C_CARD};
    border-right: 1px solid {_C_BORDER};
}}

header[data-testid="stHeader"] {{ background-color: {_C_NAV}; }}
#MainMenu, footer {{ visibility: hidden; }}

/* ── Typography ─────────────────────────────────────────────────────────── */
h1, h2, h3, h4 {{ color: {_C_TEXT}; font-weight: 600; font-size: 14px; margin-bottom: 4px; }}
p, li, label, span {{ color: {_C_TEXT}; font-size: 13px; }}
small, .caption {{ color: {_C_TEXT_AUX}; font-size: 11px; }}

/* ── Primary button ─────────────────────────────────────────────────────── */
button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"] {{
    background-color: {_C_PRIMARY} !important;
    border-color: {_C_PRIMARY} !important;
    border-radius: 4px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
}}

/* ── Metric containers (small cards) ────────────────────────────────────── */
[data-testid="metric-container"] {{
    background: {_C_CARD};
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    padding: 12px 16px;
}}
[data-testid="stMetricLabel"] {{ font-size: 11px; color: {_C_TEXT_AUX}; font-weight: 500; }}
[data-testid="stMetricValue"] {{ font-size: 20px; font-weight: 600; color: {_C_TEXT}; }}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tab"] {{
    font-size: 13px; font-weight: 500; color: {_C_TEXT_SEC};
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color: {_C_PRIMARY}; border-bottom: 2px solid {_C_PRIMARY};
}}

/* ── Dataframes ─────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
}}

/* ── Info / Error / Warning boxes ──────────────────────────────────────── */
[data-testid="stAlert"] {{ border-radius: 4px; font-size: 13px; }}

/* ── Divider ────────────────────────────────────────────────────────────── */
hr {{ border-color: {_C_BORDER}; margin: 10px 0; }}

/* ── Sidebar port info block ────────────────────────────────────────────── */
.pts-port-info {{ font-size: 13px; line-height: 1.9; color: {_C_TEXT}; }}
.pts-port-info .label {{ color: {_C_TEXT_AUX}; font-size: 11px; }}
.pts-port-info .value {{ font-weight: 600; color: {_C_TEXT}; }}

/* ── Full-screen map: collapse main container padding ───────────────────── */
.main .block-container {{
    padding-top: 0.4rem !important;
    padding-bottom: 0 !important;
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
    max-width: 100% !important;
}}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loaders (cached — loaded once per session)
# ---------------------------------------------------------------------------

@st.cache_data
def _load_presets() -> dict[str, dict]:
    """Returns {sid: preset_dict} from typhoon_presets.json."""
    path = ROOT / "src" / "backend" / "configs" / "typhoon_presets.json"
    if not path.exists():
        return {}
    return {p["sid"]: p for p in json.loads(path.read_text())}


@st.cache_data
def _load_track(sid: str) -> list[dict] | None:
    """Returns [{lat, lon, time}, …] or None if file missing."""
    path = ROOT / "data" / "typhoon_tracks" / f"{sid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


@st.cache_data
def _load_all_tracks() -> dict[str, list[dict]]:
    """Returns {sid: track_points} for all available track files."""
    tracks_dir = ROOT / "data" / "typhoon_tracks"
    if not tracks_dir.exists():
        return {}
    result: dict[str, list[dict]] = {}
    for p in tracks_dir.glob("*.json"):
        with contextlib.suppress(Exception):
            result[p.stem] = json.loads(p.read_text())
    return result


@st.cache_data
def _load_history() -> list[dict]:
    """Returns all qualifying typhoon history events from typhoon_history.json."""
    path = ROOT / "data" / "typhoon_history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


@st.cache_data
def _load_port_config() -> dict:
    """Returns NPT port config dict."""
    path = ROOT / "src" / "backend" / "configs" / "port_configs.json"
    return json.loads(path.read_text())["ports"]["NPT"]


# ---------------------------------------------------------------------------
# Map helpers
# ---------------------------------------------------------------------------

def _compute_ring(lat: float, lon: float, dist_km: float, n: int = 90) -> tuple[list[float], list[float]]:
    """Geodesic circle at dist_km from (lat, lon); returns (lats, lons)."""
    R = 6371.0
    lats, lons = [], []
    for i in range(n + 1):
        bearing = 2 * math.pi * i / n
        lat2 = math.asin(
            math.sin(math.radians(lat)) * math.cos(dist_km / R)
            + math.cos(math.radians(lat)) * math.sin(dist_km / R) * math.cos(bearing)
        )
        lon2 = math.radians(lon) + math.atan2(
            math.sin(bearing) * math.sin(dist_km / R) * math.cos(math.radians(lat)),
            math.cos(dist_km / R) - math.sin(math.radians(lat)) * math.sin(lat2),
        )
        lats.append(math.degrees(lat2))
        lons.append(math.degrees(lon2))
    return lats, lons


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' to 'rgba(r,g,b,alpha)' — Plotly-safe opacity."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from point 1 → 2 (degrees clockwise from North)."""
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlonr = math.radians(lon2 - lon1)
    x = math.sin(dlonr) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlonr)
    return (math.degrees(math.atan2(x, y)) + 360) % 360



# Category colour scheme (Saffir-Simpson)
_CAT_COLOR = {1: "#4FB3FF", 2: "#00C48C", 3: "#FFB800", 4: "#FF7A00", 5: "#FF3B30"}


def _vmax_to_cat_color(vmax_kt: float | None) -> str:
    """Per-point Saffir-Simpson color from Vmax [kt]. Gray for TD/TS/unknown."""
    if vmax_kt is None or vmax_kt < 64:
        return "#a0a0a0"
    if vmax_kt < 83:
        return _CAT_COLOR[1]
    if vmax_kt < 96:
        return _CAT_COLOR[2]
    if vmax_kt < 113:
        return _CAT_COLOR[3]
    if vmax_kt < 137:
        return _CAT_COLOR[4]
    return _CAT_COLOR[5]

# Hazard type registry — (icon, label, implemented)
_HAZARDS: dict[str, list[tuple[str, str, bool]]] = {
    "Natural Disasters": [
        ("🌀", "Typhoon",     True),
        ("🌍", "Earthquake",  False),
        ("🌊", "Tsunami",     False),
        ("⛈️", "Storm Surge", False),
        ("🌧️", "Flood",       False),
    ],
    "Man-made Disasters": [
        ("🛢️", "Oil Spill",   False),
        ("💥", "Explosion",   False),
        ("⚒️", "Strike",      False),
        ("⚔️", "War",         False),
        ("💣", "Terrorism",   False),
    ],
}


def _render_hazard_selector() -> None:
    """Vertical hazard-type list with Natural / Man-made grouping."""
    lines = ['<div style="margin:2px 0 6px;">']
    for category, items in _HAZARDS.items():
        lines.append(
            f'<div style="font-size:10px;color:{_C_TEXT_AUX};font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.6px;margin:8px 0 4px;">'
            f'{category}</div>'
        )
        for icon, name, active in items:
            bg     = _C_PRIMARY if active else "#f7f8fa"
            color  = "white"    if active else _C_TEXT_SEC
            border = _C_PRIMARY if active else _C_BORDER
            weight = "600"      if active else "400"
            lines.append(
                f'<div style="display:flex;align-items:center;padding:5px 8px;'
                f'margin-bottom:3px;background:{bg};border:1px solid {border};'
                f'border-radius:4px;cursor:default;">'
                f'<span style="font-size:15px;width:22px;display:inline-block;'
                f'text-align:center">{icon}</span>'
                f'<span style="font-size:12px;color:{color};font-weight:{weight};'
                f'margin-left:6px">{name}</span>'
                f'</div>'
            )
    lines.append('</div>')
    st.sidebar.markdown("".join(lines), unsafe_allow_html=True)


def _build_map_figure(
    track: list[dict] | None,
    all_tracks: dict[str, list[dict]],
    show_history: bool,
    selected_sid: str | None,
    strike_dist_km: float | None,
    typhoon_category: int | None = None,
) -> go.Figure:
    """Build Plotly Scattergeo — abstract base map, port location anonymised."""
    traces: list[Any] = []
    animated_trace_idx: int | None = None
    track_color = _CAT_COLOR.get(typhoon_category or 4, "#d62728")

    # 1) Historical tracks — very faint
    if show_history:
        for sid, pts in all_tracks.items():
            if sid == selected_sid or not pts:
                continue
            traces.append(go.Scattergeo(
                lat=[p["lat"] for p in pts],
                lon=[p["lon"] for p in pts],
                mode="lines",
                line=dict(color="rgba(100,100,100,0.18)", width=0.8),
                showlegend=False,
                hoverinfo="skip",
            ))

    # 2) Selected typhoon track
    lats_t: list[float] = []
    lons_t: list[float] = []
    times_t: list[str] = []
    vmax_kt_t: list[float | None] = []
    hover_texts: list[str] = []
    dot_colors: list[str] = []
    if track:
        lats_t = [p["lat"] for p in track]
        lons_t = [p["lon"] for p in track]
        times_t = [p["time"] for p in track]
        vmax_kt_t = [p.get("vmax_kt") for p in track]
        hover_texts = [
            f"{t[:16].replace('T', ' ')} UTC · {v:.0f} kt" if v is not None
            else t[:16].replace("T", " ")
            for t, v in zip(times_t, vmax_kt_t, strict=False)
        ]
        dot_colors = [_vmax_to_cat_color(v) for v in vmax_kt_t]

        # Track line
        traces.append(go.Scattergeo(
            lat=lats_t, lon=lons_t,
            mode="lines",
            line=dict(color=track_color, width=3),
            showlegend=False,
            hoverinfo="skip",
        ))
        # 6-hourly dots colored by Saffir-Simpson category
        traces.append(go.Scattergeo(
            lat=lats_t, lon=lons_t,
            mode="markers",
            marker=dict(symbol="circle", size=7, color=dot_colors,
                        line=dict(width=1.5, color="white")),
            text=hover_texts,
            hovertemplate="<b>%{text}</b><extra></extra>",
            showlegend=False,
        ))
        # Animated head dot
        animated_trace_idx = len(traces)
        traces.append(go.Scattergeo(
            lat=[lats_t[0]], lon=[lons_t[0]],
            mode="markers",
            marker=dict(size=14, symbol="circle", color=track_color,
                        line=dict(width=2, color="white")),
            showlegend=False,
            hovertemplate="<b>%{customdata}</b><extra></extra>",
            customdata=[hover_texts[0]],
        ))

    # 3) Strike distance ring
    if strike_dist_km:
        ring_lats, ring_lons = _compute_ring(PORT_LAT, PORT_LON, strike_dist_km)
        traces.append(go.Scattergeo(
            lat=ring_lats, lon=ring_lons,
            mode="lines",
            line=dict(color="rgba(255,127,14,0.9)", width=1.5, dash="dash"),
            showlegend=True,
            name=f"Strike ring {strike_dist_km:.0f} km",
            hoverinfo="skip",
        ))

    # 4) Port marker
    traces.append(go.Scattergeo(
        lat=[PORT_LAT], lon=[PORT_LON],
        mode="markers+text",
        marker=dict(size=14, symbol="pentagon", color="#2ca02c",
                    line=dict(width=1.5, color="white")),
        text=["Container Port A"],
        textposition="top right",
        textfont=dict(size=10, color="#2ca02c"),
        showlegend=False,
        hovertemplate="<b>Container Port A</b><extra></extra>",
    ))

    fig = go.Figure(data=traces)

    # Animation frames
    frames: list[go.Frame] = []
    initial_ann: dict | None = None
    if track and animated_trace_idx is not None:
        for i in range(len(lats_t)):
            t_str = times_t[i][:16].replace("T", " ")
            v = vmax_kt_t[i]
            ann_text = f"<b>{t_str}</b>"
            if v is not None:
                ann_text += f"<br>Vmax: {v:.0f} kt"
            ann = dict(
                text=ann_text, x=0.99, y=0.04, xref="paper", yref="paper",
                xanchor="right", yanchor="middle", showarrow=False,
                font=dict(size=10, color=_C_TEXT_SEC),
                bgcolor="rgba(255,255,255,0.90)",
                bordercolor=_C_BORDER, borderwidth=1, borderpad=4, align="right",
            )
            if i == 0:
                initial_ann = ann
            frames.append(go.Frame(
                data=[go.Scattergeo(
                    lat=[lats_t[i]], lon=[lons_t[i]],
                    mode="markers",
                    marker=dict(size=14, symbol="circle", color=track_color,
                                line=dict(width=2, color="white")),
                    customdata=[hover_texts[i]],
                    hovertemplate="<b>%{customdata}</b><extra></extra>",
                )],
                layout={"annotations": [ann]},
                traces=[animated_trace_idx],
                name=str(i),
            ))
        fig.frames = frames

    # Play / Pause buttons
    update_menus: list[dict] = []
    if frames:
        update_menus = [{
            "type": "buttons",
            "direction": "right",
            "showactive": False,
            "x": 0.5, "xanchor": "center",
            "y": 0.04, "yanchor": "middle",
            "bgcolor": "rgba(255,255,255,0.95)",
            "bordercolor": _C_BORDER,
            "borderwidth": 1,
            "pad": {"r": 6, "t": 4, "b": 4, "l": 6},
            "font": {"size": 12, "color": _C_TEXT},
            "buttons": [
                {
                    "label": "▶  Play",
                    "method": "animate",
                    "args": [None, {"frame": {"duration": 130, "redraw": True}, "fromcurrent": True}],
                },
                {
                    "label": "⏸  Pause",
                    "method": "animate",
                    "args": [[None], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}}],
                },
            ],
        }]

    has_legend = any(getattr(t, "showlegend", False) for t in traces)
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=900,
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=has_legend,
        legend=dict(
            font=dict(size=10, color=_C_TEXT_SEC),
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor=_C_BORDER, borderwidth=1,
            x=0.0, xanchor="left",
            y=0.04, yanchor="middle",
        ),
        geo=dict(
            scope="asia",
            domain=dict(x=[0, 1], y=[0.08, 1.0]),
            lataxis_range=[5, 35],
            lonaxis_range=[105, 145],
            showland=True, landcolor="rgb(243,243,243)",
            showocean=True, oceancolor="rgb(204,229,255)",
            showcountries=True, countrycolor="rgb(200,200,200)",
            showcoastlines=True, coastlinecolor="rgb(160,160,160)",
            showrivers=False,
            showsubunits=True, subunitcolor="rgb(220,220,220)",
        ),
        updatemenus=update_menus or None,
        annotations=[initial_ann] if initial_ann else [],
    )
    return fig


def _build_track_snapshot(track: list[dict], preset: dict) -> go.Figure:
    """Static mini typhoon-track map for Results page bottom panel."""
    lats_t = [p["lat"] for p in track]
    lons_t = [p["lon"] for p in track]
    vmax_kt_t = [p.get("vmax_kt") for p in track]
    dot_colors = [_vmax_to_cat_color(v) for v in vmax_kt_t]
    track_color = _CAT_COLOR.get(preset.get("category", 4), "#d62728")

    traces: list[Any] = []
    # Track line
    traces.append(go.Scattergeo(
        lat=lats_t, lon=lons_t, mode="lines",
        line=dict(color=track_color, width=2.5), showlegend=False, hoverinfo="skip",
    ))
    # Dots by category
    traces.append(go.Scattergeo(
        lat=lats_t, lon=lons_t, mode="markers",
        marker=dict(symbol="circle", size=5, color=dot_colors, line=dict(width=1, color="white")),
        showlegend=False, hoverinfo="skip",
    ))
    # Strike ring
    strike_km = preset.get("strike_dist_km")
    if strike_km:
        ring_lats, ring_lons = _compute_ring(PORT_LAT, PORT_LON, strike_km)
        traces.append(go.Scattergeo(
            lat=ring_lats, lon=ring_lons, mode="lines",
            line=dict(color="rgba(255,127,14,0.85)", width=1.2, dash="dash"),
            showlegend=False, hoverinfo="skip",
        ))
    # Port marker + emoji at landfall
    traces.append(go.Scattergeo(
        lat=[PORT_LAT], lon=[PORT_LON], mode="markers+text",
        marker=dict(size=12, symbol="pentagon", color="#2ca02c", line=dict(width=1.5, color="white")),
        text=["Container Port A"], textposition="top right",
        textfont=dict(size=9, color="#2ca02c"), showlegend=False,
        hovertemplate="<b>Container Port A</b><extra></extra>",
    ))
    # Cyclone emoji at track start (origin)
    traces.append(go.Scattergeo(
        lat=[lats_t[0]], lon=[lons_t[0]], mode="text",
        text=["🌀"], textfont=dict(size=20), showlegend=False, hoverinfo="skip",
    ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=300,
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        geo=dict(
            scope="asia",
            lataxis_range=[5, 35], lonaxis_range=[105, 145],
            showland=True, landcolor="rgb(243,243,243)",
            showocean=True, oceancolor="rgb(204,229,255)",
            showcountries=True, countrycolor="rgb(200,200,200)",
            showcoastlines=True, coastlinecolor="rgb(160,160,160)",
            showrivers=False,
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# App state helper
# ---------------------------------------------------------------------------

def _apply_patch(patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        st.session_state[k] = v


# ---------------------------------------------------------------------------
# Mock ResultsViewModel builder (uses real history data for Tab 2)
# ---------------------------------------------------------------------------

def _build_mock_results_vm(history: list[dict]) -> ResultsViewModel:
    """Return _MOCK_RESULTS_VM with historical_typhoons populated from real data."""
    historical_typhoons = [
        HistoricalTyphoonRow(
            year=e["year"],
            name=e["name"],
            category=e["category"],
            dist_km=e["strike_dist_km"],
            loss_usd=float(e.get("loss_usd") or 0),
        )
        for e in sorted(history, key=lambda x: x["year"], reverse=True)
    ]
    historical_total = sum(float(e.get("loss_usd") or 0) for e in history)
    n_years = max(len({e["year"] for e in history}), 1)
    historical_avg = historical_total / n_years if historical_total else _MOCK_RESULTS_VM.historical_annual_avg_usd

    return ResultsViewModel(
        typhoon_display_name=_MOCK_RESULTS_VM.typhoon_display_name,
        decreased_teu=_MOCK_RESULTS_VM.decreased_teu,
        decreased_teu_pct=_MOCK_RESULTS_VM.decreased_teu_pct,
        equipment_rows=_MOCK_RESULTS_VM.equipment_rows,
        physical_loss_total_mean_usd=_MOCK_RESULTS_VM.physical_loss_total_mean_usd,
        physical_loss_total_p95_usd=_MOCK_RESULTS_VM.physical_loss_total_p95_usd,
        economic_loss_usd=_MOCK_RESULTS_VM.economic_loss_usd,
        total_loss_usd=_MOCK_RESULTS_VM.total_loss_usd,
        historical_total_usd=historical_total or _MOCK_RESULTS_VM.historical_total_usd,
        historical_annual_avg_usd=historical_avg,
        historical_typhoons=historical_typhoons or _MOCK_RESULTS_VM.historical_typhoons,
        output_dir="outputs/mock_run",
    )


# ---------------------------------------------------------------------------
# eXecute helpers (side effects; separate from render functions)
# ---------------------------------------------------------------------------

def _scenario_summary_csv(vm: ResultsViewModel) -> str:
    """CSV of exactly what Tab 1 (Loss Summary) shows for the run on screen."""
    lines = ["section,label,value"]
    lines.append(f"summary,Typhoon,{vm.typhoon_display_name}")
    lines.append(f"summary,Decreased TEU,{vm.decreased_teu}")
    lines.append(f"summary,Decreased TEU %,{vm.decreased_teu_pct}")
    lines.append(f"summary,Economic Loss USD,{vm.economic_loss_usd}")
    lines.append(f"summary,Physical Loss Mean USD,{vm.physical_loss_total_mean_usd}")
    lines.append(f"summary,Physical Loss P95 USD,{vm.physical_loss_total_p95_usd}")
    lines.append(f"summary,Total Loss USD,{vm.total_loss_usd}")
    for row in vm.equipment_rows:
        lines.append(f"equipment,{row.label} Mean USD,{row.mean_usd}")
        lines.append(f"equipment,{row.label} P95 USD,{row.p95_usd}")
    return "\n".join(lines)


def _historical_typhoons_csv(vm: ResultsViewModel) -> str:
    """CSV of exactly what Tab 2 (Historical Records) shows."""
    lines = ["year,name,category,dist_km,loss_usd"]
    for row in vm.historical_typhoons:
        lines.append(f"{row.year},{row.name},{row.category},{row.dist_km},{row.loss_usd}")
    return "\n".join(lines)


def _export_csv(vm: ResultsViewModel) -> bytes:
    """Return CSV bytes for the run currently shown on screen (not all 25 scenarios)."""
    return _scenario_summary_csv(vm).encode()


def _export_zip(vm: ResultsViewModel) -> bytes:
    """Return a ZIP of the on-screen scenario summary + historical records — nothing else."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scenario_summary.csv", _scenario_summary_csv(vm))
        zf.writestr("historical_typhoons.csv", _historical_typhoons_csv(vm))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Render: CONFIG sidebar (pure view — no side effects)
# ---------------------------------------------------------------------------

def _render_sidebar_config(
    presets_by_sid: dict[str, dict],
    port_config: dict,
    disabled: bool = False,
) -> tuple[str | None, bool]:
    """Render port info + typhoon selector. Returns (selected_sid, run_clicked)."""
    throughput_m = port_config["annual_throughput_base_teu"] / 1e6
    st.sidebar.markdown(f"""
<div class="pts-port-info">
<span style="font-size:14px;font-weight:600;color:{_C_PRIMARY}">Container Port A</span><br>
<span class="label">Berths</span> &nbsp; <span class="value">{port_config['num_berths']}</span><br>
<span class="label">Quay Cranes</span> &nbsp; <span class="value">{port_config['num_quay_cranes']}</span><br>
<span class="label">Design TEU</span> &nbsp; <span class="value">~{throughput_m:.0f}M / yr</span><br>
<span class="label">Avg Ship Calls</span> &nbsp; <span class="value">~2,900 / yr</span>
</div>
""", unsafe_allow_html=True)

    st.sidebar.divider()

    st.sidebar.markdown(
        f'<div style="font-size:13px;font-weight:600;color:{_C_PRIMARY};margin-bottom:2px;">'
        f'Hazard Type</div>',
        unsafe_allow_html=True,
    )
    _render_hazard_selector()

    st.sidebar.divider()
    st.sidebar.markdown(
        f'<div style="font-size:13px;font-weight:600;color:{_C_PRIMARY};margin-bottom:2px;">'
        f'Select Typhoon</div>',
        unsafe_allow_html=True,
    )

    preset_list = sorted(presets_by_sid.values(), key=lambda p: p["year"])
    options: list[str | None] = [None] + [p["sid"] for p in preset_list]

    def _fmt(sid: str | None) -> str:
        if sid is None:
            return "— Select typhoon —"
        p = presets_by_sid[sid]
        return f"{p['display_name']}  (Cat {p['category']}, {p['strike_dist_km']:.0f} km)"

    current_sid: str | None = st.session_state.get("selected_typhoon_id")
    try:
        idx = options.index(current_sid)
    except ValueError:
        idx = 0

    selected_sid: str | None = st.sidebar.selectbox(
        "Typhoon",
        options=options,
        format_func=_fmt,
        index=idx,
        disabled=disabled,
        label_visibility="collapsed",
    )

    if selected_sid:
        p = presets_by_sid[selected_sid]
        st.sidebar.markdown(
            f"**{p['display_name']}**  \n"
            f"Category: {p['category']}  \n"
            f"Strike Dist: {p['strike_dist_km']:.0f} km  \n"
            f"Disruption: {p['disruption_label']}"
        )

    st.sidebar.divider()

    st.sidebar.markdown(
        f'<div style="font-size:13px;font-weight:600;color:{_C_PRIMARY};margin-bottom:4px;">'
        f'Estimate Loss</div>'
        f'<div style="font-size:11px;color:{_C_TEXT_AUX};margin-bottom:10px;">'
        f'Predict physical loss and economic loss for this attack.</div>',
        unsafe_allow_html=True,
    )

    run_disabled = (selected_sid is None) or disabled
    run_clicked: bool = st.sidebar.button(
        "▶  Run Simulation",
        type="primary",
        use_container_width=True,
        disabled=run_disabled,
    )
    return selected_sid, run_clicked


# ---------------------------------------------------------------------------
# Render: RESULTS sidebar (pure view — downloads are eXecute, initiated here)
# ---------------------------------------------------------------------------

def _render_sidebar_results(vm: ResultsViewModel) -> None:
    st.sidebar.markdown(f"""
<div class="pts-port-info">
<span style="font-size:14px;font-weight:600;color:{_C_TEXT}">Container Port A</span><br>
<span class="label">Typhoon</span> &nbsp; <span class="value">{vm.typhoon_display_name}</span><br>
<span class="label">Total Loss</span> &nbsp; <span class="value">${vm.total_loss_usd/1e6:.1f} M USD</span>
</div>
""", unsafe_allow_html=True)
    st.sidebar.divider()

    csv_bytes = _export_csv(vm)
    st.sidebar.download_button(
        "↓ Download CSV",
        data=csv_bytes,
        file_name="pts_scenario_losses.csv",
        mime="text/csv",
        use_container_width=True,
    )
    zip_bytes = _export_zip(vm)
    st.sidebar.download_button(
        "↓ Download ZIP",
        data=zip_bytes,
        file_name="pts_run_artifacts.zip",
        mime="application/zip",
        use_container_width=True,
        )
    st.sidebar.divider()


# ---------------------------------------------------------------------------
# Render: error banner (pure view — Retry event handled at app layer)
# ---------------------------------------------------------------------------

def _render_error_banner(error_msg: str) -> bool:
    """Show error banner. Returns True if Retry was clicked."""
    c1, c2 = st.columns([5, 1])
    c1.error(f"✖  Simulation failed: {error_msg}")
    return bool(c2.button("Retry", type="primary"))


# ---------------------------------------------------------------------------
# Render: RESULTS Tab 1 — Loss Summary (pure view)
# ---------------------------------------------------------------------------

def _render_results_tab1(vm: ResultsViewModel) -> None:
    st.markdown(f"#### Throughput Impact · {vm.typhoon_display_name}")
    c1, c2 = st.columns(2)
    c1.metric("Decreased TEU", f"{vm.decreased_teu:,.0f} TEU")
    c2.metric("vs. Intact", f"−{vm.decreased_teu_pct:.1f} %")

    st.markdown("---")
    st.metric(
        "Physical Loss Total (mean)",
        f"${vm.physical_loss_total_mean_usd/1e6:.1f} M USD",
        help=f"P95: ${vm.physical_loss_total_p95_usd/1e6:.1f} M USD",
    )

    rows = [
        {
            "Equipment": r.label,
            "Mean (M USD)": f"${r.mean_usd/1e6:.1f}",
            "P95 (M USD)": f"${r.p95_usd/1e6:.1f}",
        }
        for r in vm.equipment_rows
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.metric("Economic Loss (E4)", f"${vm.economic_loss_usd/1e6:.1f} M USD")
    st.metric("Total Loss  (Physical + Economic)", f"${vm.total_loss_usd/1e6:.1f} M USD")


# ---------------------------------------------------------------------------
# Render: RESULTS Tab 2 — Historical Records (pure view)
# ---------------------------------------------------------------------------

def _render_results_tab2(vm: ResultsViewModel) -> None:
    n_events = len(vm.historical_typhoons)
    n_years = max(len({r.year for r in vm.historical_typhoons}), 1)

    st.info(
        f"**Historical Total Loss  (1994–2025)**  \n"
        f"${vm.historical_total_usd/1e6:,.1f} M USD  ·  "
        f"Annual avg: ${vm.historical_annual_avg_usd/1e6:.1f} M USD  ·  "
        f"Based on {n_events} events · {n_years} years"
    )

    st.markdown("**Typhoon Strike History (Port A, 1994–2025)**")
    rows = [
        {
            "Year": r.year,
            "Name": r.name,
            "Cat": r.category,
            "Dist (km)": f"{r.dist_km:.0f}",
            "Est. Loss (M USD)": f"${r.loss_usd/1e6:.1f}" if r.loss_usd else "—",
        }
        for r in vm.historical_typhoons
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown(
        "**Validation (benchmark reference):**  "
        "Ships: Reality 2,902 / Sim 2,899  ·  "
        "TEU: Reality 6,519.5 / Sim 6,516.0"
    )


# ---------------------------------------------------------------------------
# Main app loop
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Port Typhoon Risk Simulator",
        page_icon="🌀",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()

    # Initialise session state from AppState schema (first load only)
    if "stage" not in st.session_state:
        st.session_state.update(AppState().model_dump())

    stage: str = st.session_state["stage"]

    # ── INIT ─────────────────────────────────────────────────────────────────
    if stage == "INIT":
        with st.spinner("Loading data…"):
            _load_presets()
            _load_all_tracks()
        tr = f_state("INIT", "presets_loaded")
        _apply_patch(tr.session_state_patch)
        st.rerun()

    # ── CONFIG / ERROR ────────────────────────────────────────────────────────
    elif stage in ("CONFIG", "ERROR"):
        presets_by_sid = _load_presets()
        if not presets_by_sid:
            st.error(
                "Typhoon presets not found. "
                "Run `python scripts/e1_parse_ibtracs.py` first."
            )
            st.stop()

        port_config = _load_port_config()
        selected_sid_ui, run_clicked = _render_sidebar_config(
            presets_by_sid, port_config, disabled=False
        )

        # ── Event: typhoon_selected ───────────────────────────────────────
        old_sid: str | None = st.session_state.get("selected_typhoon_id")
        if selected_sid_ui != old_sid:
            tr = f_state(
                stage, "typhoon_selected",
                sid=selected_sid_ui,
                sid_is_valid=(selected_sid_ui in presets_by_sid) if selected_sid_ui else False,
                scenario_id=(
                    presets_by_sid[selected_sid_ui]["scenario_id"]
                    if selected_sid_ui and selected_sid_ui in presets_by_sid
                    else None
                ),
            )
            _apply_patch(tr.session_state_patch)
            st.rerun()

        # ── Event: run_clicked ────────────────────────────────────────────
        if run_clicked:
            tr = f_state(
                stage, "run_clicked",
                selected_typhoon_id=st.session_state.get("selected_typhoon_id"),
            )
            _apply_patch(tr.session_state_patch)
            st.rerun()

        # ── Main area ─────────────────────────────────────────────────────
        if stage == "ERROR":
            retry = _render_error_banner(st.session_state.get("error_msg", "Unknown error"))
            if retry:
                tr = f_state(
                    "ERROR", "retry_clicked",
                    selected_typhoon_id=st.session_state.get("selected_typhoon_id"),
                )
                _apply_patch(tr.session_state_patch)
                st.rerun()

        # History toggle (sidebar — keeps main area clean for the map)
        show_history_new: bool = st.sidebar.checkbox(
            "Show Historical Typhoons (1994–2026)",
            value=st.session_state.get("show_history_tracks", True),
        )
        if show_history_new != st.session_state.get("show_history_tracks", True):
            tr = f_state(
                stage, "history_toggled",
                show_history_tracks=st.session_state.get("show_history_tracks", True),
            )
            _apply_patch(tr.session_state_patch)
            st.rerun()

        # Build and display map
        current_sid: str | None = st.session_state.get("selected_typhoon_id")
        track = _load_track(current_sid) if current_sid else None
        if track is None and current_sid:
            st.warning("Track data unavailable — map shows port location only.")

        all_tracks = _load_all_tracks() if show_history_new else {}
        strike_km = (
            presets_by_sid[current_sid]["strike_dist_km"]
            if current_sid and current_sid in presets_by_sid
            else None
        )

        if current_sid is None:
            st.info("Select a typhoon from the sidebar to begin.")

        typhoon_cat = (
            presets_by_sid[current_sid]["category"]
            if current_sid and current_sid in presets_by_sid
            else None
        )
        fig = _build_map_figure(track, all_tracks, show_history_new, current_sid, strike_km, typhoon_cat)
        st.plotly_chart(fig, use_container_width=True)



    # ── RUNNING ───────────────────────────────────────────────────────────────
    elif stage == "RUNNING":
        st.sidebar.markdown("*Simulation running…*")

        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            st.markdown("### ⟳  Running simulation…")
            st.caption(
                "Estimated time: ~4 sec (demo)" if USE_MOCK_PIPELINE
                else "Estimated time: ~30 sec"
            )

            result_vm: ResultsViewModel | None = None
            output_dir_str = "outputs/mock_run"
            exc_msg: str | None = None

            with st.status("Simulating typhoon impact…", expanded=True) as status:
                try:
                    steps = [
                        ("Port Operations Simulation", 1.0),
                        ("Physical & Equipment Loss", 0.8),
                        ("Economic Impact Analysis", 0.6),
                        ("Report Generation", 0.4),
                    ]
                    for step_name, duration in steps:
                        st.write(f"⟳  {step_name}")
                        if USE_MOCK_PIPELINE:
                            time.sleep(duration)

                    if USE_MOCK_PIPELINE:
                        history = _load_history()
                        result_vm = _build_mock_results_vm(history)
                    else:
                        current_sid = st.session_state.get("selected_typhoon_id")
                        preset = _load_presets().get(current_sid) if current_sid else None
                        if preset is None:
                            raise ValueError("No typhoon selected — cannot run simulation.")
                        pipeline_out = run_single_scenario_pipeline(
                            scenario_id=preset["scenario_id"],
                        )
                        if pipeline_out["status"] != "OK":
                            raise RuntimeError(
                                f"Pipeline failed: {pipeline_out.get('reason', pipeline_out['status'])}"
                            )
                        typhoon_info = build_typhoon_info_viewmodel(preset)
                        result_vm = build_results_viewmodel(
                            result=pipeline_out["result"],
                            typhoon_info=typhoon_info,
                            output_dir=str(pipeline_out["output_dir"]),
                        )
                        output_dir_str = str(pipeline_out["output_dir"])

                    status.update(label="✓ Analysis complete", state="complete")

                except Exception as exc:
                    exc_msg = str(exc)
                    status.update(label="✗ Failed", state="error")

        if exc_msg:
            tr = f_state("RUNNING", "sim_failed", msg=exc_msg)
        else:
            assert result_vm is not None
            tr = f_state(
                "RUNNING", "sim_completed",
                output_dir_str=output_dir_str,
                results_vm_dict=result_vm.model_dump(),
            )
        _apply_patch(tr.session_state_patch)
        st.rerun()

    # ── RESULTS ───────────────────────────────────────────────────────────────
    elif stage == "RESULTS":
        raw_vm = st.session_state.get("results_vm")
        if raw_vm is None:
            _apply_patch({"stage": "CONFIG"})
            st.rerun()
            return

        vm = ResultsViewModel.model_validate(raw_vm)

        _render_sidebar_results(vm)

        if st.sidebar.button("↺  New Analysis", use_container_width=True):
            tr = f_state("RESULTS", "new_analysis_clicked")
            _apply_patch(tr.session_state_patch)
            st.rerun()

        # Typhoon info card — top of results main area
        presets_for_results = _load_presets()
        result_sid = st.session_state.get("selected_typhoon_id")
        if result_sid and result_sid in presets_for_results:
            rp = presets_for_results[result_sid]
            cat_c = _CAT_COLOR.get(rp["category"], "#808080")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:16px;padding:10px 16px;'
                f'background:{_C_CARD};border:1px solid {_C_BORDER};border-radius:4px;margin-bottom:10px;">'
                f'<span style="font-size:15px;font-weight:600;color:{_C_TEXT}">{rp["display_name"]}</span>'
                f'<span style="background:{cat_c};color:white;font-size:11px;font-weight:700;'
                f'padding:2px 10px;border-radius:10px;">Cat {rp["category"]}</span>'
                f'<span style="font-size:12px;color:{_C_TEXT_SEC}">◉ Strike dist: {rp["strike_dist_km"]:.0f} km</span>'
                f'<span style="font-size:12px;color:{_C_TEXT_SEC}">⏱ Disruption: {rp["disruption_label"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        tab1, tab2 = st.tabs(["📊 Loss Summary", "🕰 Historical Records"])
        with tab1:
            _render_results_tab1(vm)
        with tab2:
            _render_results_tab2(vm)

        # Track snapshot at bottom of results page
        st.markdown("---")
        snap_track = _load_track(result_sid) if result_sid else None
        if snap_track and result_sid and result_sid in presets_for_results:
            snap_preset = presets_for_results[result_sid]
            st.markdown(
                f'<div style="font-size:13px;font-weight:600;color:{_C_TEXT};margin-bottom:4px;">'
                f'Typhoon Track · {snap_preset.get("display_name", result_sid)}</div>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(
                _build_track_snapshot(snap_track, snap_preset),
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
