import base64
import streamlit as st
import plotly.graph_objects as go
from PIL import Image
import pandas as pd
import numpy as np
import datetime
import os
import re
import json
import streamlit.components.v1 as components

st.set_page_config(page_title="NASA Space Monitoring Interface", layout="wide", initial_sidebar_state="expanded")

DEFAULT_STATES = {
    "menu": "Users",
    "records_df": pd.DataFrame(columns=[
        "Date", "Time", "Crew Member", "View", "Zone", "Details / Metrics", "Notes"
    ]),
    "heart_alert_state": None,
    "nose_alert_state": None,
    "hand_alert_state": None,
    "leg_alert_state": None,
    "missions": {},
    "selected_crew_sidebar": "No Crew Members Available",
    "uploaded_images": {},
    "map_view": "body",
    "selected_zone": "Forehead",
    "history_map_view": "body",
    "history_selected_zone": "Heart",
    "default_radiation": float(np.round(np.random.uniform(0.1, 0.9), 2)),
    "pending_emergency_handoff": None,
    "active_emergency_banner": None,
    "prev_problem": None,
    "prev_cause": None,
    "prevention_log": [],
    "habits_done": {},
    "prevention_nudge": None,
}

for key, val in DEFAULT_STATES.items():
    if key not in st.session_state:
        st.session_state[key] = val

NASA_TEMP_CRITICAL_LOW = 35.0
NASA_TEMP_NOMINAL_LOW = 36.0
NASA_TEMP_NOMINAL_HIGH = 38.0
NASA_TEMP_CRITICAL_HIGH = 39.5

NASA_EXERCISE_DAILY_TARGET = 2.0
NASA_EXERCISE_WEEKLY_MIN_DAYS = 6
NASA_EXERCISE_WEEKLY_TARGET_HRS = NASA_EXERCISE_DAILY_TARGET * NASA_EXERCISE_WEEKLY_MIN_DAYS
NASA_BMD_HIP_SPINE_MIN = 95.0
NASA_BMD_FEMORAL_NECK_MIN = 90.0
NASA_BMD_CRITICAL_FRACTURE = 85.0


@st.cache_data
def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


@st.cache_data
def load_inverted_image(path: str) -> Image.Image:
    img = Image.open(path)
    rgba = np.array(img.convert("RGBA"))
    r, g, b, a = rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2], rgba[:, :, 3]
    dark_stroke = (a > 0) & (r < 128) & (g < 128) & (b < 128)
    rgba[dark_stroke, 0] = 255
    rgba[dark_stroke, 1] = 255
    rgba[dark_stroke, 2] = 255
    return Image.fromarray(rgba, mode="RGBA")


def extract_metrics_from_text(text: str) -> dict:
    parsed = {}
    if not isinstance(text, str):
        return parsed
    for part in text.split("|"):
        if ":" in part:
            key, val = part.split(":", 1)
            match = re.search(r"[-+]?\d*\.?\d+", val)
            if match:
                parsed[key.strip()] = float(match.group())
    return parsed


def get_crew_baseline_bmd(crew_member: str) -> float:
    for mission_data in st.session_state.missions.values():
        for user in mission_data.get("users", []):
            if user.get("name") == crew_member:
                return float(user.get("baseline_bmd", 1.10))
    return 1.10


def get_cumulative_radiation(df: pd.DataFrame, crew_member: str) -> float:
    if df.empty or "Crew Member" not in df.columns or "Details / Metrics" not in df.columns:
        return 0.0
    crew_df = df[(df["Crew Member"] == crew_member) & (df["Zone"] == "Forehead")]
    total = 0.0
    for text in crew_df["Details / Metrics"]:
        metrics = extract_metrics_from_text(text)
        if "Radiation" in metrics:
            total += metrics["Radiation"]
    return round(total, 2)


def get_weekly_exercise_summary(df: pd.DataFrame, crew_member: str, ref_date: datetime.date) -> dict:
    if df.empty or "Zone" not in df.columns:
        return {"days_active": 0, "total_hours": 0.0}
    leg_df = df[(df["Crew Member"] == crew_member) & (df["Zone"] == "Leg")].copy()
    if leg_df.empty:
        return {"days_active": 0, "total_hours": 0.0}

    start_date = ref_date - datetime.timedelta(days=6)
    daily_hours = {}
    for _, row in leg_df.iterrows():
        if "Pre-mission baseline" in str(row.get("Notes", "")):
            continue
        try:
            d = datetime.date.fromisoformat(str(row["Date"]))
        except ValueError:
            continue
        if start_date <= d <= ref_date:
            metrics = extract_metrics_from_text(str(row.get("Details / Metrics", "")))
            hrs = metrics.get("Exercise", 0.0)
            daily_hours[d] = daily_hours.get(d, 0.0) + hrs

    days_meeting_goal = sum(1 for h in daily_hours.values() if h >= NASA_EXERCISE_DAILY_TARGET)
    total_hours = round(sum(daily_hours.values()), 2)
    return {"days_active": days_meeting_goal, "total_hours": total_hours}


def get_mood_schedule_df(df: pd.DataFrame, crew_member: str = None) -> pd.DataFrame:
    if df.empty or "Zone" not in df.columns:
        return pd.DataFrame()
    
    forehead_df = df[df["Zone"] == "Forehead"].copy()
    if crew_member:
        forehead_df = forehead_df[forehead_df["Crew Member"] == crew_member]
        
    if forehead_df.empty:
        return pd.DataFrame()

    rows = []
    for _, row in forehead_df.iterrows():
        details = str(row.get("Details / Metrics", ""))
        mood_val = "N/A"
        sleep_val = "N/A"
        
        for part in details.split("|"):
            part = part.strip()
            if part.startswith("Mood:"):
                mood_val = part.replace("Mood:", "").strip()
            elif part.startswith("Sleep:"):
                sleep_val = part.replace("Sleep:", "").strip()

        rows.append({
            "Date": row.get("Date", ""),
            "Time": row.get("Time", ""),
            "Crew Member": row.get("Crew Member", ""),
            "Mood": mood_val,
            "Sleep": sleep_val,
            "Notes": row.get("Notes", "")
        })

    agenda_df = pd.DataFrame(rows)
    agenda_df = agenda_df.sort_values(by=["Date", "Time"], ascending=[False, False]).reset_index(drop=True)
    return agenda_df


def has_recent_high_hr(df: pd.DataFrame, crew_member: str, threshold: float = 100.0) -> bool:
    if df.empty or "Zone" not in df.columns:
        return False
    heart_df = df[(df["Crew Member"] == crew_member) & (df["Zone"] == "Heart")]
    if heart_df.empty:
        return False
    last_details = str(heart_df.iloc[-1].get("Details / Metrics", ""))
    metrics = extract_metrics_from_text(last_details)
    return metrics.get("BPM", 0.0) > threshold


def has_recent_high_oxygenation(df: pd.DataFrame, crew_member: str, threshold: float = 36.5) -> bool:
    if df.empty or "Zone" not in df.columns:
        return False
    nose_df = df[(df["Crew Member"] == crew_member) & (df["Zone"] == "Nose")]
    if nose_df.empty:
        return False
    last_details = str(nose_df.iloc[-1].get("Details / Metrics", ""))
    metrics = extract_metrics_from_text(last_details)
    return metrics.get("Oxygenation", 0.0) > threshold


def trigger_emergency_redirect(
    emergency_type: str,
    crew_member: str,
    description: str,
    date_obj: datetime.date,
    time_obj: datetime.time,
    hr: str = "",
    temp: str = "",
    consciousness: str = "Alert",
    record_idx: int = None,
    tag: str = "[AUTO-EMERGENCY]"
):
    if record_idx is not None and record_idx in st.session_state.records_df.index:
        current_details = str(st.session_state.records_df.at[record_idx, "Details / Metrics"])
        if tag not in current_details:
            st.session_state.records_df.at[record_idx, "Details / Metrics"] = f"{current_details} | {tag}"

    st.session_state.pending_emergency_handoff = {
        "em_type": emergency_type,
        "em_crew": crew_member,
        "em_desc": description,
        "em_date": date_obj,
        "em_time": time_obj,
        "em_vs_hr": str(hr) if hr != "" else "",
        "em_vs_temp": str(temp) if temp != "" else "",
        "em_vs_cons": consciousness,
    }
    st.session_state.active_emergency_banner = f"{emergency_type} — {crew_member}"
    st.session_state.heart_alert_state = None
    st.session_state.nose_alert_state = None
    st.session_state.hand_alert_state = None
    st.session_state.leg_alert_state = None
    st.session_state.prevention_nudge = None
    st.session_state.menu = "Emergency"
    st.rerun()


def render_anatomy_map(view_key: str, zone_key: str, chart_prefix: str, marker_color: str, height: int = 520, fallback_zone: str = "Heart"):
    if st.session_state[view_key] == "body":
        img_file = "body.png"
        zones = {
            "Head": (0.50, 0.95),
            "Heart": (0.53, 0.73),
            "Leg": (0.37, 0.33),
            "Hand": (0.13, 0.48),
        }
        st.caption("Click directly on Head to open the head diagram, or select Heart, Leg, or Hand.")
    else:
        img_file = "head.png"
        zones = {
            "Forehead": (0.50, 0.70),
            "Eyes": (0.32, 0.49),
            "Nose": (0.50, 0.39),
        }
        st.caption("Click directly on Forehead, Eyes, or Nose.")
        if st.button("Back to Body", key=f"{chart_prefix}_back_to_body_btn"):
            st.session_state[view_key] = "body"
            st.session_state[zone_key] = fallback_zone
            st.rerun()

    try:
        img = load_inverted_image(img_file)
        w, h = img.size
        posiciones_texto = ["bottom center" if zona == "Eyes" else "top center" for zona in zones.keys()]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[w * xy[0] for xy in zones.values()],
            y=[h * xy[1] for xy in zones.values()],
            mode="markers+text",
            text=list(zones.keys()),
            textposition=posiciones_texto,
            textfont=dict(color="#ffffff", size=14, family="Arial"),
            marker=dict(size=18, color=marker_color, line=dict(width=2, color="#ffffff"))
        ))
        fig.add_layout_image(dict(
            source=img,
            xref="x",
            yref="y",
            x=0,
            y=h,
            sizex=w,
            sizey=h,
            sizing="stretch",
            layer="below"
        ))
        fig.update_xaxes(range=[0, w], visible=False, fixedrange=True, showgrid=False, zeroline=False)
        fig.update_yaxes(range=[0, h], visible=False, scaleanchor="x", fixedrange=True, showgrid=False, zeroline=False)
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=10),
            height=height,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )

        event = st.plotly_chart(
            fig,
            key=f"{chart_prefix}_{st.session_state[view_key]}",
            use_container_width=True,
            on_select="rerun",
            selection_mode="points"
        )

        if event and event.selection and event.selection.get("points"):
            idx = event.selection["points"][0]["point_index"]
            clicked = list(zones.keys())[idx]
            if st.session_state[view_key] == "body" and clicked == "Head":
                st.session_state[view_key] = "head"
                st.session_state[zone_key] = "Forehead"
                st.rerun()
            else:
                st.session_state[zone_key] = clicked

    except FileNotFoundError:
        st.warning(f"Image '{img_file}' not found in the project folder.")


def speak_widget(text: str, lang: str = "en-US", rate: float = 0.95):
    payload = json.dumps(text)
    components.html(f"""
        <div style="display:flex; gap:10px; font-family:Arial, sans-serif;">
            <button id="play" style="flex:1; padding:10px; border-radius:6px; cursor:pointer;
                background:#1e293b; color:#f8fafc; border:1px solid #A78BFA; font-size:14px;">
                🔊 Read protocol aloud
            </button>
            <button id="stop" style="padding:10px 18px; border-radius:6px; cursor:pointer;
                background:#1e293b; color:#f8fafc; border:1px solid #475569; font-size:14px;">
                ⏹ Stop
            </button>
        </div>
        <script>
            const text = {payload};
            document.getElementById('play').onclick = () => {{
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(text);
                u.lang = "{lang}";
                u.rate = {rate};
                window.speechSynthesis.speak(u);
            }};
            document.getElementById('stop').onclick = () => window.speechSynthesis.cancel();
        </script>
    """, height=60)


EMERGENCY_PROTOCOLS = {
    "Cardiac Emergency": {
        "severity": "CRITICAL",
        "color": "🔴",
        "description": "Possible cardiac arrest, severe chest pain or abnormal heartbeat.",
        "steps": [
            "1. Ensure the environment is safe before approaching the crew member.",
            "2. Check responsiveness and assess whether the person is breathing normally.",
            "3. Immediately notify Mission Control and activate the emergency medical response.",
            "4. If the person is unresponsive and not breathing normally, begin CPR according to crew medical training and mission procedures.",
            "5. Use the AED if available, following its voice and visual instructions.",
            "6. Continue monitoring the person's condition and follow Mission Control instructions.",
            "7. Record the time of onset, observed symptoms and all actions performed.",
        ],
        "avoid": [
            "Do not leave the person alone.",
            "Do not delay emergency communication.",
            "Do not give food, water or medication to an unconscious person.",
        ],
    },
    "Respiratory Emergency": {
        "severity": "CRITICAL",
        "color": "🔴",
        "description": "Severe difficulty breathing, suspected hypoxia or low oxygen saturation.",
        "steps": [
            "1. Check the person's responsiveness and breathing.",
            "2. Immediately notify Mission Control.",
            "3. Check the oxygen supply and cabin environmental conditions, following spacecraft procedures.",
            "4. Help the person maintain a comfortable position that facilitates breathing, if conscious.",
            "5. Administer supplemental oxygen only according to the approved mission medical protocol.",
            "6. Monitor oxygen saturation, respiratory rate and consciousness.",
            "7. Report all changes to Mission Control and follow medical instructions.",
        ],
        "avoid": [
            "Do not leave the person unattended.",
            "Do not assume that a normal oxygen saturation reading excludes an emergency.",
            "Do not modify spacecraft life-support systems without authorization.",
        ],
    },
    "Loss of Consciousness": {
        "severity": "CRITICAL",
        "color": "🔴",
        "description": "Crew member becomes unconscious or does not respond.",
        "steps": [
            "1. Check that the surrounding environment is safe.",
            "2. Try to establish responsiveness by speaking to the person.",
            "3. Check whether the person is breathing normally.",
            "4. Immediately contact Mission Control.",
            "5. If breathing normally, maintain an open airway and follow the approved recovery-position procedure, adapted to the spacecraft environment.",
            "6. If not breathing normally, begin CPR according to crew training and mission procedures.",
            "7. Monitor breathing and consciousness continuously.",
            "8. Record the event and report any changes.",
        ],
        "avoid": [
            "Do not give food, liquids or medication.",
            "Do not shake the person.",
            "Do not assume the person is recovering without monitoring.",
        ],
    },
    "Trauma / Injury": {
        "severity": "HIGH",
        "color": "🟠",
        "description": "Physical injury, possible fracture, impact or serious bleeding.",
        "steps": [
            "1. Secure the surrounding area to prevent additional injuries.",
            "2. Assess the person's consciousness and breathing.",
            "3. Notify Mission Control and describe the injury.",
            "4. Control external bleeding with direct pressure using appropriate sterile material.",
            "5. Avoid unnecessary movement if a spinal injury or fracture is suspected.",
            "6. Immobilize the affected area only if trained and according to mission procedures.",
            "7. Monitor the person's condition until further medical instructions are received.",
        ],
        "avoid": [
            "Do not attempt to realign a suspected fracture.",
            "Do not move a person with suspected spinal injury unless necessary for immediate safety.",
            "Do not remove embedded objects from wounds.",
        ],
    },
    "Burns": {
        "severity": "HIGH",
        "color": "🟠",
        "description": "Thermal, chemical or electrical burns.",
        "steps": [
            "1. Ensure the source of danger has been isolated safely.",
            "2. Notify Mission Control.",
            "3. For thermal burns, cool the affected area with cool running water when available and compatible with spacecraft procedures.",
            "4. Remove jewelry or loose clothing near the injury, but do not remove material stuck to the skin.",
            "5. Cover the burn with a sterile, non-adherent dressing.",
            "6. Monitor for signs of shock or respiratory complications.",
            "7. Report the affected area, estimated severity and possible cause.",
        ],
        "avoid": [
            "Do not apply ice directly to the burn.",
            "Do not break blisters.",
            "Do not apply creams, oils or household remedies.",
        ],
    },
    "Seizure": {
        "severity": "HIGH",
        "color": "🟠",
        "description": "Uncontrolled movements, convulsions or suspected neurological emergency.",
        "steps": [
            "1. Protect the person from nearby objects and potential impacts.",
            "2. Notify Mission Control.",
            "3. Monitor and record the duration of the seizure.",
            "4. Do not restrain the person's movements.",
            "5. Do not put anything inside the person's mouth.",
            "6. Once the seizure ends, check breathing and responsiveness.",
            "7. Follow the approved medical protocol and continue monitoring.",
        ],
        "avoid": [
            "Do not force the person's movements to stop.",
            "Do not give liquids or medication by mouth during the seizure.",
            "Do not leave the person alone.",
        ],
    },
    "Psychological Emergency": {
        "severity": "HIGH",
        "color": "🟠",
        "description": "Severe panic, acute distress, disorientation or risk of self-harm.",
        "steps": [
            "1. Ensure the environment is safe for the affected crew member and others.",
            "2. Approach calmly and communicate using clear, reassuring language.",
            "3. Notify Mission Control and the designated psychological support team.",
            "4. Listen without judgment and assess whether there is an immediate risk of harm.",
            "5. If safe, reduce unnecessary stimulation and provide a calm environment.",
            "6. Maintain appropriate supervision and follow professional instructions.",
            "7. Document observed behavior and actions taken.",
        ],
        "avoid": [
            "Do not dismiss or minimize the person's distress.",
            "Do not argue, threaten or blame the person.",
            "Do not leave a person at immediate risk of self-harm alone.",
        ],
    },
    "Other Emergency": {
        "severity": "MODERATE / TO BE ASSESSED",
        "color": "🟡",
        "description": "Any other unexpected medical or safety incident.",
        "steps": [
            "1. Ensure the area is safe.",
            "2. Check the affected person's responsiveness and breathing.",
            "3. Contact Mission Control if the event may affect crew safety.",
            "4. Identify and describe the symptoms or incident.",
            "5. Follow the appropriate medical or spacecraft safety procedure.",
            "6. Monitor the affected person and report changes.",
            "7. Document the event.",
        ],
        "avoid": [
            "Do not ignore worsening symptoms.",
            "Do not perform procedures outside your training.",
            "Do not delay escalation if the person's condition deteriorates.",
        ],
    },
}

EMERGENCY_COLUMNS = [
    "Date", "Time", "Crew Member", "Emergency Type", "Severity",
    "Description", "Actions Taken", "Communication Report",
]


def save_emergency_report():
    ss = st.session_state
    protocol = EMERGENCY_PROTOCOLS[ss.em_type]

    if not ss.em_desc.strip():
        ss.em_feedback = ("error", "Please provide an emergency description.")
        return
    if not ss.em_confirm:
        ss.em_feedback = ("warning", "Please confirm the incident information.")
        return

    new_row = pd.DataFrame([{
        "Date": ss.em_date.isoformat(),
        "Time": ss.em_time.strftime("%H:%M:%S"),
        "Crew Member": ss.em_crew,
        "Emergency Type": ss.em_type,
        "Severity": protocol["severity"],
        "Description": ss.em_desc,
        "Actions Taken": ss.em_actions,
        "Communication Report": ss.em_comm,
    }])
    ss.emergency_records = pd.concat(
        [ss.emergency_records, new_row], ignore_index=True
    )

    ss.em_desc = ""
    ss.em_actions = ""
    ss.em_comm = ""
    ss.em_confirm = False
    ss.active_emergency_banner = None
    ss.em_feedback = ("success", "Emergency report successfully registered!")


bg_map = {
    "Emergency": "fondo2.jpeg",
    "Prevention": "fondo3.jpeg",
    "Users": "fondo4.jpeg",
    "History": "fondo5.jpeg",
}
bg_file = bg_map.get(st.session_state.menu, "Fondo.jpeg")
bg_overlay = 0.75

try:
    bg_b64 = img_to_base64(bg_file)
    active_bg_css = (
        f"linear-gradient(rgba(11, 15, 25, {bg_overlay}), rgba(11, 15, 25, {bg_overlay})), "
        f'url("data:image/jpeg;base64,{bg_b64}")'
    )
except FileNotFoundError:
    active_bg_css = "none"

st.markdown(f"""
    <style>
    :root {{
        color-scheme: dark !important;
    }}
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
        background-color: #0b0f19 !important;
        background-image: {active_bg_css} !important;
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        color: #f8fafc !important;
    }}
    [data-testid="stHeader"] {{
        background: transparent !important;
    }}
    .block-container {{
        padding-top: 2.5rem !important;
        padding-left: 2.5rem !important;
        padding-right: 2.5rem !important;
    }}

    /* --- SIDEBAR --- */
    section[data-testid="stSidebar"] {{
        background-color: #111827 !important;
        border-right: 1px solid #1e293b !important;
    }}
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] label p {{
        color: #ffffff !important;
        opacity: 1 !important;
    }}
    section[data-testid="stSidebar"] .stButton > button {{
        width: 100% !important;
        background-color: transparent !important;
        color: #94a3b8 !important;
        border: 1px solid transparent !important;
        border-radius: 6px !important;
        padding: 12px 16px !important;
        font-size: 15px !important;
        font-weight: 500 !important;
        letter-spacing: 0.5px !important;
        text-align: left !important;
        justify-content: flex-start !important;
        transition: all 0.2s ease-in-out;
        margin-bottom: 4px !important;
    }}
    section[data-testid="stSidebar"] .stButton > button p,
    section[data-testid="stSidebar"] .stButton > button span {{
        color: #94a3b8 !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover,
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
        background-color: #1e293b !important;
        color: #CFAFFF !important;
        border: 1px solid transparent !important;
        border-left: 3px solid #CFAFFF !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover p,
    section[data-testid="stSidebar"] .stButton > button:hover span,
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] span {{
        color: #CFAFFF !important;
    }}

    /* --- BOTÓN ESPECIAL DE EMERGENCIA EN EL SIDEBAR --- */
    section[data-testid="stSidebar"] .st-key-Emergency button {{
        background-color: rgba(127, 29, 29, 0.35) !important;
        border: 1px solid rgba(239, 68, 68, 0.45) !important;
        border-left: 3px solid #ef4444 !important;
        color: #fca5a5 !important;
        font-weight: 600 !important;
    }}
    section[data-testid="stSidebar"] .st-key-Emergency button p,
    section[data-testid="stSidebar"] .st-key-Emergency button span {{
        color: #fca5a5 !important;
    }}
    section[data-testid="stSidebar"] .st-key-Emergency button:hover,
    section[data-testid="stSidebar"] .st-key-Emergency button:active,
    section[data-testid="stSidebar"] .st-key-Emergency button[kind="primary"] {{
        background-color: #b91c1c !important;
        border: 1px solid #f87171 !important;
        border-left: 4px solid #ffffff !important;
        color: #ffffff !important;
        box-shadow: 0 0 12px rgba(239, 68, 68, 0.45) !important;
    }}
    section[data-testid="stSidebar"] .st-key-Emergency button:hover p,
    section[data-testid="stSidebar"] .st-key-Emergency button:hover span,
    section[data-testid="stSidebar"] .st-key-Emergency button:active p,
    section[data-testid="stSidebar"] .st-key-Emergency button:active span,
    section[data-testid="stSidebar"] .st-key-Emergency button[kind="primary"] p,
    section[data-testid="stSidebar"] .st-key-Emergency button[kind="primary"] span {{
        color: #ffffff !important;
    }}

    /* --- CONTENEDORES Y FORMULARIOS --- */
    [data-testid="stForm"],
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: rgba(17, 24, 39, 0.72) !important;
        border: 1px solid rgba(148, 163, 184, 0.22) !important;
        border-radius: 10px !important;
    }}

    /* --- TEXTOS, ETIQUETAS Y CAPTIONS --- */
    [data-testid="stAppViewContainer"] > section.main h1,
    [data-testid="stAppViewContainer"] > section.main h2,
    [data-testid="stAppViewContainer"] > section.main h3,
    [data-testid="stAppViewContainer"] > section.main h4,
    [data-testid="stAppViewContainer"] > section.main label,
    [data-testid="stAppViewContainer"] > section.main label p {{
        color: #f8fafc !important;
    }}
    [data-testid="stAppViewContainer"] > section.main [data-testid="stCaptionContainer"],
    [data-testid="stAppViewContainer"] > section.main [data-testid="stCaptionContainer"] p {{
        color: #94a3b8 !important;
        opacity: 1 !important;
    }}

    /* --- INPUTS --- */
    input, textarea,
    [data-baseweb="input"],
    [data-baseweb="input"] > div,
    [data-baseweb="base-input"],
    [data-baseweb="select"] > div {{
        background-color: #262730 !important;
        color: #f8fafc !important;
        border-color: #3f414e !important;
    }}
    input::placeholder, textarea::placeholder {{
        color: #94a3b8 !important;
    }}
    [data-testid="stNumberInputStepDown"],
    [data-testid="stNumberInputStepUp"] {{
        background-color: #262730 !important;
        color: #f8fafc !important;
        border-color: #3f414e !important;
    }}
    [data-testid="stNumberInputStepDown"]:hover,
    [data-testid="stNumberInputStepUp"]:hover {{
        background-color: #334155 !important;
    }}

    /* --- POPOVERS --- */
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] > div,
    ul[role="listbox"],
    ul[role="listbox"] li,
    [data-baseweb="calendar"] {{
        background-color: #1e293b !important;
        color: #f8fafc !important;
    }}
    ul[role="listbox"] li:hover {{
        background-color: #334155 !important;
    }}

    /* --- BOTONES --- */
    section.main .stFormSubmitButton > button,
    section.main .stButton > button {{
        background-color: #1e293b !important;
        color: #f8fafc !important;
        border: 1px solid #475569 !important;
    }}
    section.main .stFormSubmitButton > button:hover,
    section.main .stButton > button:hover {{
        background-color: #334155 !important;
        border-color: #9C96CD !important;
        color: #CFAFFF !important;
    }}

    /* --- FILE UPLOADER --- */
    [data-testid="stFileUploaderDropzone"] {{
        background-color: #1e293b !important;
        border-color: #475569 !important;
        color: #f8fafc !important;
    }}

    /* --- MÉTRICAS --- */
    div[data-testid="stMetric"] {{
        background-color: #111827 !important;
        border: 1px solid #1e293b !important;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }}

    /* --- ESTILOS PREVENTION --- */
    .st-key-sublist_causes button {{
        background-color: #172236 !important;
        border: 1px solid #2E4366 !important;
        border-left: 4px solid #38BDF8 !important;
        color: #E2E8F0 !important;
        margin-left: 14px !important;
        width: calc(100% - 14px) !important;
    }}
    .st-key-sublist_causes button:hover {{
        background-color: #1F2E47 !important;
        border-color: #38BDF8 !important;
        border-left: 4px solid #7DD3FC !important;
        color: #FFFFFF !important;
    }}
    div[data-testid="stCheckbox"] input[type="checkbox"] {{
        accent-color: #38BDF8 !important;
    }}
    div[data-testid="stCheckbox"] label span:first-child {{
        border-color: #38BDF8 !important;
    }}
    div[data-testid="stCheckbox"] input[type="checkbox"]:checked + div,
    div[data-testid="stCheckbox"] label:has(input:checked) span:first-child {{
        background-color: #38BDF8 !important;
        border-color: #38BDF8 !important;
    }}
    @keyframes twinkle {{
        0%, 100% {{ opacity: 1; transform: scale(1); }}
        50% {{ opacity: 0.4; transform: scale(1.2); }}
    }}
    .star-celebration {{
        background: linear-gradient(90deg, rgba(14, 116, 144, 0.25) 0%, rgba(56, 189, 248, 0.2) 50%, rgba(14, 116, 144, 0.25) 100%);
        border: 1px solid #38BDF8;
        border-radius: 10px;
        padding: 14px 18px;
        margin-top: 12px;
        text-align: center;
        color: #F0F9FF;
        font-weight: 600;
        font-size: 15px;
        box-shadow: 0 0 15px rgba(56, 189, 248, 0.25);
    }}
    .star-icon {{
        display: inline-block;
        animation: twinkle 1.4s infinite ease-in-out;
        margin: 0 4px;
    }}

    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    </style>
""", unsafe_allow_html=True)

all_crew_members = []
for mission_name, mission_data in st.session_state.missions.items():
    for user in mission_data["users"]:
        all_crew_members.append(user["name"])

if not all_crew_members:
    all_crew_members = ["No Crew Members Available"]

if "pending_crew_selection" in st.session_state:
    pending = st.session_state.pop("pending_crew_selection")
    if pending in all_crew_members:
        st.session_state.selected_crew_sidebar = pending

if st.session_state.selected_crew_sidebar not in all_crew_members:
    st.session_state.selected_crew_sidebar = all_crew_members[0]

with st.sidebar:
    st.markdown("## SPACE CONTROL")
    st.caption("TELEMETRY & CREW MONITORING")
    st.markdown("---")
    selected_crew = st.selectbox(
        "SELECT CREW MEMBER",
        options=all_crew_members,
        key="selected_crew_sidebar"
    )
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("NAVIGATION SYSTEM")

    opciones = {
        "Users": "Basic crew information",
        "Register": "Record symptoms or data",
        "Emergency": "Emergency Protocols and Communication with the Ground",
        "Prevention": "Prevention protocols",
        "History": "History of past records and trends"
    }

    for key, label in opciones.items():
        is_active = st.session_state.menu == key
        if st.button(label, key=key, type="primary" if is_active else "secondary"):
            st.session_state.menu = key
            st.rerun()

    st.markdown("---")
    if st.session_state.active_emergency_banner:
        st.markdown(f"""
            <div style='background-color: #7f1d1d; color: #fecaca; padding: 10px 14px; border-radius: 6px; border: 1px solid #ef4444; font-size: 13px; font-weight: 700; letter-spacing: 0.5px;'>
                🚨 STATUS: EMERGENCY ACTIVE<br>
                <span style='font-size: 11px; font-weight: 400;'>{st.session_state.active_emergency_banner}</span>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <div style='background-color: #064e3b; color: #34d399; padding: 10px 14px; border-radius: 6px; border: 1px solid #059669; font-size: 13px; font-weight: 600; letter-spacing: 0.5px;'>
                STATUS: NOMINAL
            </div>
        """, unsafe_allow_html=True)

titulo_limpio = opciones[st.session_state.menu].upper()

st.markdown(f"""
    <div style='background: linear-gradient(90deg, #111827 0%, #7A7B9A 100%); 
                padding: 20px 25px; 
                border-radius: 8px; 
                border-left: 4px solid #321E49;
                margin-bottom: 25px;
                display: flex;
                justify-content: space-between;
                align-items: center;'>
        <div>
            <h1 style='margin: 0; font-size: 24px; color: #f8fafc; letter-spacing: 1.5px;'>
                {titulo_limpio}
            </h1>
            <p style='margin: 5px 0 0 0; color: #94a3b8; font-size: 14px;'>
                Active Crew Member: <strong style='color: #9C96CD;'>{selected_crew}</strong>
            </p>
        </div>
        <div style='text-align: right;'>
            <span style='background-color: #0f172a; color: #f8fafc; padding: 6px 14px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 1px; border: 1px solid #f8fafc;'>
                ONLINE
            </span>
        </div>
    </div>
""", unsafe_allow_html=True)

with st.container(key=f"main_view_{st.session_state.menu}"):
    if st.session_state.menu == "Users":
        with st.container(border=True):
            st.subheader("Missions & Crew Management Workspace")
            st.write("Manage space missions and add crew members to specific missions below.")
            st.markdown("Create New Mission")
            with st.form("new_mission_form", clear_on_submit=True):
                new_mission_name = st.text_input("Mission Name", placeholder="e.g., Artemis II")
                mission_location = st.selectbox(
                    "Mission Location",
                    ["Earth orbit", "Lunar orbit", "Lunar orbit + surface", "Mars"]
                )
                mission_duration = st.selectbox(
                    "Mission Duration",
                    ["Less than 30 days", "30 days to 1 year"]
                )
                submit_mission = st.form_submit_button("Create Mission")

                if submit_mission:
                    clean_m_name = new_mission_name.strip()
                    if clean_m_name:
                        if clean_m_name not in st.session_state.missions:
                            st.session_state.missions[clean_m_name] = {
                                "location": mission_location,
                                "duration": mission_duration,
                                "users": []
                            }
                            st.success(f"Mission '{clean_m_name}' created successfully.")
                            st.rerun()
                        else:
                            st.error("A mission with this name already exists.")
                    else:
                        st.error("Please enter a valid mission name.")

            st.markdown("---")

            st.markdown("Add User to a Mission")
            if not st.session_state.missions:
                st.info("No missions available yet. Please create a mission above first.")
            else:
                with st.form("new_user_form", clear_on_submit=True):
                    target_mission = st.selectbox("Select Mission", list(st.session_state.missions.keys()))
                    user_name = st.text_input("Full Name", placeholder="e.g., Cmdr. Jane Doe")
                    user_dob = st.date_input("Date of Birth", value=datetime.date(1990, 1, 1), min_value=datetime.date(1940, 1, 1), max_value=datetime.date.today())
                    col_hw1, col_hw2, col_hw3 = st.columns(3)
                    with col_hw1:
                        user_height = st.number_input("Height (m)", min_value=1.0, max_value=2.5, value=1.75, step=0.01)
                    with col_hw2:
                        user_weight = st.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=70.0, step=0.5)
                    with col_hw3:
                        user_bmd = st.number_input("Pre-Mission Bone Density (g/cm²)", min_value=0.40, max_value=2.00, value=1.10, step=0.01)
                    user_notes = st.text_area("Optional Notes", placeholder="Medical history, specialization, or operational notes...")
                
                    submit_user = st.form_submit_button("Create User")

                    if submit_user:
                        clean_u_name = user_name.strip()
                        if clean_u_name:
                            if clean_u_name in all_crew_members:
                                st.error("A crew member with this name already exists.")
                            else:
                                new_user_data = {
                                    "name": clean_u_name,
                                    "dob": user_dob.isoformat(),
                                    "height": user_height,
                                    "weight": user_weight,
                                    "baseline_bmd": round(float(user_bmd), 2),
                                    "notes": user_notes
                                }
                                st.session_state.missions[target_mission]["users"].append(new_user_data)

                                baseline_entry = pd.DataFrame([{
                                    "Date": datetime.date.today().isoformat(),
                                    "Time": datetime.datetime.now().time().replace(microsecond=0).strftime("%H:%M:%S"),
                                    "Crew Member": clean_u_name,
                                    "View": "Body",
                                    "Zone": "Leg",
                                    "Details / Metrics": f"Exercise: 0.0h | Bone Density: 100.0% ({user_bmd:.2f} g/cm2)",
                                    "Notes": "Pre-mission baseline BMD"
                                }])
                                st.session_state.records_df = pd.concat(
                                    [st.session_state.records_df, baseline_entry],
                                    ignore_index=True
                                )
                                st.session_state.pending_crew_selection = clean_u_name
                                st.rerun()
                        else:
                            st.error("Please enter a valid user name.")

            st.markdown("---")
            st.subheader("Current Missions and Crew Directory")
            if not st.session_state.missions:
                st.caption("No missions registered yet.")
            else:
                for m_name, m_info in st.session_state.missions.items():
                    with st.expander(f"Mission: {m_name} | Location: {m_info['location']} | Duration: {m_info['duration']}", expanded=True):
                        if m_info["users"]:
                            users_df = pd.DataFrame(m_info["users"])
                            users_df.columns = ["Name", "Date of Birth", "Height (m)", "Weight (kg)", "Pre-Mission BMD (g/cm²)", "Notes"]
                            st.dataframe(users_df, use_container_width=True)
                        else:
                            st.info("No crew members assigned to this mission yet.")

    elif st.session_state.menu == "Prevention":
        with st.container(border=True):
            st.subheader("Prevention Workspace")

            OTHER = "➕ Other"
            MED_WARNING = "Medical Warning: Never self-medicate. Any medication, melatonin, or supplement must be taken strictly under Ground medical prescription."

            category_general_tips = {
                "😴 Sleep": [
                    "Keep a steady work and rest schedule: aim for 7 to 8 hours of sleep (at least 6).",
                    "After a long work shift, try to sleep a bit longer than the day before.",
                    "Do relaxation or breathing exercises before going to bed.",
                    "Avoid naps during the day, as they disrupt your body clock on long missions.",
                    "Melatonin can help you fall asleep faster, but use it only under medical prescription.",
                ],
                "😰 Anxiety Crisis": [
                    "Pause non-essential tasks and focus on slow, deep breathing for 2 minutes.",
                    "Anchor your feet or hands to a handrail to feel physically grounded.",
                    "Limit caffeine and sugary snacks when feeling tense or on edge.",
                    "Talk openly with a trusted crewmate or Ground support before stress builds up.",
                ],
                "🧠 Mood & Isolation": [
                    "Keep a regular daily routine with clear boundaries between work and personal time.",
                    "Stay connected with family and friends on Earth through scheduled calls or messages.",
                    "Dedicate at least 30 minutes a day to a personal hobby, music, or reading.",
                    "Check in with your crewmates daily to share how you are feeling.",
                ],
                "☢️ Radiation": [
                    "Always wear your personal dosimeter and check daily exposure alerts.",
                    "Spend sleeping and off-duty hours in the best-shielded modules of the spacecraft.",
                    "Eat foods rich in natural antioxidants (berries, leafy greens, nuts) every day.",
                    "Take your prescribed daily antioxidant and vitamin supplements.",
                ],
                "💧 Hydration & Nutrition": [
                    "Drink water on a fixed schedule throughout the day, even if you do not feel thirsty.",
                    "Never skip meals, especially before and after heavy exercise or EVA tasks.",
                    "Prioritize protein, fiber, and potassium-rich foods to protect muscles and bones.",
                    "Log your fluid and food intake so Ground can help adjust your nutrition plan.",
                ],
            }

            exercise_library = {
                "🦴 Resistive (ARED)": [
                    {
                        "name": "Squats (Back & Single-Leg)",
                        "target": "Quads, glutes, hip & lumbar spine bone density",
                        "dosage": "3–5 sets × 6–15 reps | Load: +3–5% weekly after day 20",
                        "media": "nasa_squats.mp4",
                        "instructions": [
                            "Secure shoulder pads and waist harness firmly before unlatching the bar.",
                            "Keep your torso upright and descend until thighs are parallel to the platform.",
                            "Push smoothly through your heels to maintain steady load on the spine.",
                        ],
                    },
                    {
                        "name": "Deadlifts (Romanian & Conventional)",
                        "target": "Hamstrings, lower back, core & pelvic bone loading",
                        "dosage": "3–4 sets × 8–12 reps",
                        "media": "nasa_deadlifts.mp4",
                        "instructions": [
                            "Maintain a neutral spine and engage your core before lifting.",
                            "Keep the bar close to your shins throughout the pull.",
                            "Avoid hyperextending your lower back at the top of the movement.",
                        ],
                    },
                    {
                        "name": "Heel Raises",
                        "target": "Calves (soleus/gastrocnemius) & Achilles tendon",
                        "dosage": "4 sets × 12–15 reps",
                        "media": "nasa_heel_raises.mp4",
                        "instructions": [
                            "Place the balls of your feet on the edge of the footplate.",
                            "Press all the way up onto your toes, pause 1 second, and lower slowly.",
                        ],
                    },
                ],
                "❤️ Cardio (T2 & CEVIS)": [
                    {
                        "name": "T2 Treadmill Interval Running",
                        "target": "Cardiovascular endurance & lower-limb impact loading",
                        "dosage": "30 min | 4–7 sessions/week | Harness load: 70–80% body weight",
                        "media": "nasa_treadmill.mp4",
                        "instructions": [
                            "Adjust shoulder and hip bungee straps evenly to avoid pressure points.",
                            "Alternate 3 minutes of steady jogging with 1 minute of high-speed intervals.",
                            "Increase session frequency during the final 15–30 days before re-entry.",
                        ],
                    },
                    {
                        "name": "CEVIS Cycle Ergometer",
                        "target": "Aerobic capacity & leg stamina without harness pressure",
                        "dosage": "30 min | Moderate-to-high resistance",
                        "media": "nasa_cevis.mp4",
                        "instructions": [
                            "Clip cycling shoes into pedals and fasten the waist belt securely.",
                            "Maintain a cadence between 70 and 90 RPM.",
                        ],
                    },
                ],
                "🧘 Mobility & Backup": [
                    {
                        "name": "Resistance Band & Core Flow",
                        "target": "Postural muscles, shoulder mobility & contingency training",
                        "dosage": "20 min | Use when primary gear is under maintenance",
                        "media": "nasa_mobility.mp4",
                        "instructions": [
                            "Anchor resistance bands to a fixed handrail.",
                            "Perform slow rows, chest presses, and core anti-rotation holds.",
                            "Skip strenuous sessions on EVA days or if cabin CO2 exceeds 7 mmHg.",
                        ],
                    },
                ],
            }

            prevention_data = {
                "😴 Sleep": {
                    "🌡️ Cabin temperature": {
                        "why": "If the cabin is too hot or too cold, the body cannot relax and falling asleep takes longer.",
                        "tips": [
                            "Adjust the temperature of your sleeping area before going to bed.",
                            "Check that air vents flow gently around your sleeping quarter.",
                        ],
                    },
                    "🔊 High noise levels": {
                        "why": "Constant machine noise (fans, life support, exercise gear) can wake you up or block deep sleep.",
                        "tips": [
                            "Use ear protection or a private sleeping quarter to reduce noise.",
                            "Report unusually loud equipment near sleeping areas so it can be fixed.",
                        ],
                    },
                    "🛏️ Sleeping bag fit": {
                        "why": "A bag that is too tight, too loose, or too warm makes it hard to get comfortable.",
                        "tips": [
                            "Adjust your sleeping bag straps so it fits your body comfortably.",
                            "Use the body restraints so you do not float around while sleeping.",
                        ],
                    },
                    "🪐 Floating feeling": {
                        "why": "Without gravity, there is no mattress pressure telling your brain you are lying down, making it harder to relax.",
                        "tips": [
                            "Secure the sleeping restraints snugly so your body feels held in place.",
                            "Sleep in the same spot and position every night to build a habit.",
                        ],
                    },
                    "📅 Schedule changes": {
                        "why": "Last-minute task shifts cut sleep short, especially before critical operations.",
                        "tips": [
                            "Avoid last-minute schedule changes whenever possible.",
                            "If your sleep was cut short, extend your rest period the next day.",
                        ],
                    },
                    "💼 Heavy workload": {
                        "why": "Packed workdays leave little time to unwind, causing fatigue to build up.",
                        "tips": [
                            "Alternate demanding tasks with lighter ones throughout the day.",
                            "Protect your scheduled rest and off-duty breaks.",
                        ],
                    },
                    "💡 Light & body clock": {
                        "why": "Orbiting Earth creates 16 sunrises and sunsets per day, confusing your internal clock.",
                        "warning": MED_WARNING,
                        "tips": [
                            "Use bright light during work hours and dim, warm light before bed.",
                            "Avoid bright screens and blue light 1 hour before sleeping.",
                            "Consult Ground medical support before using melatonin to reset your sleep cycle.",
                        ],
                    },
                    "😟 Stress or discomfort": {
                        "why": "Worry, tension, or body aches make it hard to fall asleep, and poor sleep makes them worse.",
                        "tips": [
                            "Do a 5-minute relaxation routine before bed: try 4-7-8 breathing (inhale 4s, hold 7s, exhale 8s) or a slow head-to-toe muscle scan.",
                            "Practice slow, controlled movement routines such as space-adapted Tai Chi to release physical tension before sleep.",
                            "Talk with a crewmate or Ground support about what is worrying you.",
                        ],
                    },
                    OTHER: {
                        "why": "If your cause is not listed, write it below to log it for Ground. Meanwhile, use the general sleep habits below.",
                        "warning": MED_WARNING,
                        "tips": category_general_tips["😴 Sleep"],
                    },
                },
                "😰 Anxiety Crisis": {
                    "🚨 Sudden panic or high stress": {
                        "why": "High-stakes operations, alarms, or emergencies trigger a rapid adrenaline surge, racing heart, and shortness of breath.",
                        "tips": [
                            "Pause non-critical tasks and hold onto a fixed handrail to steady yourself.",
                            "Do box breathing: inhale 4s, hold 4s, exhale 4s, hold 4s until your pulse slows.",
                            "Name 5 things you can see and 3 things you can touch to bring focus back to the present.",
                        ],
                    },
                    "🌀 Feeling trapped (claustrophobia)": {
                        "why": "Living inside tight spacecraft modules with constant background hum can trigger sudden feelings of confinement.",
                        "tips": [
                            "Move to a larger module or look out the window/cupola at Earth for perspective.",
                            "Use the VR headset with Earth nature scenes to give your brain a change of scenery.",
                            "Play calming music or familiar audio recordings from home.",
                        ],
                    },
                    "🧬 Brain chemistry & fatigue": {
                        "why": "Microgravity, poor sleep, and oxidative stress alter mood-regulating brain chemicals, making anxiety easier to trigger.",
                        "warning": MED_WARNING,
                        "tips": [
                            "Eat foods rich in Omega-3s and antioxidants to support brain balance.",
                            "Cut back on coffee, tea, or energy drinks during high-stress periods.",
                            "Contact the Flight Surgeon before taking any medication from the onboard medical kit.",
                        ],
                    },
                    OTHER: {
                        "why": "If your cause is not listed, write it below to log it for Ground. Meanwhile, use the general anxiety habits below.",
                        "tips": category_general_tips["😰 Anxiety Crisis"],
                    },
                },
                "🏋️ Exercise": {},
                "🧠 Mood & Isolation": {
                    "🌍 Homesickness & distance": {
                        "why": "Being far from Earth and loved ones for months can cause loneliness, sadness, and emotional fatigue.",
                        "tips": [
                            "Schedule regular private video or audio calls with family and friends.",
                            "Spend time tending onboard plants or looking at personal photos and mementos.",
                            "Use private psychological support sessions whenever you feel down.",
                        ],
                    },
                    "🤝 Crew tension & misunderstandings": {
                        "why": "Living and working in tight quarters amplifies minor habits, cultural differences, and communication friction.",
                        "tips": [
                            "Practice active listening: let your crewmate finish without interrupting, maintain eye contact, and repeat back what you understood before replying.",
                            "Manage conflicts calmly: use 'I' statements ('I feel stressed when...' instead of 'You always...') to avoid blame.",
                            "Take a 15-minute cool-down break in your private quarter if a discussion gets heated, then revisit it calmly.",
                        ],
                    },
                    "📉 Mental fog & low motivation": {
                        "why": "Combined space stressors lower focus, slow reaction times, and drain daily motivation.",
                        "tips": [
                            "Break large procedures into small, single-step checklists.",
                            "Use VR environments or interactive games during downtime to refresh your mind.",
                            "Log persistent low mood or mental fatigue so Ground can adjust your workload.",
                        ],
                    },
                    OTHER: {
                        "why": "If your cause is not listed, write it below to log it for Ground. Meanwhile, use the general mood habits below.",
                        "tips": category_general_tips["🧠 Mood & Isolation"],
                    },
                },
                "☢️ Radiation": {
                    "☀️ Solar storms & cosmic rays": {
                        "why": "Space radiation passes through spacecraft walls and can damage cells and DNA, especially during solar flares.",
                        "tips": [
                            "Move immediately to the shielded 'storm shelter' if a solar event alarm sounds.",
                            "Sleep inside polyethylene-lined quarters, which cut daily radiation by ~20%.",
                            "Check your active dosimeter before and after every spacewalk (EVA).",
                        ],
                    },
                    "🧬 Cell stress from radiation": {
                        "why": "Radiation creates unstable molecules (free radicals) in body water that irritate tissues and speed up cell wear.",
                        "warning": MED_WARNING,
                        "tips": [
                            "Take your prescribed daily antioxidant pack (Vitamins C, E, A, Selenium, Zinc, and CoQ10).",
                            "Eat foods rich in natural plant antioxidants like berries, green tea, and leafy greens.",
                            "Keep selenium intake steady through your prescribed diet to protect cell repair enzymes.",
                        ],
                    },
                    "🛡️ Lowered immune & eye protection": {
                        "why": "Radiation and weightlessness weaken white blood cells and increase long-term eye lens sensitivity.",
                        "warning": MED_WARNING,
                        "tips": [
                            "Support immunity with prescribed daily Vitamins D, C, Zinc, and beta-glucans.",
                            "Protect your eyes by eating foods rich in lutein, zeaxanthin, and Omega-3s.",
                            "Report any unusual fatigue, skin irritation, or vision changes to Ground right away.",
                        ],
                    },
                    OTHER: {
                        "why": "If your cause is not listed, write it below to log it for Ground. Meanwhile, use the general radiation habits below.",
                        "warning": MED_WARNING,
                        "tips": category_general_tips["☢️ Radiation"],
                    },
                },
                "💧 Hydration & Nutrition": {
                    "🚰 Dehydration & fluid shift": {
                        "why": "In space, body fluids shift toward your head, fooling your brain into not feeling thirsty and raising kidney stone risk.",
                        "tips": [
                            "Drink water on a set timer rather than waiting to feel thirsty.",
                            "Drink extra fluids with electrolytes before and after daily workouts.",
                            "Follow the pre-landing hydration protocol to prevent dizziness upon return.",
                        ],
                    },
                    "🦠 Stomach & gut imbalance": {
                        "why": "Packaged space food and stress change gut bacteria, causing bloating and poorer nutrient absorption.",
                        "warning": MED_WARNING,
                        "tips": [
                            "Take your prescribed daily probiotic supplement to keep gut bacteria balanced.",
                            "Eat fiber-rich foods and prebiotics to support healthy digestion.",
                            "Include fermented food options when available in your meal rotation.",
                        ],
                    },
                    "🥗 Low energy & nutrient gaps": {
                        "why": "Muscle building slows by ~46% in space, and heavy workouts burn extra vitamins and minerals.",
                        "tips": [
                            "Prioritize high-protein foods and amino acids at every meal to protect muscle mass.",
                            "Maintain your daily Calcium, Magnesium, Vitamin D, and Vitamin K intake for bone health.",
                            "Add nutrient-dense foods like spirulina or fortified snacks when appetite is low.",
                        ],
                    },
                    OTHER: {
                        "why": "If your cause is not listed, write it below to log it for Ground. Meanwhile, use the general hydration and nutrition habits below.",
                        "tips": category_general_tips["💧 Hydration & Nutrition"],
                    },
                },
                OTHER: {},
            }

            col_list, col_detail = st.columns([1, 2])

            with col_list:
                for idx, (problem, causes) in enumerate(prevention_data.items()):
                    is_open = st.session_state.prev_problem == problem
                    arrow = "▾" if is_open else "▸"
                    if st.button(f"{arrow} {problem}", key=f"prev_main_{idx}_{problem}", use_container_width=True):
                        st.session_state.prev_problem = None if is_open else problem
                        st.session_state.prev_cause = None
                        st.rerun()
                    if is_open and causes:
                        with st.container(key="sublist_causes"):
                            for c_idx, cause in enumerate(causes):
                                selected = st.session_state.prev_cause == cause
                                label = f"› {cause}" if selected else cause
                                if st.button(label, key=f"prev_sub_{idx}_{c_idx}_{cause}", use_container_width=True):
                                    st.session_state.prev_cause = cause
                                    st.rerun()

            with col_detail:
                p, c = st.session_state.prev_problem, st.session_state.prev_cause

                # 1. Vista especial cuando se selecciona "➕ Other" en la lista principal
                if p == OTHER:
                    st.markdown("### ➕ Log Another Problem & Resolution")
                    st.info("Describe the issue you experienced, its possible cause, and what action you took to resolve it. This will be logged for Ground.")

                    with st.form("prev_main_other_form", clear_on_submit=True):
                        custom_problem = st.text_input("What was the problem or symptom?")
                        custom_cause = st.text_input("What do you think was the possible cause?")
                        custom_solution = st.text_area("How did you solve or manage the problem?")
                        saved_main = st.form_submit_button("Save and prepare report for Ground")

                    if saved_main:
                        if custom_problem.strip() and custom_cause.strip():
                            st.session_state.prevention_log.append({
                                "Date": datetime.date.today().isoformat(),
                                "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                                "Crew Member": selected_crew,
                                "Problem": custom_problem.strip(),
                                "Possible cause": custom_cause.strip(),
                                "Action / Solution taken": custom_solution.strip() if custom_solution.strip() else "Pending / Monitored",
                            })
                            st.success("Report saved.")
                        else:
                            st.warning("Please enter at least the problem and the possible cause.")

                    if st.session_state.prevention_log:
                        st.markdown("#### Reports for Ground")
                        st.dataframe(pd.DataFrame(st.session_state.prevention_log), use_container_width=True, hide_index=True)
                        last = st.session_state.prevention_log[-1]
                        st.caption("Message ready to send (use the copy button):")
                        st.code(
                            f"NON-URGENT REPORT | {last['Date']} {last['Time']}\n"
                            f"Crew member: {last['Crew Member']}\n"
                            f"Problem: {last['Problem']}\n"
                            f"Possible cause: {last['Possible cause']}\n"
                            f"Solution / Action taken: {last.get('Action / Solution taken', 'N/A')}\n"
                            f"Please advise.",
                            language=None,
                        )

                # 2. Vista especial multimedia cuando se selecciona "🏋️ Exercise"
                elif p == "🏋️ Exercise":
                    st.markdown("### 🏋️ Space Exercise & Countermeasures")
                    st.caption(
                        f"NASA Requirement: **{NASA_EXERCISE_DAILY_TARGET:.1f} h/day** (6–7 days/week) to prevent "
                        "1–1.5% monthly bone density loss and muscle atrophy."
                    )

                    today_iso = datetime.date.today().isoformat()
                    any_ex_completed = False

                    tabs = st.tabs(list(exercise_library.keys()))
                    for tab, (category, exercises) in zip(tabs, exercise_library.items()):
                        with tab:
                            for ex in exercises:
                                with st.container(border=True):
                                    c_info, c_media = st.columns([1.2, 1])
                                    with c_info:
                                        st.markdown(f"#### {ex['name']}")
                                        st.caption(f"**Target:** {ex['target']}")
                                        st.info(f"**Prescription:** {ex['dosage']}")
                                        for step in ex["instructions"]:
                                            st.markdown(f"- {step}")

                                        done_key = f"ex_done_{today_iso}_{selected_crew}_{ex['name']}"
                                        is_done = st.checkbox("Completed today", key=done_key)
                                        if is_done:
                                            any_ex_completed = True

                                    with c_media:
                                        media_src = ex.get("media", "")
                                        if media_src.startswith("http"):
                                            st.video(media_src)
                                        elif media_src and os.path.exists(media_src):
                                            if media_src.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi")):
                                                st.video(media_src)
                                            else:
                                                st.image(media_src, use_container_width=True)
                                        else:
                                            st.info(f"📹 Place your NASA video file **`{media_src}`** in the project folder to display it here.")

                    if any_ex_completed:
                        st.session_state.habits_done[f"{today_iso}_{selected_crew}_1"] = True
                        if selected_crew != "No Crew Members Available":
                            if st.button("Log 2.0h Countermeasure Session to Clinical Records", key="log_prev_ex_to_df"):
                                baseline_bmd = get_crew_baseline_bmd(selected_crew)
                                new_ex_entry = pd.DataFrame([{
                                    "Date": today_iso,
                                    "Time": datetime.datetime.now().time().replace(microsecond=0).strftime("%H:%M:%S"),
                                    "Crew Member": selected_crew,
                                    "View": "Body",
                                    "Zone": "Leg",
                                    "Details / Metrics": f"Exercise: {NASA_EXERCISE_DAILY_TARGET:.1f}h | BMD_gcm2: {baseline_bmd:.2f} g/cm2 | Bone Density: 100.0%",
                                    "Notes": "Completed via Prevention Exercise Module"
                                }])
                                st.session_state.records_df = pd.concat(
                                    [st.session_state.records_df, new_ex_entry],
                                    ignore_index=True
                                )
                                st.success(f"2.0h exercise session logged in Clinical Records & History for {selected_crew}!")

                # 3. Vista cuando se seleccionó un problema Y una causa específica
                elif p in prevention_data and c in prevention_data[p]:
                    data = prevention_data[p][c]
                    st.markdown(f"### {c}")
                    st.info(data["why"])

                    if "warning" in data:
                        st.warning(data["warning"])

                    if c == OTHER:
                        problem_name = p.split(" ", 1)[-1]
                        with st.form("prev_other_form", clear_on_submit=True):
                            other_cause = st.text_input("What is the other possible cause?")
                            other_solution = st.text_area("How did you solve or manage it? (Optional)")
                            saved = st.form_submit_button("Save and prepare message for Ground")
                        if saved:
                            if other_cause.strip():
                                st.session_state.prevention_log.append({
                                    "Date": datetime.date.today().isoformat(),
                                    "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                                    "Crew Member": selected_crew,
                                    "Problem": problem_name,
                                    "Possible cause": other_cause.strip(),
                                    "Action / Solution taken": other_solution.strip() if other_solution.strip() else "N/A",
                                })
                                st.success("Saved.")
                            else:
                                st.warning("Write the cause first.")

                        if st.session_state.prevention_log:
                            st.markdown("#### Reports for Ground")
                            st.dataframe(pd.DataFrame(st.session_state.prevention_log), use_container_width=True, hide_index=True)
                            last = st.session_state.prevention_log[-1]
                            st.caption("Message ready to send (use the copy button):")
                            st.code(
                                f"NON-URGENT REPORT | {last['Date']} {last['Time']}\n"
                                f"Crew member: {last['Crew Member']}\n"
                                f"Problem: {last['Problem']}\n"
                                f"Possible cause: {last['Possible cause']}\n"
                                f"Solution / Action taken: {last.get('Action / Solution taken', 'N/A')}\n"
                                f"Please advise.",
                                language=None,
                            )

                    st.markdown("#### What you can do")
                    for tip in data["tips"]:
                        st.markdown(f"- {tip}")

                    if c != OTHER and p in category_general_tips:
                        with st.expander(f"Habits that help in any {p.split(' ', 1)[-1].lower()} case"):
                            for tip in category_general_tips[p]:
                                st.markdown(f"- {tip}")

                # 4. Vista por defecto vinculada en tiempo real con records_df
                else:
                    if p in prevention_data and prevention_data[p]:
                        st.info(f"👈 **{p} selected.** Now choose a possible cause from the blue list on the left to view protocols.")
                    else:
                        st.info("👈 **Step 1:** Select a problem on the left.  |  **Step 2:** Choose a possible cause to view action protocols.")

                    st.markdown(f"### Telemetry Prevention Summary — {selected_crew}")
                    df = st.session_state.records_df

                    if selected_crew == "No Crew Members Available":
                        st.warning("No crew members registered yet. Create a mission and crew member in 'Basic crew information' first.")
                    else:
                        crew_forehead = df[(df["Crew Member"] == selected_crew) & (df["Zone"] == "Forehead")]
                        sleep_vals, moods = [], []
                        for text in crew_forehead["Details / Metrics"]:
                            parsed = extract_metrics_from_text(str(text))
                            if "Sleep" in parsed:
                                sleep_vals.append(parsed["Sleep"])
                            m_mood = re.search(r"Mood:\s*([^|]+)", str(text))
                            if m_mood:
                                moods.append(m_mood.group(1).strip())

                        total_rad = get_cumulative_radiation(df, selected_crew)
                        weekly_ex = get_weekly_exercise_summary(df, selected_crew, datetime.date.today())

                        c1, c2, c3, c4 = st.columns(4)
                        if sleep_vals:
                            c1.metric("Last Sleep", f"{sleep_vals[-1]:.1f} h", f"{sleep_vals[-1] - 7.0:+.1f} h vs 7h goal")
                        else:
                            c1.metric("Last Sleep", "No data")

                        c2.metric("Last Mood", moods[-1] if moods else "No data")
                        c3.metric("Cumulative Radiation", f"{total_rad:.2f} mSv", f"{max(0.0, 600.0 - total_rad):.2f} mSv left", delta_color="off")
                        c4.metric("7-Day Exercise", f"{weekly_ex['days_active']}/6 days", f"{weekly_ex['total_hours']:.1f} h total", delta_color="off")

                        if sleep_vals and sleep_vals[-1] < 7.0:
                            st.warning(f"Last recorded sleep ({sleep_vals[-1]:.1f} h) was below the 7.0 h NASA target. Sleep protocols can help.")
                            if st.button("Open Sleep protocols", key="prev_open_sleep"):
                                st.session_state.prev_problem = "😴 Sleep"
                                st.rerun()

                        if moods and any(m in moods[-1] for m in ["Anxious", "Overwhelmed", "Stressed", "Sad", "Irritable"]):
                            st.warning(f"Recent mood logged as **{moods[-1]}**. Consider reviewing Anxiety or Mood & Isolation protocols.")
                            col_b1, col_b2 = st.columns(2)
                            with col_b1:
                                if st.button("Open Anxiety Crisis protocols", key="prev_open_anx"):
                                    st.session_state.prev_problem = "😰 Anxiety Crisis"
                                    st.rerun()
                            with col_b2:
                                if st.button("Open Mood & Isolation protocols", key="prev_open_mood"):
                                    st.session_state.prev_problem = "🧠 Mood & Isolation"
                                    st.rerun()

                        if total_rad >= 450.0:
                            st.warning(f"Cumulative radiation is elevated ({total_rad:.2f} mSv / 600 mSv limit). Review Radiation shielding & antioxidant protocols.")
                            if st.button("Open Radiation protocols", key="prev_open_rad"):
                                st.session_state.prev_problem = "☢️ Radiation"
                                st.rerun()

                        if weekly_ex["days_active"] < NASA_EXERCISE_WEEKLY_MIN_DAYS:
                            st.info(f"7-day exercise compliance is **{weekly_ex['days_active']}/6 days** ({weekly_ex['total_hours']:.1f} h). Maintain daily ARED/T2 countermeasures.")
                            if st.button("Open Exercise modules", key="prev_open_ex"):
                                st.session_state.prev_problem = "🏋️ Exercise"
                                st.rerun()

                        if not sleep_vals and not moods and total_rad == 0.0 and weekly_ex["total_hours"] == 0.0:
                            st.caption(f"No telemetry records yet for {selected_crew}. Save data in 'Record symptoms or data' to activate personalized alerts.")

            st.markdown("---")
            st.markdown("#### Daily habits")

            habits = [
                "Sleep 7 to 8 hours",
                "Do my daily exercise",
                "Eat balanced meals and drink water",
                "Do relaxation or breathing exercises",
                "Talk with someone (crew, family or support team)",
            ]
            today_key = f"{datetime.date.today()}_{selected_crew}"
            done_habits = st.session_state.setdefault("habits_done", {})

            if selected_crew != "No Crew Members Available" and not st.session_state.records_df.empty:
                today_str = datetime.date.today().isoformat()
                today_records = st.session_state.records_df[
                    (st.session_state.records_df["Crew Member"] == selected_crew)
                    & (st.session_state.records_df["Date"] == today_str)
                ]
                for _, r in today_records.iterrows():
                    m_today = extract_metrics_from_text(str(r.get("Details / Metrics", "")))
                    if r.get("Zone") == "Forehead" and m_today.get("Sleep", 0.0) >= 7.0:
                        done_habits[f"{today_key}_0"] = True
                    if r.get("Zone") == "Leg" and m_today.get("Exercise", 0.0) >= NASA_EXERCISE_DAILY_TARGET:
                        done_habits[f"{today_key}_1"] = True

            for i, habit in enumerate(habits):
                k = f"{today_key}_{i}"
                done_habits[k] = st.checkbox(habit, value=done_habits.get(k, False), key=f"habit_{k}")

            done = sum(v for k, v in done_habits.items() if k.startswith(today_key))
            st.progress(done / len(habits), text=f"{done} of {len(habits)} habits done today")

            celebrated_key = f"celebrated_{today_key}"
            if done == len(habits):
                st.markdown(
                    """
                    <div class="star-celebration">
                        <span class="star-icon">✨</span>
                        All daily prevention habits completed! Mission readiness optimal.
                        <span class="star-icon">✨</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if not st.session_state.get(celebrated_key, False):
                    st.balloons()
                    st.session_state[celebrated_key] = True
            else:
                st.session_state[celebrated_key] = False

    elif st.session_state.menu == "Register":
        with st.container(border=True):
            st.subheader("Register Workspace")

            render_anatomy_map(
                view_key="map_view",
                zone_key="selected_zone",
                chart_prefix="chart",
                marker_color="#ef4444",
                height=520,
                fallback_zone="Heart"
            )

            zone = st.session_state.selected_zone
            st.info(f"Selected Zone: {zone}")

            metrics_summary = ""
            uploaded_medical_img = None

            with st.form(f"zone_metrics_form_{zone}"):
                col_d, col_t = st.columns(2)
                with col_d:
                    record_date = st.date_input("Record Date", value=datetime.date.today())
                with col_t:
                    record_time = st.time_input("Record Time", value=datetime.datetime.now().time().replace(microsecond=0))

                if zone == "Forehead":
                    prev_radiation = get_cumulative_radiation(st.session_state.records_df, selected_crew)
                    st.caption(f"Current Cumulative Radiation for {selected_crew}: **{prev_radiation:.2f} mSv** ")

                    mood = st.selectbox(
                        "Mood",
                        [
                            "😢 Sad",
                            "😠 Irritable",
                            "😰 Anxious",
                            "😴 Tired",
                            "😄 Cheerful",
                            "🤯 Overwhelmed",
                            "😫 Stressed",
                            "😐 Indifferent"
                        ]
                    )
                    sleep_hours = st.number_input("Sleep (hours)", min_value=0.0, max_value=24.0, value=7.5, step=0.5)
                    radiation = st.number_input("Session Radiation Dose (mSv)", min_value=0.0, value=st.session_state.default_radiation, step=0.05)
                    new_cumulative_rad = round(prev_radiation + radiation, 2)
                    metrics_summary = f"Mood: {mood} | Sleep: {sleep_hours}h | Radiation: {radiation} mSv | Cumulative Radiation: {new_cumulative_rad} mSv"

                elif zone == "Eyes":
                    uploaded_medical_img = st.file_uploader("Upload Medical Image", type=["png", "jpg", "jpeg"])
                    eye_status = st.selectbox("Ocular Check", ["Normal", "Dryness", "Blurred Vision", "Pressure", "Difficulty focusing up close", "Blind spots"])
                    metrics_summary = f"Ocular: {eye_status} | Image: {uploaded_medical_img.name if uploaded_medical_img else 'None'}"

                elif zone == "Nose":
                    st.caption("Normal Reference Range: **32.9 – 36.5 mL/kg/min**")
                    oxygenation = st.number_input(
                        "Oxygenation Rate (mL/kg/min)",
                        min_value=10.0,
                        max_value=60.0,
                        value=34.5,
                        step=0.1
                    )
                    metrics_summary = f"Oxygenation: {oxygenation} mL/kg/min"

                elif zone == "Heart":
                    st.caption("Reference Ranges — Heart Rate: **40–180 BPM** | Systolic BP: **90–130 mmHg** | Diastolic BP: **60–85 mmHg** | Pulse Pressure: **30–50 mmHg**")
                    bpm = st.number_input("Heart Rate (BPM)", min_value=20, max_value=240, value=72, step=1)
                    col_bp1, col_bp2 = st.columns(2)
                    with col_bp1:
                        systolic_bp = st.number_input("Systolic BP (mmHg)", min_value=50, max_value=220, value=115, step=1)
                    with col_bp2:
                        diastolic_bp = st.number_input("Diastolic BP (mmHg)", min_value=30, max_value=140, value=75, step=1)
                    pulse_pressure = systolic_bp - diastolic_bp
                    metrics_summary = (
                        f"BPM: {bpm} | Systolic BP: {systolic_bp} mmHg | "
                        f"Diastolic BP: {diastolic_bp} mmHg | Pulse Pressure: {pulse_pressure} mmHg"
                    )

                elif zone == "Leg":
                    baseline_bmd = get_crew_baseline_bmd(selected_crew)
                    st.caption(
                        f"Pre-mission Baseline BMD for {selected_crew}: **{baseline_bmd:.2f} g/cm²** | "
                        f"Limits: **≥ {NASA_BMD_HIP_SPINE_MIN:.0f}%** (Hip/Spine) • **≥ {NASA_BMD_FEMORAL_NECK_MIN:.0f}%** (Femoral Neck) | "
                        f"Exercise Target: **{NASA_EXERCISE_DAILY_TARGET:.1f} h/day (6–7 days/week)**"
                    )
                    exercise_hours = st.number_input("Exercise (hours/day)", min_value=0.0, max_value=12.0, value=2.0, step=0.25)
                    current_bmd_gcm2 = st.number_input(
                        "Current Bone Mineral Density (g/cm²)",
                        min_value=0.30,
                        max_value=2.00,
                        value=baseline_bmd,
                        step=0.01
                    )
                    bmd_pct = round((current_bmd_gcm2 / baseline_bmd) * 100.0, 1) if baseline_bmd > 0 else 100.0
                    metrics_summary = f"Exercise: {exercise_hours}h | BMD_gcm2: {current_bmd_gcm2:.2f} g/cm2 | Bone Density: {bmd_pct:.1f}%"

                elif zone == "Hand":
                    st.caption(
                        f"Thermal Limits — Nominal: **{NASA_TEMP_NOMINAL_LOW:.1f}–{NASA_TEMP_NOMINAL_HIGH:.1f} °C** | "
                        f"Caution: **35.0–36.0 °C / 38.0–39.5 °C** | Critical Emergency: **≤ {NASA_TEMP_CRITICAL_LOW:.1f} °C or ≥ {NASA_TEMP_CRITICAL_HIGH:.1f} °C**"
                    )
                    temp_c = st.number_input("Temperature (°C)", min_value=25.0, max_value=45.0, value=36.6, step=0.1)
                    skin_symptoms = st.multiselect("Skin Symptoms", ["None", "Rash", "Redness", "Swelling", "Dryness"], default=["None"])
                    metrics_summary = f"Temp: {temp_c}°C | Skin: {', '.join(skin_symptoms)}"

                notes = st.text_input("Notes", placeholder="Optional notes...")
                save_btn = st.form_submit_button("Save Record")

                if save_btn:
                    hora_str = record_time.strftime("%H:%M:%S")
                    new_idx = len(st.session_state.records_df)
                    if uploaded_medical_img is not None:
                        st.session_state.uploaded_images[new_idx] = {
                            "name": uploaded_medical_img.name,
                            "bytes": uploaded_medical_img.getvalue()
                        }

                    new_entry = pd.DataFrame([{
                        "Date": record_date.isoformat(),
                        "Time": hora_str,
                        "Crew Member": selected_crew,
                        "View": st.session_state.map_view.capitalize(),
                        "Zone": zone,
                        "Details / Metrics": metrics_summary,
                        "Notes": notes
                    }])
                    st.session_state.records_df = pd.concat(
                        [st.session_state.records_df, new_entry],
                        ignore_index=True
                    )
                    st.success(f"Record saved for {record_date.isoformat()} at {hora_str}.")

                    if zone == "Forehead":
                        if new_cumulative_rad >= 600.0:
                            trigger_emergency_redirect(
                                emergency_type="Other Emergency",
                                crew_member=selected_crew,
                                description=(
                                    f"CRITICAL RADIATION EXPOSURE: Cumulative radiation reached {new_cumulative_rad} mSv "
                                    f"(Session: {radiation} mSv), exceeding NASA 600 mSv career limit."
                                    + (f" Notes: {notes}" if notes else "")
                                ),
                                date_obj=record_date,
                                time_obj=record_time,
                                record_idx=new_idx,
                                tag="[CRITICAL RADIATION -> EMERGENCY]"
                            )
                        elif any(m in mood for m in ["Anxious", "Overwhelmed", "Stressed"]) and sleep_hours < 5.0:
                            trigger_emergency_redirect(
                                emergency_type="Psychological Emergency",
                                crew_member=selected_crew,
                                description=(
                                    f"ACUTE PSYCHOLOGICAL DISTRESS: Crew member reported '{mood}' mood combined with "
                                    f"severe sleep deprivation ({sleep_hours}h)."
                                    + (f" Notes: {notes}" if notes else "")
                                ),
                                date_obj=record_date,
                                time_obj=record_time,
                                record_idx=new_idx,
                                tag="[PSYCHOLOGICAL EMERGENCY]"
                            )
                        else:
                            if sleep_hours < 7.0:
                                st.warning(
                                    "Sleep below 7 hours detected. Recommendation: Perform relaxation techniques "
                                    "(guided breathing, progressive muscle relaxation, or mindfulness)."
                                )
                                st.session_state.prevention_nudge = {
                                    "crew": selected_crew,
                                    "problem": "😴 Sleep",
                                    "msg": f"Sleep below 7 hours detected ({sleep_hours}h). Recommended: Review Sleep & Relaxation protocols."
                                }
                            elif any(m in mood for m in ["Anxious", "Overwhelmed", "Stressed", "Sad", "Irritable"]):
                                target_prev = "😰 Anxiety Crisis" if any(m in mood for m in ["Anxious", "Overwhelmed", "Stressed"]) else "🧠 Mood & Isolation"
                                st.session_state.prevention_nudge = {
                                    "crew": selected_crew,
                                    "problem": target_prev,
                                    "msg": f"Mood logged as '{mood}'. Recommended: Review {target_prev.split(' ', 1)[-1]} prevention protocols."
                                }
                            elif new_cumulative_rad >= 450.0:
                                st.warning(f"HIGH CUMULATIVE RADIATION: {selected_crew} is at {new_cumulative_rad} mSv.")
                                st.session_state.prevention_nudge = {
                                    "crew": selected_crew,
                                    "problem": "☢️ Radiation",
                                    "msg": f"Cumulative radiation at {new_cumulative_rad} mSv. Recommended: Review Radiation shielding & antioxidant protocols."
                                }
                            else:
                                st.session_state.prevention_nudge = None

                    elif zone == "Eyes":
                        if eye_status == "Blind spots":
                            trigger_emergency_redirect(
                                emergency_type="Other Emergency",
                                crew_member=selected_crew,
                                description=(
                                    "ACUTE OCULAR / NEUROLOGICAL ALERT: Crew member reported blind spots during ocular check "
                                    "(possible SANS / visual field deficit)."
                                    + (f" Notes: {notes}" if notes else "")
                                ),
                                date_obj=record_date,
                                time_obj=record_time,
                                record_idx=new_idx,
                                tag="[OCULAR EMERGENCY]"
                            )
                        else:
                            st.session_state.prevention_nudge = None

                    elif zone == "Leg":
                        weekly_ex = get_weekly_exercise_summary(st.session_state.records_df, selected_crew, record_date)
                        if exercise_hours < NASA_EXERCISE_DAILY_TARGET:
                            st.warning(
                                f"**EXERCISE REMINDER**: Today's session is **{exercise_hours:.2f} h** "
                                f"(NASA daily requirement: **{NASA_EXERCISE_DAILY_TARGET:.1f} h/day**, 6–7 days/week). "
                                f"7-day compliance: **{weekly_ex['days_active']}/6 days** ({weekly_ex['total_hours']:.1f} h / {NASA_EXERCISE_WEEKLY_TARGET_HRS:.0f} h target). "
                                "Please schedule an ARED resistive + aerobic countermeasure session."
                            )
                            st.session_state.prevention_nudge = {
                                "crew": selected_crew,
                                "problem": "🏋️ Exercise",
                                "msg": f"Exercise session ({exercise_hours:.2f}h) is below NASA's 2.0h daily target."
                            }
                        elif weekly_ex["days_active"] < NASA_EXERCISE_WEEKLY_MIN_DAYS:
                            st.info(
                                f"**WEEKLY EXERCISE TRACKER**: Daily goal achieved ({exercise_hours:.2f} h), "
                                f"but 7-day compliance is **{weekly_ex['days_active']}/6 days** ({weekly_ex['total_hours']:.1f} h). "
                                "Maintain 2.0 h/day to reach the 6–7 days/week NASA countermeasure target."
                            )
                            st.session_state.prevention_nudge = None
                        else:
                            st.success(
                                f"Exercise countermeasure nominal: {exercise_hours:.2f} h today | "
                                f"7-day compliance: {weekly_ex['days_active']} days ({weekly_ex['total_hours']:.1f} h)."
                            )
                            st.session_state.prevention_nudge = None

                        if bmd_pct < NASA_BMD_CRITICAL_FRACTURE:
                            trigger_emergency_redirect(
                                emergency_type="Trauma / Injury",
                                crew_member=selected_crew,
                                description=(
                                    f"CRITICAL BONE MINERAL DENSITY LOSS: "
                                    f"Current BMD {current_bmd_gcm2:.2f} g/cm² ({bmd_pct:.1f}% of {baseline_bmd:.2f} g/cm² baseline; "
                                    f"severely below 90% femoral neck / 95% hip & spine limits). High fracture risk."
                                    + (f" Notes: {notes}" if notes else "")
                                ),
                                date_obj=record_date,
                                time_obj=record_time,
                                record_idx=new_idx,
                                tag="[CRITICAL BMD LOSS -> EMERGENCY]"
                            )
                        elif bmd_pct < NASA_BMD_HIP_SPINE_MIN:
                            bmd_level = (
                                f"BELOW FEMORAL NECK LIMIT (< {NASA_BMD_FEMORAL_NECK_MIN:.0f}%)"
                                if bmd_pct < NASA_BMD_FEMORAL_NECK_MIN
                                else f"BELOW HIP & SPINE LIMIT ({NASA_BMD_FEMORAL_NECK_MIN:.0f}% – {NASA_BMD_HIP_SPINE_MIN:.0f}%)"
                            )
                            st.session_state.leg_alert_state = {
                                "crew": selected_crew,
                                "bmd": bmd_pct,
                                "bmd_gcm2": current_bmd_gcm2,
                                "baseline_bmd": baseline_bmd,
                                "exercise": exercise_hours,
                                "level": bmd_level,
                                "record_idx": new_idx,
                                "date_obj": record_date,
                                "time_obj": record_time,
                                "notes": notes,
                            }
                        else:
                            st.session_state.leg_alert_state = None
                            st.success(
                                f"Bone Mineral Density at {current_bmd_gcm2:.2f} g/cm² ({bmd_pct:.1f}% of baseline) complies with "
                                f"Limits (≥ {NASA_BMD_HIP_SPINE_MIN:.0f}% Hip/Spine, ≥ {NASA_BMD_FEMORAL_NECK_MIN:.0f}% Femoral Neck)."
                            )

                    elif zone == "Hand":
                        if temp_c >= NASA_TEMP_CRITICAL_HIGH or temp_c <= NASA_TEMP_CRITICAL_LOW:
                            cond = (
                                f"Severe Hyperthermia (≥ {NASA_TEMP_CRITICAL_HIGH}°C)"
                                if temp_c >= NASA_TEMP_CRITICAL_HIGH
                                else f"Moderate/Severe Hypothermia (≤ {NASA_TEMP_CRITICAL_LOW}°C)"
                            )
                            trigger_emergency_redirect(
                                emergency_type="Other Emergency",
                                crew_member=selected_crew,
                                description=(
                                    f"CRITICAL NASA THERMAL LIMIT EXCEEDED ({cond}): Recorded temperature {temp_c}°C. "
                                    f"Skin symptoms: {', '.join(skin_symptoms)}."
                                    + (f" Notes: {notes}" if notes else "")
                                ),
                                date_obj=record_date,
                                time_obj=record_time,
                                temp=str(temp_c),
                                record_idx=new_idx,
                                tag="[CRITICAL THERMAL -> EMERGENCY]"
                            )
                        elif temp_c < NASA_TEMP_NOMINAL_LOW or temp_c > NASA_TEMP_NOMINAL_HIGH:
                            status_txt = (
                                "LOW — Mild Hypothermia Risk (35.0–36.0 °C)"
                                if temp_c < NASA_TEMP_NOMINAL_LOW
                                else "HIGH — Thermal Stress / Fever Risk (38.0–39.5 °C)"
                            )
                            st.session_state.hand_alert_state = {
                                "crew": selected_crew,
                                "temp": temp_c,
                                "status": status_txt,
                                "skin": ", ".join(skin_symptoms),
                                "record_idx": new_idx,
                                "date_obj": record_date,
                                "time_obj": record_time,
                                "notes": notes,
                            }
                        else:
                            st.session_state.hand_alert_state = None
                            st.success(
                                f"Temperature ({temp_c}°C) is within NASA nominal limits "
                                f"({NASA_TEMP_NOMINAL_LOW:.1f} – {NASA_TEMP_NOMINAL_HIGH:.1f} °C)."
                            )

                    elif zone == "Nose":
                        if oxygenation < 32.9 or oxygenation > 36.5:
                            st.session_state.nose_alert_state = {
                                "crew": selected_crew,
                                "value": oxygenation,
                                "status": "LOW (Hypoxia Risk)" if oxygenation < 32.9 else "HIGH (Elevated Oxygen Demand)",
                                "high_hr": has_recent_high_hr(st.session_state.records_df, selected_crew),
                                "record_idx": new_idx,
                                "date_obj": record_date,
                                "time_obj": record_time,
                                "notes": notes,
                            }
                        else:
                            st.session_state.nose_alert_state = None
                            st.success(f"Oxygenation ({oxygenation} mL/kg/min) is within the normal range (32.9 – 36.5 mL/kg/min).")

                    elif zone == "Heart":
                        hr_out = bpm < 40 or bpm > 180
                        bp_out = (
                            systolic_bp < 90 or systolic_bp > 130
                            or diastolic_bp < 60 or diastolic_bp > 85
                            or pulse_pressure < 30 or pulse_pressure > 50
                        )
                        if hr_out or bp_out:
                            reasons = []
                            if bpm < 40:
                                reasons.append(f"Bradycardia ({bpm} BPM < 40)")
                            elif bpm > 180:
                                reasons.append(f"Tachycardia ({bpm} BPM > 180)")
                            if systolic_bp < 90 or diastolic_bp < 60:
                                reasons.append(f"Hypotension ({systolic_bp}/{diastolic_bp} mmHg)")
                            elif systolic_bp > 130 or diastolic_bp > 85:
                                reasons.append(f"Hypertension ({systolic_bp}/{diastolic_bp} mmHg)")
                            if pulse_pressure < 30 or pulse_pressure > 50:
                                reasons.append(f"Abnormal Pulse Pressure ({pulse_pressure} mmHg)")

                            reasons_str = ", ".join(reasons)

                            if bpm < 35 or bpm > 200:
                                trigger_emergency_redirect(
                                    emergency_type="Cardiac Emergency",
                                    crew_member=selected_crew,
                                    description=(
                                        f"CRITICAL HEMODYNAMIC INSTABILITY: {reasons_str}. "
                                        f"BP: {systolic_bp}/{diastolic_bp} mmHg."
                                        + (f" Notes: {notes}" if notes else "")
                                    ),
                                    date_obj=record_date,
                                    time_obj=record_time,
                                    hr=str(bpm),
                                    record_idx=new_idx,
                                    tag="[CRITICAL CARDIAC -> EMERGENCY]"
                                )

                            st.session_state.heart_alert_state = {
                                "crew": selected_crew,
                                "bpm": bpm,
                                "sbp": systolic_bp,
                                "dbp": diastolic_bp,
                                "pp": pulse_pressure,
                                "reasons": reasons_str,
                                "high_oxy": has_recent_high_oxygenation(st.session_state.records_df, selected_crew),
                                "record_idx": new_idx,
                                "date_obj": record_date,
                                "time_obj": record_time,
                                "notes": notes,
                            }
                        else:
                            st.session_state.heart_alert_state = None
                            st.success(
                                f"Hemodynamics nominal: {bpm} BPM | BP {systolic_bp}/{diastolic_bp} mmHg | "
                                f"Pulse Pressure {pulse_pressure} mmHg."
                            )

            # Botón persistente hacia Prevention cuando se detecta una oportunidad preventiva
            nudge = st.session_state.get("prevention_nudge")
            if nudge and nudge["crew"] == selected_crew:
                st.info(f"🛡️ **PREVENTION RECOMMENDATION**: {nudge['msg']}")
                if st.button("Go to Prevention Protocols", key="go_to_prev_nudge_btn"):
                    st.session_state.prev_problem = nudge["problem"]
                    st.session_state.prev_cause = None
                    st.session_state.prevention_nudge = None
                    st.session_state.menu = "Prevention"
                    st.rerun()

            if uploaded_medical_img is not None:
                st.image(uploaded_medical_img, caption=f"Uploaded Medical Image: {uploaded_medical_img.name}", width=300)

            if zone == "Forehead":
                st.markdown(f"#### Mood & Sleep Agenda — {selected_crew}")
                mood_agenda = get_mood_schedule_df(st.session_state.records_df, crew_member=selected_crew)
                if not mood_agenda.empty:
                    st.dataframe(
                        mood_agenda[["Date", "Time", "Mood", "Sleep", "Notes"]],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.caption(f"No mood entries recorded yet for {selected_crew}.")

            if zone == "Leg" and st.session_state.leg_alert_state is not None:
                l_alert = st.session_state.leg_alert_state
                if l_alert["crew"] == selected_crew:
                    st.warning(
                        f"**BONE DENSITY ALERT ({l_alert['level']})**: "
                        f"Recorded BMD is **{l_alert['bmd_gcm2']:.2f} g/cm² ({l_alert['bmd']:.1f}%** of {l_alert['baseline_bmd']:.2f} g/cm² pre-mission baseline; "
                        f"Required: ≥ 95% Hip & Spine, ≥ 90% Femoral Neck)."
                    )

                    leg_symptoms_list = [
                        "Acute hip, spine, or leg pain",
                        "Pain during ARED load-bearing exercise",
                        "Swelling, bruising, or joint instability",
                        "Recent impact or suspected stress fracture",
                        "Muscle weakness / inability to bear load"
                    ]

                    selected_leg_symptoms = st.multiselect(
                        "Does the crew member present any musculoskeletal or injury symptoms?",
                        options=leg_symptoms_list,
                        key="leg_symptoms_selector"
                    )

                    if st.button("Confirm Musculoskeletal Check", key="confirm_leg_symptoms_btn"):
                        idx = l_alert["record_idx"]
                        if selected_leg_symptoms:
                            symp_str = ", ".join(selected_leg_symptoms)
                            trigger_emergency_redirect(
                                emergency_type="Trauma / Injury",
                                crew_member=selected_crew,
                                description=(
                                    f"BONE COUNTERMEASURE & INJURY ALERT ({l_alert['level']}): "
                                    f"BMD at {l_alert['bmd_gcm2']:.2f} g/cm² ({l_alert['bmd']:.1f}% baseline) | Exercise: {l_alert['exercise']:.2f}h. "
                                    f"Confirmed symptoms: {symp_str}."
                                    + (f" Notes: {l_alert['notes']}" if l_alert.get("notes") else "")
                                ),
                                date_obj=l_alert.get("date_obj", datetime.date.today()),
                                time_obj=l_alert.get("time_obj", datetime.datetime.now().time().replace(microsecond=0)),
                                record_idx=idx,
                                tag=f"Musculoskeletal Symptoms: {symp_str} [EMERGENCY]"
                            )
                        else:
                            st.warning(
                                "**BONE COUNTERMEASURE ESCALATION**: No acute injury symptoms reported. "
                                "Increase ARED resistive exercise protocol (2.0 h/day, 6–7 days/week), verify Vitamin D & Calcium intake, "
                                "and schedule bone density re-evaluation."
                            )
                            if idx in st.session_state.records_df.index:
                                st.session_state.records_df.at[idx, "Details / Metrics"] += " | Musculoskeletal Symptoms: None [BMD COUNTERMEASURE]"
                            st.session_state.leg_alert_state = None
                            st.session_state.prevention_nudge = {
                                "crew": selected_crew,
                                "problem": "🏋️ Exercise",
                                "msg": "BMD below nominal without acute injury. Recommended: Follow ARED resistive countermeasures."
                            }
                            st.rerun()

            if zone == "Hand" and st.session_state.hand_alert_state is not None:
                t_alert = st.session_state.hand_alert_state
                if t_alert["crew"] == selected_crew:
                    st.warning(
                        f"**NASA THERMAL CAUTION ({t_alert['status']})**: "
                        f"Recorded temperature **{t_alert['temp']}°C** is outside the nominal 36.0 – 38.0 °C range."
                    )

                    thermal_symptoms_list = [
                        "Uncontrolled shivering",
                        "Loss of hand dexterity / numbness",
                        "Confusion / slowed cognition",
                        "Dizziness / weakness",
                        "Profuse sweating or hot dry skin",
                        "Blisters or severe skin pain"
                    ]

                    selected_thermal_symptoms = st.multiselect(
                        "Does the crew member present any thermal stress or hypothermia symptoms?",
                        options=thermal_symptoms_list,
                        key="hand_symptoms_selector"
                    )

                    if st.button("Confirm Thermal Check", key="confirm_hand_symptoms_btn"):
                        idx = t_alert["record_idx"]
                        if selected_thermal_symptoms:
                            symp_str = ", ".join(selected_thermal_symptoms)
                            em_category = (
                                "Burns"
                                if "Blisters or severe skin pain" in selected_thermal_symptoms
                                else "Other Emergency"
                            )
                            trigger_emergency_redirect(
                                emergency_type=em_category,
                                crew_member=selected_crew,
                                description=(
                                    f"NASA THERMAL ALERT ({t_alert['status']}): Temp {t_alert['temp']}°C | "
                                    f"Skin: {t_alert['skin']}. Confirmed symptoms: {symp_str}."
                                    + (f" Notes: {t_alert['notes']}" if t_alert.get("notes") else "")
                                ),
                                date_obj=t_alert.get("date_obj", datetime.date.today()),
                                time_obj=t_alert.get("time_obj", datetime.datetime.now().time().replace(microsecond=0)),
                                temp=str(t_alert["temp"]),
                                record_idx=idx,
                                tag=f"Thermal Symptoms: {symp_str} [EMERGENCY]"
                            )
                        else:
                            st.warning(
                                "**THERMAL MONITORING ALERT**: No systemic symptoms reported. "
                                "Adjust suit LCVG / cabin thermal control and re-check temperature in 10 minutes."
                            )
                            if idx in st.session_state.records_df.index:
                                st.session_state.records_df.at[idx, "Details / Metrics"] += " | Thermal Symptoms: None [MONITOR]"
                            st.session_state.hand_alert_state = None

            if zone == "Nose" and st.session_state.nose_alert_state is not None:
                alert_info = st.session_state.nose_alert_state
                if alert_info["crew"] == selected_crew:
                    st.warning(
                        f"**OUT-OF-RANGE OXYGENATION ({alert_info['status']})**: "
                        f"Recorded value **{alert_info['value']} mL/kg/min** (Normal: 32.9 – 36.5 mL/kg/min)."
                    )
                    if alert_info["value"] > 36.5 and alert_info["high_hr"]:
                        st.info("Note: High oxygenation combined with elevated heart rate may indicate recent physical activity.")

                    hypoxia_symptoms_list = [
                        "Fainting",
                        "Dizziness",
                        "Shortness of breath",
                        "Headache",
                        "Clumsiness / impaired movement",
                        "Excessive sweating",
                        "Bluish lips"
                    ]

                    selected_hypoxia_symptoms = st.multiselect(
                        "Does the crew member present any of the following symptoms?",
                        options=hypoxia_symptoms_list,
                        key="nose_symptoms_selector"
                    )

                    if st.button("Confirm Symptom Check", key="confirm_nose_symptoms_btn"):
                        idx = alert_info["record_idx"]
                        if selected_hypoxia_symptoms:
                            symp_str = ", ".join(selected_hypoxia_symptoms)
                            cons_state = "Unresponsive" if "Fainting" in selected_hypoxia_symptoms else "Alert"
                            trigger_emergency_redirect(
                                emergency_type="Respiratory Emergency",
                                crew_member=selected_crew,
                                description=(
                                    f"RESPIRATORY / HYPOXIA ALERT ({alert_info['status']}): Oxygenation at {alert_info['value']} mL/kg/min. "
                                    f"Confirmed symptoms: {symp_str}."
                                    + (f" Notes: {alert_info['notes']}" if alert_info.get("notes") else "")
                                ),
                                date_obj=alert_info.get("date_obj", datetime.date.today()),
                                time_obj=alert_info.get("time_obj", datetime.datetime.now().time().replace(microsecond=0)),
                                consciousness=cons_state,
                                record_idx=idx,
                                tag=f"Symptoms: {symp_str} [EMERGENCY]"
                            )
                        else:
                            st.warning(
                                "**SENSOR / PREVENTIVE ALERT**: No symptoms reported, but oxygenation remains out of range. "
                                "Verify mask/sensor seal and re-measure in 2 minutes."
                            )
                            if idx in st.session_state.records_df.index:
                                st.session_state.records_df.at[idx, "Details / Metrics"] += " | Symptoms: None [ALERT]"
                            st.session_state.nose_alert_state = None
          
            if zone == "Heart" and st.session_state.heart_alert_state is not None:
                h_alert = st.session_state.heart_alert_state
                if h_alert["crew"] == selected_crew:
                    st.warning(
                        f"**OUT-OF-RANGE CARDIOVASCULAR READING**: Detected — **{h_alert['reasons']}**."
                    )
                    if h_alert["bpm"] > 100 and h_alert["high_oxy"]:
                        st.info("Note: Elevated heart rate combined with high oxygenation (> 36.5 mL/kg/min) indicates physical activity.")

                    heart_symptoms_list = [
                        "Shortness of breath",
                        "Fatigue",
                        "Dizziness",
                        "Chest pain",
                        "Fainting"
                    ]

                    selected_heart_symptoms = st.multiselect(
                        "Does the crew member present any of the following symptoms?",
                        options=heart_symptoms_list,
                        key="heart_symptoms_selector"
                    )

                    if st.button("Confirm Cardiovascular Check", key="confirm_heart_symptoms_btn"):
                        idx = h_alert["record_idx"]
                        if selected_heart_symptoms:
                            symp_str = ", ".join(selected_heart_symptoms)
                            cons_state = "Unresponsive" if "Fainting" in selected_heart_symptoms else "Alert"
                            trigger_emergency_redirect(
                                emergency_type="Cardiac Emergency",
                                crew_member=selected_crew,
                                description=(
                                    f"CARDIAC ALERT: {h_alert['reasons']} | BP: {h_alert['sbp']}/{h_alert['dbp']} mmHg. "
                                    f"Confirmed symptoms: {symp_str}."
                                    + (f" Notes: {h_alert['notes']}" if h_alert.get("notes") else "")
                                ),
                                date_obj=h_alert.get("date_obj", datetime.date.today()),
                                time_obj=h_alert.get("time_obj", datetime.datetime.now().time().replace(microsecond=0)),
                                hr=str(h_alert["bpm"]),
                                consciousness=cons_state,
                                record_idx=idx,
                                tag=f"Symptoms: {symp_str} [EMERGENCY]"
                            )
                        else:
                            st.warning(
                                "**SENSOR READJUSTMENT REQUIRED**: No symptoms reported. "
                                "Please readjust the chest/wrist biometric sensor and repeat the measurement."
                            )
                            if idx in st.session_state.records_df.index:
                                st.session_state.records_df.at[idx, "Details / Metrics"] += " | Symptoms: None [READJUST SENSOR]"
                            st.session_state.heart_alert_state = None

            st.dataframe(st.session_state.records_df, use_container_width=True)

    elif st.session_state.menu == "History":
        with st.container(border=True):
            st.subheader("Clinical History — Body & Head Map")

            render_anatomy_map(
                view_key="history_map_view",
                zone_key="history_selected_zone",
                chart_prefix="history_chart",
                marker_color="#38bdf8",
                height=500,
                fallback_zone="Heart"
            )

            h_zone = st.session_state.history_selected_zone
            st.markdown(f"### Clinical Charts — {h_zone}")

            df_all = st.session_state.records_df.copy()
            df_zone = df_all[df_all["Zone"] == h_zone].copy() if (not df_all.empty and "Zone" in df_all.columns) else pd.DataFrame()

            if df_zone.empty:
                st.info(f"No clinical records yet for '{h_zone}'. Register entries in 'Record symptoms or data' with this zone.")
            else:
                sort_cols = [c for c in ["Date", "Time"] if c in df_zone.columns]
                if sort_cols:
                    df_zone = df_zone.sort_values(sort_cols)

                extracted_rows = df_zone["Details / Metrics"].apply(extract_metrics_from_text)
                metrics_df = pd.DataFrame(list(extracted_rows), index=df_zone.index)
                base_cols = [c for c in ["Date", "Crew Member", "Notes"] if c in df_zone.columns]
                chart_df = pd.concat([df_zone[base_cols], metrics_df], axis=1)

                numeric_cols = [
                    c for c in metrics_df.columns
                    if metrics_df[c].notna().any()
                    and not (h_zone == "Nose" and c == "SpO2")
                    and not (h_zone == "Heart" and c == "Diastolic BP")
                ]          

                metric_options = list(numeric_cols)
                if h_zone == "Forehead":
                    metric_options.append("Mood Agenda")

                if metric_options:
                    selected_metric = st.selectbox(
                        f"Metric to plot for {h_zone}",
                        options=metric_options,
                        key=f"metric_select_{h_zone}"
                    )

                    with st.container(key=f"viz_box_{h_zone}_{selected_metric}"):
                        if selected_metric == "Mood Agenda":
                            st.markdown("#### Crew Mood & Sleep Agenda")
                            mood_agenda = get_mood_schedule_df(st.session_state.records_df)
                            if not mood_agenda.empty:
                                st.dataframe(mood_agenda, use_container_width=True, hide_index=True)
                            else:
                                st.info("No mood entries recorded yet.")
                        else:
                            palette_morada = [
                                "#D8B4FE",
                                "#38BDF8",
                                "#F472B6",
                                "#A78BFA",
                                "#FBBF24",
                                "#34D399"
                            ]

                            fig_clin = go.Figure()
                            x_axis_col = "Date" if "Date" in chart_df.columns else chart_df.index

                            plot_df = chart_df.copy()
                            if h_zone == "Leg" and selected_metric == "Exercise" and "Notes" in plot_df.columns:
                                plot_df = plot_df[plot_df["Notes"] != "Pre-mission baseline BMD"]

                            for i, (crew, grp) in enumerate(plot_df.dropna(subset=[selected_metric]).groupby("Crew Member")):
                                color_linea = palette_morada[i % len(palette_morada)]
                                fig_clin.add_trace(go.Scatter(
                                    x=grp[x_axis_col] if "Date" in plot_df.columns else grp.index,
                                    y=grp[selected_metric],
                                    mode="lines+markers",
                                    name=crew,
                                    line=dict(color=color_linea, width=3),
                                    marker=dict(
                                        size=9,
                                        color=color_linea,
                                        line=dict(width=2, color="#0f172a")
                                    )
                                ))

                            if h_zone == "Hand" and selected_metric == "Temp":
                                fig_clin.add_hrect(
                                    y0=NASA_TEMP_NOMINAL_LOW,
                                    y1=NASA_TEMP_NOMINAL_HIGH,
                                    fillcolor="rgba(52, 211, 153, 0.10)",
                                    line_width=0,
                                    annotation_text="NASA Nominal Zone (36.0–38.0°C)",
                                    annotation_position="top left",
                                    annotation_font_color="#34D399",
                                    annotation_font_size=11
                                )
                                fig_clin.add_hline(
                                    y=NASA_TEMP_CRITICAL_HIGH,
                                    line_dash="dash",
                                    line_color="#ef4444",
                                    line_width=2,
                                    annotation_text="NASA Critical Hyperthermia (39.5°C)",
                                    annotation_position="top right",
                                    annotation_font_color="#fca5a5"
                                )
                                fig_clin.add_hline(
                                    y=NASA_TEMP_NOMINAL_HIGH,
                                    line_dash="dot",
                                    line_color="#f59e0b",
                                    line_width=1.5,
                                    annotation_text="Upper Nominal Limit (38.0°C)",
                                    annotation_position="bottom right",
                                    annotation_font_color="#fcd34d"
                                )
                                fig_clin.add_hline(
                                    y=NASA_TEMP_NOMINAL_LOW,
                                    line_dash="dot",
                                    line_color="#38bdf8",
                                    line_width=1.5,
                                    annotation_text="Lower Nominal Limit (36.0°C)",
                                    annotation_position="top right",
                                    annotation_font_color="#7dd3fc"
                                )
                                fig_clin.add_hline(
                                    y=NASA_TEMP_CRITICAL_LOW,
                                    line_dash="dash",
                                    line_color="#ef4444",
                                    line_width=2,
                                    annotation_text="NASA Critical Hypothermia (35.0°C)",
                                    annotation_position="bottom right",
                                    annotation_font_color="#fca5a5"
                                )
                                y_vals = plot_df["Temp"].dropna()
                                y_min = min(34.2, float(y_vals.min()) - 0.5) if not y_vals.empty else 34.2
                                y_max = max(40.3, float(y_vals.max()) + 0.5) if not y_vals.empty else 40.3
                                fig_clin.update_yaxes(range=[y_min, y_max])

                            elif h_zone == "Leg" and selected_metric == "Bone Density":
                                fig_clin.add_hrect(
                                    y0=NASA_BMD_HIP_SPINE_MIN,
                                    y1=105.0,
                                    fillcolor="rgba(52, 211, 153, 0.10)",
                                    line_width=0,
                                    annotation_text="Nominal Zone (≥ 95%)",
                                    annotation_position="top left",
                                    annotation_font_color="#34D399",
                                    annotation_font_size=11
                                )
                                fig_clin.add_hline(
                                    y=NASA_BMD_HIP_SPINE_MIN,
                                    line_dash="dot",
                                    line_color="#f59e0b",
                                    line_width=2,
                                    annotation_text="Hip & Spine Limit (95% Baseline)",
                                    annotation_position="top right",
                                    annotation_font_color="#fcd34d"
                                )
                                fig_clin.add_hline(
                                    y=NASA_BMD_FEMORAL_NECK_MIN,
                                    line_dash="dash",
                                    line_color="#ef4444",
                                    line_width=2,
                                    annotation_text="Femoral Neck Limit (90% Baseline)",
                                    annotation_position="bottom right",
                                    annotation_font_color="#fca5a5"
                                )
                                y_vals = plot_df["Bone Density"].dropna()
                                y_min = min(87.0, float(y_vals.min()) - 2.0) if not y_vals.empty else 87.0
                                y_max = max(103.0, float(y_vals.max()) + 2.0) if not y_vals.empty else 103.0
                                fig_clin.update_yaxes(range=[y_min, y_max])

                            elif h_zone == "Leg" and selected_metric == "Exercise":
                                fig_clin.add_hline(
                                    y=NASA_EXERCISE_DAILY_TARGET,
                                    line_dash="dash",
                                    line_color="#34D399",
                                    line_width=2,
                                    annotation_text="NASA Daily Countermeasure Target (2.0 h/day)",
                                    annotation_position="top right",
                                    annotation_font_color="#34D399"
                                )
                                y_vals = plot_df["Exercise"].dropna()
                                y_max = max(3.0, float(y_vals.max()) + 0.5) if not y_vals.empty else 3.0
                                fig_clin.update_yaxes(range=[0, y_max])

                            y_label = selected_metric
                            if h_zone == "Hand" and selected_metric == "Temp":
                                y_label = "Temperature (°C)"
                            elif h_zone == "Leg" and selected_metric == "Bone Density":
                                y_label = "Bone Mineral Density (% Pre-Mission)"
                            elif h_zone == "Leg" and selected_metric == "BMD_gcm2":
                                y_label = "Bone Mineral Density (g/cm²)"
                            elif h_zone == "Leg" and selected_metric == "Exercise":
                                y_label = "Exercise Duration (hours)"

                            fig_clin.update_layout(
                                title=dict(
                                    text=f"{h_zone} — {selected_metric} over Date",
                                    font=dict(color="#D8B4FE", size=17)
                                ),
                                xaxis_title="Date",
                                yaxis_title=y_label,
                                height=380 if h_zone in ("Hand", "Leg") else 350,
                                paper_bgcolor="rgba(17, 24, 39, 0.85)",
                                plot_bgcolor="rgba(17, 24, 39, 0.55)",
                                font=dict(color="#e2e8f0", size=12),
                                legend=dict(
                                    bgcolor="rgba(17, 24, 39, 0.9)",
                                    bordercolor="rgba(216, 180, 254, 0.35)",
                                    borderwidth=1,
                                    font=dict(color="#e2e8f0")
                                ),
                                xaxis=dict(
                                    showgrid=True,
                                    gridcolor="rgba(167, 139, 250, 0.16)",
                                    linecolor="rgba(216, 180, 254, 0.3)",
                                    tickfont=dict(color="#cbd5e1", size=11)
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor="rgba(167, 139, 250, 0.16)",
                                    linecolor="rgba(216, 180, 254, 0.3)",
                                    tickfont=dict(color="#cbd5e1", size=11)
                                )
                            )
                            st.plotly_chart(fig_clin, use_container_width=True, key=f"clin_plot_{h_zone}_{selected_metric}")
                else:
                    st.caption("This zone's current entries have categorical or image metrics rather than numeric series.")

                cols_to_show = [c for c in ["Date", "Time", "Crew Member", "Details / Metrics", "Notes"] if c in df_zone.columns]
                st.dataframe(df_zone[cols_to_show], use_container_width=True)

                if h_zone == "Eyes":
                    saved_imgs = [
                        (idx, st.session_state.uploaded_images[idx], df_zone.loc[idx])
                        for idx in df_zone.index
                        if idx in st.session_state.uploaded_images
                    ]
                    if saved_imgs:
                        st.markdown("#### Saved Ocular Images")
                        img_cols = st.columns(min(len(saved_imgs), 3))
                        for i, (_, img_data, row_info) in enumerate(saved_imgs):
                            with img_cols[i % 3]:
                                st.image(
                                    img_data["bytes"],
                                    caption=f"{row_info['Crew Member']} ({row_info['Date']} {row_info['Time']}) - {img_data['name']}",
                                    use_container_width=True
                                )

    elif st.session_state.menu == "Emergency":
        with st.container(border=True):
            st.subheader("Emergency Protocols and Communication")
            st.caption("CREW SAFETY • EMERGENCY RESPONSE • GROUND COMMUNICATION")

            if "emergency_records" not in st.session_state:
                st.session_state.emergency_records = pd.DataFrame(columns=EMERGENCY_COLUMNS)

            handoff = st.session_state.pop("pending_emergency_handoff", None)
            if handoff:
                st.session_state.em_type = handoff["em_type"]
                if handoff["em_crew"] in all_crew_members:
                    st.session_state.em_crew = handoff["em_crew"]
                    st.session_state.em_crew_sync = handoff["em_crew"]
                st.session_state.em_desc = handoff["em_desc"]
                st.session_state.em_date = handoff["em_date"]
                st.session_state.em_time = handoff["em_time"]
                st.session_state.em_vs_hr = handoff.get("em_vs_hr", "")
                st.session_state.em_vs_temp = handoff.get("em_vs_temp", "")
                st.session_state.em_vs_cons = handoff.get("em_vs_cons", "Alert")
                st.toast(f"Automatic Emergency Activated: {handoff['em_type']}", icon="🚨")
            elif st.session_state.get("em_crew_sync") != selected_crew:
                st.session_state.em_crew = selected_crew
                st.session_state.em_crew_sync = selected_crew

            if st.session_state.active_emergency_banner:
                st.error(
                    f"🚨 **AUTOMATIC EMERGENCY ACTIVATED ({st.session_state.active_emergency_banner})**: "
                    "Telemetry data and protocol have been pre-loaded below. Follow immediate actions and contact Mission Control."
                )
            else:
                st.error(
                    "EMERGENCY NOTICE: If a crew member is in immediate danger, "
                    "activate the mission emergency response and contact Mission Control immediately."
                )

            col1, col2 = st.columns([1, 1.5])

            with col1:
                st.markdown("### Emergency Identification")

                emergency_type = st.selectbox(
                    "Select Emergency Type",
                    list(EMERGENCY_PROTOCOLS.keys()),
                    key="em_type",
                )
                protocol = EMERGENCY_PROTOCOLS[emergency_type]

                st.markdown(f"### {protocol['color']} {protocol['severity']}")
                st.info(protocol["description"])

                affected_crew = st.selectbox(
                    "Affected Crew Member",
                    all_crew_members,
                    key="em_crew",
                )

                st.text_area(
                    "Emergency Description",
                    placeholder="Describe the symptoms, incident or situation...",
                    key="em_desc",
                )

                st.markdown("### Incident Information")
                st.date_input("Emergency Date", value=datetime.date.today(), key="em_date")
                st.time_input(
                    "Emergency Time",
                    value=datetime.datetime.now().time().replace(microsecond=0),
                    key="em_time",
                )

            with col2:
                st.markdown("### Emergency Response Protocol")
                st.markdown(f"**Selected protocol: {emergency_type}**")

                spoken_text = (
                    f"Emergency protocol: {emergency_type}. Severity: {protocol['severity']}. "
                    "Immediate actions. "
                    + " ".join(f"Step {s}" for s in protocol["steps"])
                    + " Actions to avoid. "
                    + " ".join(protocol["avoid"])
                )
                speak_widget(spoken_text, lang="en-US")

                st.markdown("#### Immediate Actions — Step by Step")
                for step in protocol["steps"]:
                    st.markdown(
                        f"""
                        <div style="
                            background-color: rgba(30, 41, 59, 0.85);
                            border-left: 3px solid #A78BFA;
                            padding: 12px 15px;
                            border-radius: 6px;
                            margin-bottom: 9px;
                            color: #E2E8F0;
                            font-size: 14px;">
                            {step}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.markdown("#### Actions to Avoid")
                for warning in protocol["avoid"]:
                    st.warning(warning)

            st.markdown("---")
            st.markdown("### Communication with Mission Control")
            st.info(
                "During an emergency, communicate clearly and report the affected crew member, "
                "symptoms, time of onset, vital signs when available and actions already performed."
            )

            st.markdown("#### Vital Signs (optional)")
            v1, v2, v3, v4, v5 = st.columns(5)
            with v1:
                vs_consciousness = st.selectbox(
                    "Consciousness",
                    ["Not assessed", "Alert", "Responds to voice", "Responds to pain", "Unresponsive"],
                    key="em_vs_cons",
                )
            with v2:
                vs_hr = st.text_input("Heart rate (BPM)", placeholder="e.g. 110", key="em_vs_hr")
            with v3:
                vs_spo2 = st.text_input("SpO2 (%)", placeholder="e.g. 92", key="em_vs_spo2")
            with v4:
                vs_rr = st.text_input("Resp. rate (/min)", placeholder="e.g. 24", key="em_vs_rr")
            with v5:
                vs_temp = st.text_input("Temp (°C)", placeholder="e.g. 36.6", key="em_vs_temp")

            vitals_parts = []
            if vs_consciousness != "Not assessed":
                vitals_parts.append(f"Consciousness: {vs_consciousness}")
            if vs_hr.strip():
                vitals_parts.append(f"HR {vs_hr.strip()} BPM")
            if vs_spo2.strip():
                vitals_parts.append(f"SpO2 {vs_spo2.strip()}%")
            if vs_rr.strip():
                vitals_parts.append(f"RR {vs_rr.strip()}/min")
            if vs_temp.strip():
                vitals_parts.append(f"Temp {vs_temp.strip()}°C")
            vitals_text = ", ".join(vitals_parts) if vitals_parts else "not available"

            st.text_area(
                "Emergency Communication Report (additional notes)",
                placeholder=(
                    "Example: Current condition: ... Actions taken: ... "
                    "Requesting instructions for ..."
                ),
                key="em_comm",
            )

            auto_message = (
                f"MISSION CONTROL, MISSION CONTROL — MEDICAL EMERGENCY\n"
                f"Crew member: {st.session_state.em_crew}\n"
                f"Emergency type: {emergency_type} ({protocol['severity']})\n"
                f"Time of onset: {st.session_state.em_date.isoformat()} "
                f"{st.session_state.em_time.strftime('%H:%M:%S')}\n"
                f"Situation: {st.session_state.em_desc.strip() or '[describe symptoms/incident]'}\n"
                f"Vital signs: {vitals_text}\n"
                f"Actions taken: {st.session_state.get('em_actions', '').strip() or '[none yet]'}\n"
                f"Additional notes: {st.session_state.em_comm.strip() or '[none]'}\n"
                f"Requesting medical guidance. Over."
            )
            st.markdown("**Suggested message to transmit** (use the copy icon):")
            st.code(auto_message, language=None)

            st.markdown("---")
            st.markdown("### Emergency Actions & Incident Registration")

            st.text_area(
                "Actions Performed",
                placeholder="Describe the actions performed by the crew...",
                key="em_actions",
            )

            st.checkbox(
                "I confirm that the incident information has been reviewed.",
                key="em_confirm",
            )

            st.button(
                "SAVE EMERGENCY REPORT",
                type="primary",
                use_container_width=True,
                on_click=save_emergency_report,
            )

            feedback = st.session_state.pop("em_feedback", None)
            if feedback:
                kind, msg = feedback
                getattr(st, kind)(msg)

            st.markdown("---")
            st.markdown("### Emergency History")

            if not st.session_state.emergency_records.empty:
                st.dataframe(
                    st.session_state.emergency_records,
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "DOWNLOAD EMERGENCY REPORTS (CSV)",
                    data=st.session_state.emergency_records.to_csv(index=False).encode("utf-8"),
                    file_name="emergency_reports.csv",
                    mime="text/csv",
                )
            else:
                st.info("No emergency incidents have been registered yet.")

            st.caption(
                "SPACE CONTROL SYSTEM | Emergency protocols are educational guidance and must be "
                "validated against approved mission medical procedures and professional instructions."
            )