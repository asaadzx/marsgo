"""MarsGo — Mango's Mars map.

A suit-aware EVA traverse planner for Jezero Crater, built from cached NASA
data. Run with:

    streamlit run app.py
"""

from __future__ import annotations

import html

import folium
import streamlit as st
from streamlit_folium import st_folium
# Try to import the tour component; if it fails, declare it manually from the installed package assets.
try:
    from streamlit_tour import st_tour
except Exception:
    # Fallback: use pre‑copied assets inside the Docker image.
    try:
        import pathlib
        import streamlit.components.v1 as components
        asset_dir = pathlib.Path('/app/streamlit_tour_assets')
        st_tour = components.declare_component('streamlit_tour', path=str(asset_dir))
    except Exception:
        # Final silent fallback – no‑op placeholder (no warning).
        def st_tour(*args, **kwargs):
            return None
import json, pathlib

from src import data, routing, suit, terrain, ui, weather
from src.config import (
    BOX,
    COLORS,
    GEOLOGY_COLORS,
    OBJECTIVES,
    STATION_ORDER,
)

st.set_page_config(
    page_title="MarsGo — Jezero EVA planner",
    page_icon="🪐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state flags
if "first_run" not in st.session_state:
    # Persist tour completion beyond session using a file marker
    tour_marker = pathlib.Path(__file__).parent / ".tour_completed"
    st.session_state.first_run = not tour_marker.exists()
if "show_tour" not in st.session_state:
    st.session_state.show_tour = False
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "planner"

# Sidebar controls (moved above tour rendering)
col1, col2 = st.columns([1, 1])
with col1:
    st.markdown("<div id='replay-tour'></div>", unsafe_allow_html=True)
    if st.button("Replay Tour"):
        st.session_state.show_tour = True
with col2:
    st.markdown("<div id='help-button'></div>", unsafe_allow_html=True)
    if st.button("Help"):
        st.session_state.view_mode = "help"
# Auto‑launch tour on first run
if st.session_state.first_run:
    st.session_state.show_tour = True
ui.inject_css(st)

# Load guided tour steps
tour_path = pathlib.Path(__file__).parent / "assets" / "tour_steps.json"
with open(tour_path) as f:
    tour_data = json.load(f)

if st.session_state.show_tour:
    # Attempt to render the tour; if fallback is active it will just warn.
    st_tour(steps=tour_data["steps"])
    st.session_state.show_tour = False
    # Mark tour as completed on disk
    tour_marker = pathlib.Path(__file__).parent / ".tour_completed"
    tour_marker.touch()
    st.session_state.first_run = False

# Help view handling
if st.session_state.view_mode == "help":
    st.markdown("## Help & Glossary")
    st.markdown("""
**Navigation**: Use the sidebar to select stations and options.
**Tour**: Replay the guided tour anytime with the button above.

**Glossary**
- *sol*: Martian solar day (~24h 39m).
- *EVA*: Extravehicular activity.
- *Field mode*: Glove‑compatible UI for astronauts.
""")
    if st.button("Back to Planner"):
        st.session_state.view_mode = "planner"


# --------------------------------------------------------------------------
# cached compute
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=24)
def cached_route(ids: tuple[str, ...], speed_kmh: float) -> routing.RouteResult | None:
    return routing.plan_route(ids, speed_kmh)


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

stations = list(data.stations())
station_map = {s["id"]: s for s in stations}
start = station_map.get("START")
w = weather.conditions()

if "field_mode" not in st.session_state:
    st.session_state.field_mode = False


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        '<div class="mg-brand" style="margin-bottom:14px">'
        '<div class="name">Mars<span>Go</span></div>'
        '<div class="tag">EVA planner</div></div>',
        unsafe_allow_html=True,
    )
    # Help and tour controls
    # Sidebar buttons moved above tour rendering
    st.markdown("---")
    st.markdown('<div class="sect" style="margin-top:0">Science objective</div>',
                unsafe_allow_html=True)
    # Placeholder for tour selector
    st.markdown("<div id='objective-select'></div>", unsafe_allow_html=True)
    st.markdown("<div id='objective-select'></div>", unsafe_allow_html=True)
    objective = st.selectbox(
        "Science objective", list(OBJECTIVES), label_visibility="collapsed",
    )
    obj = OBJECTIVES[objective]
    st.caption(obj["question"])

    st.markdown('<div class="sect">Heritage stations</div>', unsafe_allow_html=True)
    station_ids = st.multiselect(
        "Heritage stations",
        options=list(STATION_ORDER),
        default=obj["stations"],
        format_func=lambda s: f"{s} · {station_map[s]['name']}",
        label_visibility="collapsed",
        key=f"stations::{objective}",
    )

    st.markdown('<div class="sect">Suit limits</div>', unsafe_allow_html=True)
    cap_h = st.slider("EVA duration cap (h)", 2.0, 8.0, 6.0, 0.5)
    speed = st.slider("Walk speed (km/h)", 1.0, 2.0, 1.5, 0.1)
    reserve_pct = st.slider("Walk-back reserve (%)", 10, 40, 25, 5)
    with st.expander("Assumptions and units"):
        st.caption(
            "PLSS planning values, not flight rules: 1.0 kg O₂ at 0.09 kg/h; "
            "2.5 L water at 0.15 L/h; 8 h battery; 0.03 mSv/h surface GCR; "
            "600 mSv career limit. Walk time adds 6% per degree of climb."
        )

    st.markdown('<div class="sect">Map layers</div>', unsafe_allow_html=True)
    show_geology = st.toggle("USGS geologic units", True)
    show_slope = st.toggle("Slope (DEM)", False)
    show_rough = st.toggle("Surface roughness (CTX)", False)
    show_hazard = st.toggle("No-go terrain", True)
    show_rover = st.toggle("Perseverance traverse", True)
    show_ellipse = st.toggle("Landing ellipse", True)
    show_features = st.toggle("Named features", False)

    st.markdown('<div class="sect">Off-nominal</div>', unsafe_allow_html=True)
    solar_event = st.toggle("Solar particle event", False)
    dust_storm = st.toggle("Dust-storm hold", False)

    st.divider()
    field_mode = st.toggle("Field mode (glove UI)", value=st.session_state.field_mode)
    st.session_state.field_mode = field_mode

    if st.button("Plan traverse", type="primary", width="stretch"):
        cached_route.clear()

    st.caption(
        "All layers are cached locally. The app never calls NASA during the demo."
    )


# --------------------------------------------------------------------------
# route + verdict
# --------------------------------------------------------------------------

ordered = tuple(s for s in STATION_ORDER if s in station_ids)
route = None
result = None
route_error = None
if ordered:
    try:
        route = cached_route(ordered, float(speed))
    except Exception as exc:  # noqa: BLE001
        route_error = str(exc)

cfg = suit.default_config(
    eva_cap_h=float(cap_h),
    speed_kmh=float(speed),
    reserve_frac=reserve_pct / 100.0,
)
if route is not None:
    result = suit.evaluate(
        route.stats, cfg, w, solar_event=solar_event, dust_storm=dust_storm,
    )


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------

verdict_chip = ""
if result:
    vc = COLORS["go"] if result["verdict"] == "GO" else COLORS["nogo"]
    verdict_chip = (
        f'<span class="chip" style="border-color:{vc};color:{vc};font-weight:800;'
        f'letter-spacing:.08em">{result["verdict"]}</span>'
    )

st.markdown(
    f'<div class="mg-head">'
    f'<div class="mg-brand"><div class="name">Mars<span>Go</span></div>'
    f'<div class="tag">Mango\'s Mars map · EVA-1 · Jezero Crater</div></div>'
    f'<div class="mg-meta">{verdict_chip}{weather.chip_html(w)}'
    f'<span class="chip">CTX 4.83 m/px</span>'
    f'<span class="chip">DEM 200 m/px</span></div></div>',
    unsafe_allow_html=True,
)

if not ordered:
    st.warning("Select at least one heritage station to plan the EVA.")
elif route_error:
    st.error(f"Routing failed: {route_error}")
elif route is None:
    st.info("Press **Plan traverse** to compute a route.")


# --------------------------------------------------------------------------
# map builder
# --------------------------------------------------------------------------

def build_map(route, selected_layers: dict, focus_id: str) -> folium.Map:
    center = [(BOX["s"] + BOX["n"]) / 2, (BOX["w"] + BOX["e"]) / 2]
    bounds = [[BOX["s"], BOX["w"]], [BOX["n"], BOX["e"]]]

    m = folium.Map(
        location=center,
        zoom_start=13,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
        min_zoom=11,
        max_zoom=17,
        max_bounds=True,
        attributionControl=True,
    )
    m.fit_bounds(bounds, padding=(8, 8))
    m.options["maxBounds"] = [
        [BOX["s"] - 0.03, BOX["w"] - 0.05],
        [BOX["n"] + 0.03, BOX["e"] + 0.05],
    ]

    # 1. CTX optical basemap
    folium.raster_layers.ImageOverlay(
        image=str(data.basemap_path()),
        bounds=bounds,
        opacity=1.0,
        name="CTX optical",
        interactive=False,
        cross_origin=False,
    ).add_to(m)

    # 2. USGS geologic units
    if selected_layers["geology"]:
        def style_fn(feature):
            props = feature.get("properties", {})
            return {
                "fillColor": GEOLOGY_COLORS.get(props.get("symbol"), "#9aa3ad"),
                "color": "#0a0c0f",
                "weight": 0.5,
                "opacity": 0.5,
                "fillOpacity": 0.24,
            }

        folium.GeoJson(
            data.geology(),
            name="USGS Jezero geology",
            style_function=style_fn,
            tooltip=folium.GeoJsonTooltip(
                fields=["symbol", "name"], aliases=["Unit", "Name"],
                sticky=True,
            ),
        ).add_to(m)

    # 3. terrain overlays
    overlays = []
    if selected_layers["slope"]:
        overlays.append(("slope", 0.55))
    if selected_layers["rough"]:
        overlays.append(("roughness", 0.50))
    if selected_layers["hazard"]:
        overlays.append(("hazard", 0.80))
    for name, opacity in overlays:
        folium.raster_layers.ImageOverlay(
            image=str(data.overlay_path(name)),
            bounds=bounds,
            opacity=opacity,
            name=name,
            interactive=False,
            cross_origin=False,
        ).add_to(m)

    # 4. landing ellipse
    if selected_layers["ellipse"]:
        folium.GeoJson(
            data.landing_ellipse(),
            name="Landing ellipse",
            style_function=lambda _: {
                "color": "#f1c40f", "weight": 1.4, "dashArray": "6 6",
                "fill": False, "opacity": 0.9,
            },
        ).add_to(m)

    # 5. named features
    if selected_layers["features"]:
        for f in data.waypoints()["features"]:
            lon, lat = f["geometry"]["coordinates"]
            if not (BOX["w"] <= lon <= BOX["e"] and BOX["s"] <= lat <= BOX["n"]):
                continue
            folium.CircleMarker(
                location=[lat, lon], radius=3.5, color="#e0653a",
                weight=1, fill=True, fill_color="#e0653a", fill_opacity=0.7,
                tooltip=f["properties"]["name"],
            ).add_to(m)

    # 6. rover traverse
    if selected_layers["rover"]:
        segs = [[[lat, lon] for lon, lat in seg] for seg in data.traverse_segments()]
        folium.PolyLine(
            locations=segs,
            color="#aab3bc",
            weight=1.6,
            opacity=0.62,
            dash_array="2 6",
            tooltip="Perseverance traverse · sol 14 → 1176 · 26.9 km",
        ).add_to(m)

    # 7. planned human route
    if route is not None and len(route.lons) > 1:
        pts = [[float(lat), float(lon)] for lon, lat in zip(route.lons, route.lats)]
        folium.PolyLine(
            locations=pts, color="#ffffff", weight=9, opacity=0.28, line_cap="round",
        ).add_to(m)
        folium.PolyLine(
            locations=pts,
            color=COLORS["route"],
            weight=4.2,
            opacity=1.0,
            line_cap="round",
            tooltip=(
                f"MarsGo route · {route.stats['distance_km']:.2f} km · "
                f"{ui.fmt_duration(route.stats['duration_h'])}"
            ),
        ).add_to(m)

    # 8. start and stations
    if start:
        folium.Marker(
            location=[start["lat"], start["lon"]],
            icon=folium.DivIcon(
                icon_size=(70, 26), icon_anchor=(35, 13),
                html=(
                    '<div style="background:#f1c40f;color:#111;font:800 11px '
                    'Segoe UI,sans-serif;padding:3px 7px;border-radius:5px;'
                    'text-align:center;border:1px solid #0006;'
                    'box-shadow:0 2px 8px #0008">BASE</div>'
                ),
            ),
            tooltip=f"START · Forward base · sol {start['sol']}",
        ).add_to(m)

    for sid in STATION_ORDER:
        s = station_map.get(sid)
        if s is None:
            continue
        active = sid in (route.station_ids if route else ())
        focus = sid == focus_id
        color = COLORS["route"] if active else "#77818b"
        radius = 9 if focus else 7
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=radius,
            color="#06131a",
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=1.0 if active else 0.55,
            tooltip=f"{sid} · {s['name']} · sol {s['sol']}",
            popup=folium.Popup(
                f"<b>{sid} — {html.escape(s['name'])}</b><br>"
                f"Perseverance sol {s['sol']}<br>"
                f"{s['lon']:.5f}, {s['lat']:.5f}",
                max_width=240,
            ),
        ).add_to(m)
        folium.Marker(
            location=[s["lat"], s["lon"]],
            icon=folium.DivIcon(
                icon_size=(62, 20), icon_anchor=(-10, 26),
                html=(
                    f'<div style="color:#eaf9ff;font:800 12px Segoe UI,sans-serif;'
                    f'text-shadow:0 1px 4px #000,0 0 8px #000;white-space:nowrap">'
                    f'{sid} · {html.escape(s["name"])}</div>'
                ),
            ),
            interactive=False,
        ).add_to(m)

    return m


# --------------------------------------------------------------------------
# station card
# --------------------------------------------------------------------------

def station_science_html(sid: str) -> str:
    s = station_map[sid]
    unit = data.unit_at(s["lon"], s["lat"])
    if unit:
        unit_html = ui.unit_tag(unit.get("symbol", "?"), unit.get("name", "Mapped unit"))
        interpretation = (unit.get("Unit_Interpretation")
                          or unit.get("Unit_Description") or "")
        interpretation = html.escape(interpretation.strip())[:260]
    else:
        unit_html = "<b>Outside mapped unit polygons</b>"
        interpretation = "No USGS unit polygon contains this point."

    spectral = obj["mineral"]
    if "Hydrated" in objective:
        spectral = data.mineral_coverage_note()

    return (
        f'<div class="sci" style="margin-top:8px">'
        f'<div style="margin-bottom:6px">{unit_html}</div>'
        f'<div style="color:#9aa3ad;margin-bottom:9px">{interpretation}</div>'
        f'<div><b>Objective:</b> {html.escape(objective)}</div>'
        f'<div><b>Instrument:</b> {html.escape(obj["instrument"])}</div>'
        f'<div><b>Sample:</b> {html.escape(obj["sample"])}</div>'
        f'<div><b>Dwell:</b> {obj["dwell_min"]} min · '
        f'<b>Priority:</b> {obj["priority"]}</div>'
        f'<div style="margin-top:8px"><b>Spectral context:</b> {html.escape(spectral)}</div>'
        f'<div style="margin-top:8px;color:#9aa3ad">{html.escape(obj["why"])}</div>'
        f"</div>"
    )


def station_card(sid: str) -> None:
    s = station_map[sid]
    st.markdown(ui.station_header(s), unsafe_allow_html=True)
    t = terrain.terrain_at(s["lon"], s["lat"])
    st.markdown(
        f'<div style="font-size:11.5px;color:#9aa3ad;margin:2px 0 8px">'
        f'Elev {t["elevation_m"]:.0f} m · slope {t["slope_deg"]:.1f}° · '
        f'roughness {t["roughness"]:.2f} · {s["lon"]:.4f}, {s["lat"]:.4f}</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["Orbital · HiRISE", "Rover POV"])
    with tabs[0]:
        closeup = data.closeup_path(sid)
        if closeup:
            st.image(str(closeup), width="stretch",
                     caption="HiRISE mosaic close-up · ~0.6 m/px · Esri Astro/NASA")
        else:
            st.caption("No HiRISE close-up cached for this station.")
    with tabs[1]:
        pov = data.pov_image(sid)
        if pov:
            image, meta = pov
            cam = meta.get("camera", "Mastcam-Z / Navcam")
            st.image(image, width="stretch",
                     caption=f"Perseverance · sol {meta.get('sol', s['sol'])} · "
                             f"{cam} · NASA/JPL-Caltech")
        else:
            st.caption("No Perseverance image cached for this station.")

    st.markdown(station_science_html(sid), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------

layers = {
    "geology": show_geology,
    "slope": show_slope,
    "rough": show_rough,
    "hazard": show_hazard,
    "rover": show_rover,
    "ellipse": show_ellipse,
    "features": show_features,
}

focus_id = "S3"
if route and route.station_ids:
    focus_id = route.station_ids[-1]


def compass(deg: float) -> str:
    pts = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return pts[int((deg + 22.5) // 45) % 8]


if result and field_mode:
    first_id = route.station_ids[0]
    first = station_map[first_id]
    leg = route.legs[0]
    distance_m = leg["distance_km"] * 1000
    st.markdown(
        f'<div class="field-card">'
        f'<div class="k">Next waypoint · {html.escape(first["name"])}</div>'
        f'<div class="big">{compass(leg["bearing"])} {leg["bearing"]:.0f}° · '
        f'{distance_m:.0f} m</div>'
        f'<div class="sub">walk {ui.fmt_duration(distance_m / 1000 / speed)} · '
        f'max slope {leg["max_slope"]:.1f}° · {first_id} sol {first["sol"]} · '
        f'verdict <b>{result["verdict"]}</b></div></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([2.7, 1.0], gap="medium")
    with left:
        st_folium(build_map(route, layers, first_id), height=560,
                  use_container_width=True, returned_objects=[],
                  key="field_map")
    with right:
        st.markdown(ui.verdict_badge(result["verdict"], result["reason"]),
                    unsafe_allow_html=True)
        st.markdown('<div class="sect">Suit status</div>', unsafe_allow_html=True)
        st.markdown(ui.suit_bars(result["consumables"], reserve_pct / 100.0),
                    unsafe_allow_html=True)
        st.caption("Tap the map pins for station provenance.")
    st.markdown(ui.footer(), unsafe_allow_html=True)
    st.stop()


# normal PLAN layout -------------------------------------------------------

left, right = st.columns([2.55, 1.08], gap="medium")

with left:
    active_layers = ["CTX 4.83 m/px"]
    if show_geology:
        active_layers.append("USGS geology")
    if show_slope:
        active_layers.append("Slope")
    if show_rough:
        active_layers.append("Roughness")
    if show_hazard:
        active_layers.append("No-go")
    if show_rover:
        active_layers.append("Rover prior")
    st.markdown(
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'gap:12px;flex-wrap:wrap">'
        + ui.layer_chips(active_layers)
        + f'<div style="font-size:11.5px;color:#9aa3ad;margin-bottom:8px">'
          f'{len(ordered)} station(s) · {objective}</div></div>',
        unsafe_allow_html=True,
    )
    if route is not None:
        st_folium(build_map(route, layers, focus_id), height=610,
                  use_container_width=True, returned_objects=[], key="plan_map")
    else:
        st.info("No route yet — select stations and press Plan traverse.")
    st.caption(
        "Terrain: 200 m/px MOLA/HRSC DEM for slope; 4.8 m/px CTX texture for "
        "human-scale roughness. The DEM cannot resolve a metre-scale scarp, so "
        "roughness is used as a hazard proxy and hard no-go mask."
    )

with right:
    if result:
        st.markdown(ui.verdict_badge(result["verdict"], result["reason"]),
                    unsafe_allow_html=True)

        st.markdown('<div class="sect">Route</div>', unsafe_allow_html=True)
        s = route.stats
        st.markdown(
            ui.metric_grid([
                ("Distance", f"{s['distance_km']:.2f} km", "round trip"),
                ("Duration", ui.fmt_duration(s["duration_h"]), f"at {speed:.1f} km/h"),
                ("Ascent", f"{s['ascent_m']:.0f} m", f"descent {s['descent_m']:.0f} m"),
                ("Slope", f"{s['slope_p95']:.1f}°", f"p95 · peak {s['slope_max']:.1f}°"),
                ("Hazards", f"{s['hazard_crossings']}", "no-go samples on line"),
                ("Stations", f"{len(route.station_ids)}", "heritage stops"),
            ], cols=2),
            unsafe_allow_html=True,
        )

        st.markdown('<div class="sect">Suit budget</div>', unsafe_allow_html=True)
        st.markdown(ui.suit_bars(result["consumables"], reserve_pct / 100.0),
                    unsafe_allow_html=True)

        st.markdown('<div class="sect">Safety checks</div>', unsafe_allow_html=True)
        st.markdown(ui.checklist(result["constraints"]), unsafe_allow_html=True)

        st.markdown('<div class="sect">Weather &amp; dose</div>', unsafe_allow_html=True)
        st.markdown(
            ui.metric_grid([
                ("Dust", f"τ≈{result['tau']:.1f}" if result["tau"] is not None else "n/a",
                 "REMS opacity proxy"),
                ("EVA dose", f"{result['dose_mSv']:.3f} mSv",
                 f"{result['dose_pct_career']:.2f}% of career"),
            ], cols=2),
            unsafe_allow_html=True,
        )
        st.caption(
            f"{w['source']} · sol {w['sol']} ({w['earth_date']}). "
            "Gale Crater analog, not Jezero."
        )

        st.markdown('<div class="sect">Station detail</div>', unsafe_allow_html=True)
        detail_options = list(route.station_ids) if route.station_ids else list(STATION_ORDER)
        default_idx = detail_options.index(focus_id) if focus_id in detail_options else 0
        detail_id = st.selectbox("Inspect station", detail_options,
                                 index=default_idx, label_visibility="collapsed",
                                 key=f"detail::{objective}::{','.join(detail_options)}")
        station_card(detail_id)
    else:
        st.markdown(
            '<div class="card"><div class="k">Verdict</div>'
            '<div class="v">NO PLAN</div>'
            '<div class="s">Select at least one station, then plan the traverse.</div>'
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown(ui.footer(), unsafe_allow_html=True)
