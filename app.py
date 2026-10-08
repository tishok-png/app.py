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
  - A clean, light SaaS-style theme (white cards, purple accent)

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

# ---- palette (light SaaS style, purple accent) ----
PURPLE = "#6C5CE7"
PURPLE_LIGHT = "#EFEBFF"
GREEN = "#16C98D"
GREEN_LIGHT = "#E4FBF3"
RED = "#FF5C72"
RED_LIGHT = "#FFEAEE"
BLUE = "#4F8CFF"
BLUE_LIGHT = "#EAF1FF"
GRAY_LIGHT = "#F1F0F5"
TEXT_DARK = "#1F2430"
TEXT_MUTED = "#8A8FA3"

# Belt speed levels shown on the buttons, in cm/s. These are the physically
# MEASURED speeds (level 1 updated from measurement; 2 and 3 are still the
# original computed estimates) — they label the buttons for the operator and
# don't need to match the ESP's internal step-rate target exactly, only mean
# the same level 1/2/3 as sorter_pi_agent.py's BELT_SPEED_CM_S_BY_LEVEL.
SPEED_LEVELS = [(1, 3.75), (2, 6.2), (3, 7.4)]

# Machine status -> (icon, card background, accent color). Idle/Running/
# Calibration/Fault mirror the ESP's own reported state (see sorter_esp8266.ino).
STATUS_STYLE = {
    "Idle": ("⚪", GRAY_LIGHT, TEXT_MUTED),
    "Running": ("🟢", GREEN_LIGHT, GREEN),
    "Calibration": ("🛠️", BLUE_LIGHT, BLUE),
    "Fault": ("🔴", RED_LIGHT, RED),
}

GOOD_COLOR, BAD_COLOR, TOTAL_COLOR = GREEN, RED, PURPLE

# --------------------------------------------------------------------------
# Theme / styling - clean light SaaS look
# --------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');
    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
    h1, h2, h3, .stat-value {{ font-family: 'Plus Jakarta Sans', sans-serif !important; }}

    .stApp {{
        background: linear-gradient(135deg, #f2edff 0%, #eef1ff 45%, #fbfbff 100%);
    }}

    /* main content panel - the floating white "card" look */
    .block-container {{
        background: #ffffff;
        border-radius: 24px;
        padding: 2.2rem 2.5rem !important;
        box-shadow: 0 20px 50px rgba(108, 92, 231, 0.10);
        margin-top: 1rem;
    }}

    h1, h2, h3 {{ color: {TEXT_DARK} !important; font-weight: 800 !important; letter-spacing: -0.02em; }}
    p, span, label, .stCaption {{ color: {TEXT_DARK}; }}

    /* Sidebar - dark, like the reference design */
    [data-testid="stSidebar"] {{
        background: #14121f;
        border-right: none;
    }}
    [data-testid="stSidebar"] * {{ color: #f2f0fa !important; }}
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] [data-baseweb="select"] > div {{
        background-color: #1f1c33 !important;
        color: #f2f0fa !important;
        border: 1px solid #35304f !important;
        border-radius: 10px !important;
    }}
    [data-testid="stSidebar"] div.stButton > button {{
        background: #1f1c33; color: #f2f0fa !important; border: 1px solid #35304f !important;
    }}
    [data-testid="stSidebar"] div.stButton > button:hover {{ background: {PURPLE}; border-color: {PURPLE} !important; }}
    [data-testid="stSidebar"] hr {{ border-color: #2a2640 !important; }}

    /* Tabs styled as pill nav */
    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
    .stTabs [data-baseweb="tab"] {{
        background: {PURPLE_LIGHT}; border-radius: 12px; padding: 10px 18px;
        color: {PURPLE} !important; font-weight: 700;
    }}
    .stTabs [aria-selected="true"] {{
        background: {PURPLE} !important; color: white !important;
    }}
    .stTabs [aria-selected="true"] p {{ color: white !important; }}

    /* Buttons (main content area) */
    div.stButton > button {{
        font-size: 0.9rem !important;
        padding: 0.4rem 0.9rem !important;
        height: auto !important;
        border-radius: 999px !important;
        border: 1px solid #e4e0fa !important;
        background: #ffffff;
        color: {TEXT_DARK} !important;
        font-weight: 700 !important;
        transition: transform 0.12s ease, box-shadow 0.12s ease;
    }}
    div.stButton > button:hover {{ transform: translateY(-2px); box-shadow: 0 10px 24px rgba(108,92,231,0.18); }}
    div.stButton > button[kind="primary"] {{
        background: {PURPLE} !important; color: white !important; border: none !important;
    }}

    /* Small pill buttons - Connect / Disconnect only (START/STOP stay big) */
    .st-key-conn_btns div.stButton > button {{
        padding: 0.4rem 0.9rem !important;
        font-size: 0.85rem !important;
    }}
    .st-key-conn_btns div.stButton > button[kind="primary"] {{
        background: {PURPLE} !important; color: white !important;
    }}
    .st-key-conn_btns div[data-testid="column"]:last-child div.stButton > button {{
        color: {RED} !important; border-color: {RED} !important; background: {RED_LIGHT} !important;
    }}

    /* STOP button - same size as START now, just colored red */
    .st-key-stop_btn div.stButton > button {{
        background: {RED} !important; color: white !important; border: none !important;
    }}
    .st-key-stop_btn div.stButton > button:hover {{ box-shadow: 0 10px 24px rgba(255,92,114,0.28); }}

    /* CALIBRATE button - blue, matches the Calibration status color */
    .st-key-cal_btn div.stButton > button {{
        background: {BLUE} !important; color: white !important; border: none !important;
    }}
    .st-key-cal_btn div.stButton > button:hover {{ box-shadow: 0 10px 24px rgba(79,140,255,0.28); }}

    /* Custom stat cards - fixed, uniform size for all four */
    .stat-card {{
        background: #ffffff; border: 1px solid #f0eefc; border-radius: 18px;
        padding: 16px 18px; box-shadow: 0 8px 22px rgba(31,36,48,0.06);
        display: flex; align-items: center; gap: 14px;
        height: 92px; box-sizing: border-box; overflow: hidden;
    }}
    .stat-icon {{
        width: 44px; height: 44px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.3rem; flex-shrink: 0;
    }}
    .stat-label {{ font-size: 0.82rem; color: {TEXT_MUTED}; font-weight: 600; margin-bottom: 2px; white-space: nowrap; }}
    .stat-value {{ font-size: 1.6rem; font-weight: 800; line-height: 1.1; }}

    /* Big white "card" wrapper for the chart section and camera feed,
       styled like the reference dashboard's chart panel */
    .st-key-run_card, .st-key-cam_card {{
        background: #ffffff; border: 1px solid #f0eefc; border-radius: 20px;
        padding: 22px 24px 10px 24px; box-shadow: 0 8px 22px rgba(31,36,48,0.06);
        margin-top: 4px; margin-bottom: 18px;
    }}
    /* Keep camera image from growing too tall */
    .st-key-cam_card img {{
        max-height: 220px !important;
        object-fit: contain;
    }}
         
    .card-title {{ font-size: 0.9rem; color: {TEXT_MUTED}; font-weight: 700; margin-bottom: 2px; }}
    .card-total {{ font-size: 1.7rem; font-weight: 800; color: {TEXT_DARK}; margin-bottom: 4px; }}
    .legend-row {{ text-align: right; padding-top: 10px; font-weight: 600; color: {TEXT_DARK}; font-size: 0.88rem; }}
    .legend-dot {{
        display: inline-block; width: 12px; height: 12px; border-radius: 50%;
        border: 3px solid; margin-right: 4px; vertical-align: middle;
    }}

    /* Responsive: stack cleanly on narrow (phone) screens */
    @media (max-width: 768px) {{
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
        [data-testid="column"] {{ min-width: 100% !important; margin-bottom: 12px; }}
        .block-container {{ padding: 1.2rem !important; border-radius: 16px; }}
        .stat-value {{ font-size: 1.4rem; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def stat_card(icon: str, icon_bg: str, label: str, value, value_color=None):
    color_style = f"color:{value_color};" if value_color else f"color:{TEXT_DARK};"
    html = (
        f"<div class='stat-card'>"
        f"<div class='stat-icon' style='background:{icon_bg};'>{icon}</div>"
        f"<div><div class='stat-label'>{label}</div>"
        f"<div class='stat-value' style='{color_style}'>{value}</div>"
        f"</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _chart_theme(chart):
    return chart.configure_view(strokeWidth=0).configure_axis(
        gridColor="#f0eefc", domainColor="#e4e0fa", labelColor=TEXT_MUTED, titleColor=TEXT_MUTED,
    ).configure_legend(labelColor=TEXT_DARK, titleColor=TEXT_DARK)


def trend_chart(df: pd.DataFrame, height=280):
    long_df = df.melt(id_vars=["time"], value_vars=["good", "bad", "total"],
                       var_name="type", value_name="count")
    chart = (
        alt.Chart(long_df)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X("time:N", title="Time", axis=alt.Axis(labelAngle=-40)),
            y=alt.Y("count:Q", title="Seeds counted"),
            color=alt.Color(
                "type:N", title="",
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
        .mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=48)
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
    st.header("⚙️ Connection Settings")

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
        if st.button("🔌 Connect", use_container_width=True, type="primary"):
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
        if st.button("⛔ Disconnect", use_container_width=True):
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
            st.success("Connected ✅")
        else:
            st.error(f"Connection failed: {snap.get('error') or 'unknown error'}")

    st.divider()
    show_camera = st.checkbox("📷 Show camera feed", value=True)

    st.divider()
    n_sessions = len(st.session_state.sessions)
    st.caption(f"📜 **{n_sessions}** past session(s) logged — see the History tab.")
    if n_sessions:
        last = st.session_state.sessions[-1]
        st.caption(f"Last run: {last['good']} good / {last['bad']} bad "
                   f"({last['good_pct']:.1f}% good)")

    st.divider()
    st.caption(
        "**USB protocol** — in: `0`/`1` (bad/good, per-seed) · `GOOD`/`BAD` · "
        "`COUNTS:<g>,<b>` · `STATUS:IDLE/RUNNING/CALIBRATION/FAULT` · "
        "`DIVERTER:READY/DIVERTING` — out: `START`/`STOP`/`CALIBRATE`/"
        "`SPD1`/`SPD2`/`SPD3`/`SERVO50`/`SERVO100`/`SERVO150`/`SERVO180`\n\n"
        "**Cloud protocol** — Firebase keys: `good`, `bad` (running totals), "
        "`status` (Idle/Running/Calibration/Fault), `diverter` (Ready/Diverting), "
        "`camera_frame`, `command`.\n\n"
        "**Speed levels** — 3.75 / 6.2 / 7.4 cm/s (level 1 is measured; "
        "2 and 3 are still computed estimates)."
    )

# --------------------------------------------------------------------------
# Title + tabs
# --------------------------------------------------------------------------
st.markdown(
    f"<h1 style='color:{TEXT_DARK};'>🌽 Automated Seed Sorting Machine</h1>",
    unsafe_allow_html=True,
)
st.caption("Real-time monitoring and control interface for the automated maize seed sorting system.")

tab_live, tab_history = st.tabs(["📊 Live Dashboard", "📜 History"])

# --------------------------------------------------------------------------
# LIVE TAB
# --------------------------------------------------------------------------
with tab_live:

    @st.fragment(run_every=1)
    def live_dashboard():
        bridge = st.session_state.bridge
        if bridge is None:
            good, bad, status, diverter, cam_frame = 0, 0, "Idle", "Ready", None
        else:
            snap = bridge.get_snapshot()
            good, bad, status = snap["good"], snap["bad"], snap["status"]
            diverter = snap.get("diverter", "Ready")
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
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            icon, bg, color = STATUS_STYLE.get(status, STATUS_STYLE["Idle"])
            stat_card(
                icon, bg, "Machine Status",
                status if status in STATUS_STYLE else "Idle",
                value_color=color,
            )
        with col2:
            # Diverter is independent of Machine Status — it's the servo's
            # own moment-to-moment state, not the overall run state.
            if diverter == "Diverting":
                d_icon, d_bg, d_color = "🟡", BLUE_LIGHT, BLUE
            else:
                d_icon, d_bg, d_color = "⚪", GRAY_LIGHT, TEXT_MUTED
            stat_card(d_icon, d_bg, "Diverter", diverter, value_color=d_color)
        with col3:
            stat_card("✅", GREEN_LIGHT, "Good Seeds", good)
        with col4:
            stat_card("❌", RED_LIGHT, "Bad / Defective", bad)
        with col5:
            stat_card("🌽", PURPLE_LIGHT, "Total Counted", total)

        # ---- control row: progress bar + Start/Stop, right under the cards
        # (no scrolling needed to find these) ----
        prog_col, btn_col1, btn_col2 = st.columns([3, 1, 1])
        with prog_col:
            st.write("")
            st.progress(min(good_pct / 100, 1.0), text=f"Good seed rate: {good_pct:.1f}% (of {total} sorted)")
        with btn_col1:
            st.write("")
            if st.button("▶️  START", use_container_width=True, type="primary"):
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
            if stop_container.button("⏹️  STOP", use_container_width=True):
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
        speed_cols = st.columns([1, 1, 1, 1.3])
        for col, (level, cms) in zip(speed_cols[:3], SPEED_LEVELS):
            with col:
                if st.button(f"⚙️ {cms:.2f} cm/s", use_container_width=True, key=f"spd_{level}"):
                    bridge = st.session_state.bridge
                    if bridge is None:
                        st.error("Connect to the machine first (see sidebar).")
                    else:
                        ok = bridge.send_command(f"SPD{level}")
                        if ok:
                            st.toast(f"Speed set to {cms:.2f} cm/s", icon="⚙️")
                        else:
                            st.error("Failed to send speed command.")
        with speed_cols[3]:
            cal_container = st.container(key="cal_btn")
            if cal_container.button("🛠️  CALIBRATE", use_container_width=True):
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

        # ---- third control row: manual servo-angle bring-up test, only
        # meaningful (and only allowed on the Pi side) while Idle ----
        st.caption("Servo bring-up test — moves the gate directly, bypassing the FIFO. Only works while Idle.")
        servo_cols = st.columns(4)
        servo_disabled = status != "Idle"
        for col, angle in zip(servo_cols, (50, 100, 150, 180)):
            with col:
                if st.button(f"🔧 {angle}°", use_container_width=True,
                             key=f"servo_{angle}", disabled=servo_disabled):
                    bridge = st.session_state.bridge
                    if bridge is None:
                        st.error("Connect to the machine first (see sidebar).")
                    else:
                        ok = bridge.send_command(f"SERVO{angle}")
                        if ok:
                            st.toast(f"Servo moved to {angle}°", icon="🔧")
                        else:
                            st.error("Failed to send servo test command.")

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
                    f"<div class='card-title'>Current Run</div>"
                    f"<div class='card-total'>{total} "
                    f"<span style='font-size:0.95rem;color:{TEXT_MUTED};font-weight:600;'>seeds sorted</span></div>",
                    unsafe_allow_html=True,
                )
            with head_r:
                st.markdown(
                    f"<div class='legend-row'>"
                    f"<span class='legend-dot' style='border-color:{GREEN};'></span> Good&nbsp;&nbsp;&nbsp;"
                    f"<span class='legend-dot' style='border-color:{RED};'></span> Bad</div>",
                    unsafe_allow_html=True,
                )
            st.altair_chart(trend_chart(df, height=260), use_container_width=True)
            st.altair_chart(good_bad_bar(good, bad, height=180), use_container_width=True)
            if not series:
                st.caption("Press START to begin logging this run — it'll be saved to History once you press STOP.")

        # ---- camera feed (optional - toggle in sidebar) ----
        if show_camera:
            cam_card = st.container(key="cam_card")
            with cam_card:
                st.markdown("<div class='card-title'>📷 Live Camera Feed</div>", unsafe_allow_html=True)
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
    st.subheader("📜 Past Sorting Sessions")

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
            "⬇️ Download all sessions (CSV)", data=all_csv,
            file_name=f"seed_sorting_sessions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        st.divider()
        options = [f"Session {s['id']} — {s['start_dt'].strftime('%Y-%m-%d %H:%M')}" for s in sessions]
        pick = st.selectbox("View details for a specific session:", options[::-1])
        chosen = sessions[options.index(pick)]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            stat_card("✅", GREEN_LIGHT, "Good", chosen["good"])
        with c2:
            stat_card("❌", RED_LIGHT, "Bad", chosen["bad"])
        with c3:
            stat_card("🌽", PURPLE_LIGHT, "Total", chosen["total"])
        with c4:
            stat_card("📈", BLUE_LIGHT, "Good rate", f"{chosen['good_pct']:.1f}%")

        st.write("")
        if chosen["series"]:
            sdf = pd.DataFrame(chosen["series"])
            gcol, bcol = st.columns([2, 1])
            with gcol:
                st.altair_chart(trend_chart(sdf), use_container_width=True)
            with bcol:
                st.altair_chart(good_bad_bar(chosen["good"], chosen["bad"]), use_container_width=True)

            session_csv = sdf.to_csv(index=False).encode("utf-8")
            st.download_button(
                f"⬇️ Download Session {chosen['id']} detail (CSV)", data=session_csv,
                file_name=f"seed_sorting_session_{chosen['id']}.csv", mime="text/csv",
            )
        else:
            st.caption("No detailed readings were logged during this session.")
