"""
app.py - Operator Monitoring & Control Dashboard
Automated Seed Sorting System

Built with Streamlit, per Chapter 3 (3.3 - 3.4), extended with:
  - Total maize counted
  - A live camera feed (good/bad labelled frames from the Pi)
  - Session-based history: every START->STOP run is saved as a session
    you can browse afterwards, each with its own graph + CSV download
  - Clean Altair graphs (trend line + good-vs-bad bar)
  - Three connection modes: Simulation, Live (USB serial), and
    Cloud (WiFi, over the internet - works from a phone anywhere)
  - A clean, professional light dashboard theme (white panels, teal accent)

Run with:
    streamlit run app.py
"""

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from serial_bridge import SerialBridge, SimulationBridge
from cloud_bridge import CloudBridge

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="Seed Sorting Control Dashboard",
    page_icon="🌽",
    layout="wide",
)

if "bridge" not in st.session_state:
    st.session_state.bridge = None
if "mode" not in st.session_state:
    st.session_state.mode = "Simulation (no hardware)"
if "live_series" not in st.session_state:
    st.session_state.live_series = []       # time series for the CURRENT run
if "sessions" not in st.session_state:
    st.session_state.sessions = []          # completed runs, newest last
if "active_session" not in st.session_state:
    st.session_state.active_session = None  # {"start_dt","start_good","start_bad"}
if "last_run_series" not in st.session_state:
    st.session_state.last_run_series = []   # keeps the graph line visible after STOP

# ---- palette (neutral canvas, white cards, teal accent) ----
CANVAS = "#F3F5F8"
LINE = "#E2E8F0"
ACCENT = "#0F766E"
GREEN = "#1A9D6B"
RED = "#D64545"
RED_LIGHT = "#FDECEC"
BLUE = "#2563EB"
SLATE = "#475569"
TEXT_DARK = "#0F172A"
TEXT_MUTED = "#64748B"

# Belt speed levels, in cm/s — must match BELT_SPEED_CM_S in sorter_esp8266.ino
SPEED_LEVELS = [(1, 3.14), (2, 6.2), (3, 7.4)]

# Machine status -> indicator color. Idle/Running/Calibration/Fault mirror the
# ESP's own reported state (see sorter_esp8266.ino).
STATUS_STYLE = {
    "Idle": TEXT_MUTED,
    "Running": GREEN,
    "Calibration": BLUE,
    "Fault": RED,
}

GOOD_COLOR, BAD_COLOR, TOTAL_COLOR = GREEN, RED, SLATE

# --------------------------------------------------------------------------
# Theme / styling - neutral operations-dashboard look
# --------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
    html, body, .stApp, [class*="css"], button, input, textarea, select {{
        font-family: 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif;
    }}
    .stApp {{ background: {CANVAS}; color: {TEXT_DARK}; }}
    header[data-testid="stHeader"] {{ background: transparent; }}
    footer {{ visibility: hidden; }}
    .block-container {{ max-width: 1400px; padding: 2rem 2.5rem 3rem !important; }}

    h1, h2, h3 {{ color: {TEXT_DARK} !important; font-weight: 600 !important; letter-spacing: -0.01em; }}
    p, label, .stCaption {{ color: {TEXT_DARK}; }}
    [data-testid="stCaptionContainer"] p {{ color: {TEXT_MUTED} !important; }}

    .page-head {{ padding-bottom: 14px; margin-bottom: 8px; border-bottom: 1px solid {LINE}; }}
    .page-head h1 {{ font-size: 1.55rem; margin: 0 0 4px 0 !important; padding: 0 !important; }}
    .page-head p {{ margin: 0; color: {TEXT_MUTED}; font-size: 0.92rem; }}

    /* ---------- Sidebar ---------- */
    [data-testid="stSidebar"] {{ background: #0F1724; border-right: 1px solid #1B2638; }}
    [data-testid="stSidebar"] * {{ color: #E6EBF2 !important; }}
    [data-testid="stSidebar"] h2 {{ font-size: 1rem !important; font-weight: 600 !important; }}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color: #93A1B5 !important; font-size: 0.78rem; }}
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] [data-baseweb="select"] > div {{
        background-color: #172033 !important; border: 1px solid #263248 !important; border-radius: 8px !important;
    }}
    [data-testid="stSidebar"] hr {{ border-color: #1F2A3C !important; }}
    [data-testid="stSidebar"] div.stButton > button {{
        background: #172033; color: #E6EBF2 !important; border: 1px solid #2A3750 !important; box-shadow: none;
    }}
    [data-testid="stSidebar"] div.stButton > button:hover {{ background: #1D2940; border-color: #3B4B69 !important; }}
    [data-testid="stSidebar"] div.stButton > button[kind="primary"],
    [data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-primary"] {{
        background: {ACCENT}; border-color: {ACCENT} !important; color: #ffffff !important;
    }}
    .st-key-conn_btns [data-testid="stColumn"]:last-child div.stButton > button,
    .st-key-conn_btns [data-testid="column"]:last-child div.stButton > button {{
        background: transparent !important; color: #FF8A8A !important; border-color: #6B2D33 !important;
    }}

    /* ---------- Tabs: underline style ---------- */
    .stTabs [data-baseweb="tab-list"] {{ gap: 26px; border-bottom: 1px solid {LINE}; }}
    .stTabs [data-baseweb="tab"] {{ background: transparent; padding: 10px 2px; height: auto; }}
    .stTabs [data-baseweb="tab"] p {{ color: {TEXT_MUTED}; font-weight: 500; font-size: 0.95rem; }}
    .stTabs [aria-selected="true"] p {{ color: {TEXT_DARK}; font-weight: 600; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background-color: {ACCENT} !important; height: 2px; }}
    .stTabs [data-baseweb="tab-border"] {{ background-color: transparent !important; }}

    /* ---------- Buttons ---------- */
    div.stButton > button, div.stDownloadButton > button {{
        font-size: 0.9rem !important; font-weight: 600 !important;
        min-height: 40px; height: auto !important; padding: 0.4rem 1rem !important;
        border-radius: 8px !important; border: 1px solid #CBD5E1 !important;
        background: #ffffff; color: {TEXT_DARK} !important;
        box-shadow: 0 1px 2px rgba(15,23,42,0.05); transition: background 0.12s ease, border-color 0.12s ease;
    }}
    div.stButton > button p, div.stDownloadButton > button p {{ color: inherit !important; font-weight: 600; }}
    div.stButton > button:hover, div.stDownloadButton > button:hover {{ background: #F8FAFC; border-color: #94A3B8 !important; }}
    div.stButton > button[kind="primary"],
    div.stButton > button[data-testid="stBaseButton-primary"] {{
        background: {ACCENT}; color: #ffffff !important; border: none !important;
    }}
    div.stButton > button[kind="primary"]:hover,
    div.stButton > button[data-testid="stBaseButton-primary"]:hover {{ background: #115E59; }}
    .st-key-stop_btn div.stButton > button {{ background: {RED}; color: #ffffff !important; border: none !important; }}
    .st-key-stop_btn div.stButton > button:hover {{ background: #B93A3A; }}
    .st-key-cal_btn div.stButton > button {{ background: {BLUE}; color: #ffffff !important; border: none !important; }}
    .st-key-cal_btn div.stButton > button:hover {{ background: #1D4FC4; }}

    /* ---------- KPI cards ---------- */
    .kpi {{
        background: #ffffff; border: 1px solid {LINE}; border-radius: 10px;
        padding: 14px 18px; min-height: 88px; box-sizing: border-box;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04);
    }}
    .kpi-label {{ display: flex; align-items: center; gap: 8px; font-size: 0.82rem; color: {TEXT_MUTED}; font-weight: 500; margin-bottom: 6px; }}
    .kpi-mark {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    .kpi-value {{ font-size: 1.75rem; font-weight: 600; line-height: 1.1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}

    /* ---------- Panels (controls, chart, camera, history) ---------- */
    .st-key-ctrl_card, .st-key-run_card, .st-key-cam_card, .st-key-hist_card {{
        background: #ffffff; border: 1px solid {LINE}; border-radius: 10px;
        padding: 18px 20px; box-shadow: 0 1px 2px rgba(15,23,42,0.04);
        margin: 4px 0 14px 0;
    }}
    .st-key-cam_card img {{ max-height: 220px !important; object-fit: contain; }}

    .card-title {{ font-size: 0.85rem; color: {TEXT_MUTED}; font-weight: 500; }}
    .card-total {{ font-size: 1.6rem; font-weight: 600; letter-spacing: -0.02em; color: {TEXT_DARK}; font-variant-numeric: tabular-nums; }}
    .card-unit {{ font-size: 0.9rem; color: {TEXT_MUTED}; font-weight: 500; letter-spacing: 0; }}
    .legend-row {{ text-align: right; padding-top: 8px; font-weight: 500; color: {TEXT_DARK}; font-size: 0.85rem; }}
    .legend-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin: 0 5px 0 14px; vertical-align: middle; }}
    .ctrl-label {{ font-size: 0.85rem; color: {TEXT_MUTED}; font-weight: 500; padding-top: 9px; }}

    .stProgress [data-baseweb="progress-bar"] > div {{ background: #E6EAF0 !important; border-radius: 999px; }}
    .stProgress [data-baseweb="progress-bar"] > div > div {{ background: {GREEN} !important; border-radius: 999px; }}
    [data-testid="stDataFrame"] {{ border: 1px solid {LINE}; border-radius: 10px; overflow: hidden; }}
    [data-testid="stAlert"] {{ border-radius: 8px; }}

    /* Responsive: stack cleanly on narrow (phone) screens */
    @media (max-width: 768px) {{
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
        [data-testid="column"], [data-testid="stColumn"] {{ min-width: 100% !important; margin-bottom: 12px; }}
        .block-container {{ padding: 1.2rem 1rem !important; }}
        .kpi-value {{ font-size: 1.4rem; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def stat_card(label: str, value, marker: str, value_color=None):
    color_style = f"color:{value_color};" if value_color else f"color:{TEXT_DARK};"
    html = (
        f"<div class='kpi'>"
        f"<div class='kpi-label'><span class='kpi-mark' style='background:{marker};'></span>{label}</div>"
        f"<div class='kpi-value' style='{color_style}'>{value}</div>"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


CHART_FONT = "IBM Plex Sans, sans-serif"


def _chart_theme(chart):
    return chart.configure_view(strokeWidth=0).configure_axis(
        gridColor=LINE, domainColor="#CBD5E1", tickColor="#CBD5E1",
        labelColor=TEXT_MUTED, titleColor=TEXT_MUTED,
        labelFont=CHART_FONT, titleFont=CHART_FONT,
        labelFontSize=11, titleFontSize=11, titleFontWeight=500,
    ).configure_legend(
        labelColor=TEXT_DARK, titleColor=TEXT_DARK, labelFont=CHART_FONT,
        labelFontSize=12, orient="top",
    )


def trend_chart(df: pd.DataFrame, height=280, legend=True):
    long_df = df.melt(id_vars=["time"], value_vars=["good", "bad", "total"],
                       var_name="type", value_name="count")
    chart = (
        alt.Chart(long_df)
        .mark_line(point=alt.OverlayMarkDef(size=36), strokeWidth=2)
        .encode(
            x=alt.X("time:N", title="Time", axis=alt.Axis(labelAngle=-40)),
            y=alt.Y("count:Q", title="Seeds counted"),
            color=alt.Color(
                "type:N", title="",
                legend=alt.Legend() if legend else None,
                scale=alt.Scale(domain=["good", "bad", "total"],
                                 range=[GOOD_COLOR, BAD_COLOR, TOTAL_COLOR]),
            ),
            tooltip=["time", "type", "count"],
        )
        .properties(height=height, background="white")
        .interactive()
    )
    return _chart_theme(chart)


def good_bad_bar(good: int, bad: int, height=240):
    df = pd.DataFrame({"Category": ["Good", "Bad"], "Count": [good, bad]})
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=44)
        .encode(
            x=alt.X("Category:N", title=""),
            y=alt.Y("Count:Q", title="Seeds"),
            color=alt.Color(
                "Category:N", legend=None,
                scale=alt.Scale(domain=["Good", "Bad"], range=[GOOD_COLOR, BAD_COLOR]),
            ),
            tooltip=["Category", "Count"],
        )
        .properties(height=height, background="white")
    )
    return _chart_theme(chart)


def start_new_session(good: int, bad: int):
    st.session_state.active_session = {
        "start_dt": datetime.now(),
        "start_good": good,
        "start_bad": bad,
    }
    st.session_state.live_series = []
    st.session_state.last_run_series = []


def end_active_session(good: int, bad: int):
    active = st.session_state.active_session
    if not active:
        return
    session_good = good - active["start_good"]
    session_bad = bad - active["start_bad"]
    session_total = session_good + session_bad
    st.session_state.sessions.append({
        "id": len(st.session_state.sessions) + 1,
        "start_dt": active["start_dt"],
        "end_dt": datetime.now(),
        "good": session_good,
        "bad": session_bad,
        "total": session_total,
        "good_pct": (session_good / session_total * 100) if session_total else 0.0,
        "series": list(st.session_state.live_series),
    })
    st.session_state.last_run_series = list(st.session_state.live_series)
    st.session_state.active_session = None
    st.session_state.live_series = []


# --------------------------------------------------------------------------
# Sidebar - connection settings
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Connection")

    mode_options = [
        "Simulation (no hardware)",
        "Live (Raspberry Pi over USB)",
        "Cloud (WiFi - check from anywhere)",
    ]
    mode = st.radio(
        "Mode", mode_options, index=mode_options.index(st.session_state.mode),
        help="Simulation: demo with fake data.\nLive: wired by USB, same computer.\n"
             "Cloud: Pi + dashboard talk over the internet via Firebase - works "
             "from your phone, from anywhere.",
    )
    st.session_state.mode = mode

    port, baud, db_url = None, None, None
    if mode.startswith("Live"):
        port = st.text_input("Serial port", value="COM3",
                              help="e.g. COM3 on Windows, /dev/ttyACM0 on Linux/Pi.")
        baud = st.number_input("Baud rate", value=9600, step=1)
    elif mode.startswith("Cloud"):
        db_url = st.text_input(
            "Firebase Database URL", value="",
            placeholder="https://your-project-id-default-rtdb.firebaseio.com",
            help="From the Firebase Console -> Realtime Database.",
        )

    conn_container = st.container(key="conn_btns")
    col_a, col_b = conn_container.columns(2)
    with col_a:
        if st.button("Connect", use_container_width=True, type="primary"):
            if st.session_state.bridge:
                st.session_state.bridge.disconnect()
            if mode.startswith("Live"):
                bridge = SerialBridge(port, int(baud))
            elif mode.startswith("Cloud"):
                bridge = CloudBridge(db_url) if db_url else None
                if bridge is None:
                    st.error("Enter your Firebase Database URL first.")
            else:
                bridge = SimulationBridge()
            if bridge is not None:
                bridge.connect()
                st.session_state.bridge = bridge
    with col_b:
        if st.button("Disconnect", use_container_width=True):
            if st.session_state.bridge:
                st.session_state.bridge.disconnect()
            st.session_state.bridge = None

    st.divider()
    bridge = st.session_state.bridge
    if bridge is None:
        st.warning("Not connected yet. Click **Connect** above.")
    else:
        snap = bridge.get_snapshot()
        if snap["connected"]:
            st.success("Connected")
        else:
            st.error(f"Connection failed: {snap.get('error') or 'unknown error'}")

    st.divider()
    show_camera = st.checkbox("Show camera feed", value=True)

    st.divider()
    n_sessions = len(st.session_state.sessions)
    st.caption(f"**{n_sessions}** past session(s) logged — see the History tab.")
    if n_sessions:
        last = st.session_state.sessions[-1]
        st.caption(f"Last run: {last['good']} good / {last['bad']} bad "
                   f"({last['good_pct']:.1f}% good)")

    st.divider()
    st.caption(
        "**USB protocol** — in: `0`/`1` (bad/good, per-seed) · `GOOD`/`BAD` · "
        "`COUNTS:<g>,<b>` · `STATUS:IDLE/RUNNING/CALIBRATION/FAULT` — "
        "out: `START`/`STOP`/`CALIBRATE`/`SPD1`/`SPD2`/`SPD3`\n\n"
        "**Cloud protocol** — Firebase keys: `good`, `bad` (running totals), "
        "`status` (Idle/Running/Calibration/Fault), `camera_frame`, `command`.\n\n"
        "**Speed levels** — 3.14 / 6.2 / 7.4 cm/s."
    )

# --------------------------------------------------------------------------
# Title + tabs
# --------------------------------------------------------------------------
st.markdown(
    "<div class='page-head'><h1>Automated Seed Sorting Machine</h1>"
    "<p>Real-time monitoring and control interface for the automated maize seed sorting system.</p></div>",
    unsafe_allow_html=True,
)

tab_live, tab_history = st.tabs(["Live dashboard", "History"])

# --------------------------------------------------------------------------
# LIVE TAB
# --------------------------------------------------------------------------
with tab_live:

    @st.fragment(run_every=1)
    def live_dashboard():
        bridge = st.session_state.bridge
        if bridge is None:
            good, bad, status, cam_frame = 0, 0, "Idle", None
        else:
            snap = bridge.get_snapshot()
            good, bad, status = snap["good"], snap["bad"], snap["status"]
            cam_frame = snap.get("camera_frame")

        total = good + bad
        good_pct = (good / total * 100) if total else 0.0

        # record this run's time series (only while a session is active)
        series = st.session_state.live_series
        if st.session_state.active_session and (
            not series or series[-1]["good"] != good or series[-1]["bad"] != bad
        ):
            series.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "good": good, "bad": bad, "total": total,
            })

        # ---- metrics row (matching stat-card style) ----
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            status_color = STATUS_STYLE.get(status, STATUS_STYLE["Idle"])
            stat_card("Machine status", status if status in STATUS_STYLE else "Idle",
                      status_color, value_color=status_color)
        with col2:
            stat_card("Good seeds", good, GREEN)
        with col3:
            stat_card("Bad / defective", bad, RED)
        with col4:
            stat_card("Total counted", total, TOTAL_COLOR)

        # ---- control row: progress bar + Start/Stop, right under the cards
        # (no scrolling needed to find these) ----
        with st.container(key="ctrl_card"):
            prog_col, btn_col1, btn_col2 = st.columns([3, 1, 1])
            with prog_col:
                st.write("")
                st.progress(min(good_pct / 100, 1.0), text=f"Good seed rate: {good_pct:.1f}% (of {total} sorted)")
            with btn_col1:
                st.write("")
                if st.button("Start", use_container_width=True, type="primary"):
                    bridge = st.session_state.bridge
                    if bridge is None:
                        st.error("Connect to the machine first (see sidebar).")
                    else:
                        snap = bridge.get_snapshot()
                        ok = bridge.send_command("START")
                        if ok:
                            if not st.session_state.active_session:
                                start_new_session(snap["good"], snap["bad"])
                            st.toast("START command sent — new session logging began", icon="✅")
                        else:
                            st.error("Failed to send START command.")
            with btn_col2:
                st.write("")
                stop_container = st.container(key="stop_btn")
                if stop_container.button("Stop", use_container_width=True):
                    bridge = st.session_state.bridge
                    if bridge is None:
                        st.error("Connect to the machine first (see sidebar).")
                    else:
                        snap = bridge.get_snapshot()
                        ok = bridge.send_command("STOP")
                        if ok:
                            end_active_session(snap["good"], snap["bad"])
                            st.toast("STOP command sent — session saved to History", icon="🛑")
                        else:
                            st.error("Failed to send STOP command.")

            if status == "Fault":
                st.error("⚠️ Machine is in FAULT — press STOP to clear it before starting again.")

            # ---- second control row: belt speed (3 fixed levels) + Calibrate,
            # right under Start/Stop so both are reachable without scrolling ----
            speed_cols = st.columns([0.9, 1, 1, 1, 1.3])
            with speed_cols[0]:
                st.markdown("<div class='ctrl-label'>Belt speed</div>", unsafe_allow_html=True)
            for col, (level, cms) in zip(speed_cols[1:4], SPEED_LEVELS):
                with col:
                    if st.button(f"{cms:.2f} cm/s", use_container_width=True, key=f"spd_{level}"):
                        bridge = st.session_state.bridge
                        if bridge is None:
                            st.error("Connect to the machine first (see sidebar).")
                        else:
                            ok = bridge.send_command(f"SPD{level}")
                            if ok:
                                st.toast(f"Speed set to {cms:.2f} cm/s", icon="⚙️")
                            else:
                                st.error("Failed to send speed command.")
            with speed_cols[4]:
                cal_container = st.container(key="cal_btn")
                if cal_container.button("Calibrate", use_container_width=True):
                    bridge = st.session_state.bridge
                    if bridge is None:
                        st.error("Connect to the machine first (see sidebar).")
                    else:
                        ok = bridge.send_command("CALIBRATE")
                        if ok:
                            st.toast(
                                "Calibration started — belt + singulator run continuously "
                                "at the lowest speed until STOP is pressed", icon="🛠️",
                            )
                        else:
                            st.error("Failed to send CALIBRATE command.")

        # ---- current-run chart, wrapped in one clean card (title + total +
        # legend on top, chart underneath) like the reference dashboard ----
        if series:
            df = pd.DataFrame(series)
        elif st.session_state.last_run_series:
            df = pd.DataFrame(st.session_state.last_run_series)
        else:
            df = pd.DataFrame([{
                "time": datetime.now().strftime("%H:%M:%S"),
                "good": good, "bad": bad, "total": total,
            }])

        run_card = st.container(key="run_card")
        with run_card:
            head_l, head_r = st.columns([2, 1])
            with head_l:
                st.markdown(
                    f"<div class='card-title'>Current run</div>"
                    f"<div class='card-total'>{total} <span class='card-unit'>seeds sorted</span></div>",
                    unsafe_allow_html=True,
                )
            with head_r:
                st.markdown(
                    f"<div class='legend-row'>"
                    f"<span class='legend-dot' style='background:{GOOD_COLOR};'></span>Good"
                    f"<span class='legend-dot' style='background:{BAD_COLOR};'></span>Bad"
                    f"<span class='legend-dot' style='background:{TOTAL_COLOR};'></span>Total</div>",
                    unsafe_allow_html=True,
                )
            chart_l, chart_r = st.columns([2, 1])
            with chart_l:
                st.altair_chart(trend_chart(df, height=280, legend=False), use_container_width=True)
            with chart_r:
                st.altair_chart(good_bad_bar(good, bad, height=280), use_container_width=True)
            if not series:
                st.caption("Press START to begin logging this run — it'll be saved to History once you press STOP.")

        # ---- camera feed (optional - toggle in sidebar) ----
        if show_camera:
            cam_card = st.container(key="cam_card")
            with cam_card:
                st.markdown("<div class='card-title'>Live camera feed</div>", unsafe_allow_html=True)
                if cam_frame:
                    try:
                        import base64
                        img_bytes = base64.b64decode(cam_frame)
                        st.image(img_bytes, caption="Labelled feed from the Pi (0 = bad, 1 = good)",
                                  use_container_width=True)
                    except Exception:
                        st.info("Camera frame received but could not be decoded.")
                else:
                    st.info("No camera frame yet — waiting for the Pi/vision script to publish one.")

    live_dashboard()

# --------------------------------------------------------------------------
# HISTORY TAB
# --------------------------------------------------------------------------
with tab_history:
    st.subheader("Past sorting sessions")

    sessions = st.session_state.sessions
    if not sessions:
        st.info("No completed sessions yet. Run the machine (START → STOP) on the "
                 "Live Dashboard tab, and each run will show up here afterward.")
    else:
        summary_rows = [{
            "Session": s["id"],
            "Start": s["start_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            "End": s["end_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            "Good": s["good"], "Bad": s["bad"], "Total": s["total"],
            "Good %": round(s["good_pct"], 1),
        } for s in sessions]
        summary_df = pd.DataFrame(summary_rows)

        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        all_csv = summary_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download all sessions (CSV)", data=all_csv,
            file_name=f"seed_sorting_sessions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        st.divider()
        options = [f"Session {s['id']} — {s['start_dt'].strftime('%Y-%m-%d %H:%M')}" for s in sessions]
        pick = st.selectbox("View details for a specific session:", options[::-1])
        chosen = sessions[options.index(pick)]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            stat_card("Good", chosen["good"], GREEN)
        with c2:
            stat_card("Bad", chosen["bad"], RED)
        with c3:
            stat_card("Total", chosen["total"], TOTAL_COLOR)
        with c4:
            stat_card("Good rate", f"{chosen['good_pct']:.1f}%", BLUE)

        st.write("")
        if chosen["series"]:
            sdf = pd.DataFrame(chosen["series"])
            with st.container(key="hist_card"):
                gcol, bcol = st.columns([2, 1])
                with gcol:
                    st.altair_chart(trend_chart(sdf, height=260), use_container_width=True)
                with bcol:
                    st.altair_chart(good_bad_bar(chosen["good"], chosen["bad"], height=260), use_container_width=True)

            session_csv = sdf.to_csv(index=False).encode("utf-8")
            st.download_button(
                f"Download session {chosen['id']} detail (CSV)", data=session_csv,
                file_name=f"seed_sorting_session_{chosen['id']}.csv", mime="text/csv",
            )
        else:
            st.caption("No detailed readings were logged during this session.")
