# medilink.py
# MediLink – Health Access App (offline-first, no API keys)
# Features:
# - Home: quick actions, date, randomized daily health tip
# - Smarter Symptom Checker: expanded rule-based conditions + red-flag urgent warnings
# - Health Library: categorized, searchable, offline content
# - Emergency: user-defined contacts, tel/WhatsApp/SMS actions, optional location share
# - Medication Reminder: JSON persistence, due-now alerts within app (no background services)

import streamlit as st
import datetime as dt
import json
import os
import random
import re
import urllib.parse
from typing import List, Dict, Any, Tuple

# ---------------------------
# Config / Paths
# ---------------------------
st.set_page_config(page_title="MediLink – Health Access App", layout="wide")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "medilink_data")
os.makedirs(DATA_DIR, exist_ok=True)

CONTACTS_FILE = os.path.join(DATA_DIR, "contacts.json")
REMINDERS_FILE = os.path.join(DATA_DIR, "reminders.json")

# ---------------------------
# Daily Tips
# ---------------------------
DAILY_TIPS = [
    "Drink clean water; carry a reusable bottle and aim for 6–8 cups daily.",
    "Sleep 7–9 hours; keep your phone away 30 minutes before bedtime.",
    "Wash hands with soap before meals and after using the restroom.",
    "Use mosquito nets and remove standing water to reduce malaria risk.",
    "30 minutes of brisk walking boosts mood and heart health.",
    "Eat a rainbow: include fruits & vegetables of different colors.",
    "Manage stress: 4-7-8 breathing—inhale 4s, hold 7s, exhale 8s.",
    "Limit sugary drinks; choose water or unsweetened tea.",
    "Check medicine expiry dates before use.",
    "If chest pain + shortness of breath → seek emergency care now.",
]

# ---------------------------
# JSON helpers
# ---------------------------
def _read_json(path: str, fallback):
    try:
        if not os.path.exists(path):
            _write_json(path, fallback)
            return fallback
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def _write_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Could not save file {os.path.basename(path)}: {e}")

# ---------------------------
# Contacts persistence
# ---------------------------
DEFAULT_CONTACTS = [
    {"name": "National Emergency (Nigeria)", "type": "Ambulance/Police/Fire", "phone": "112", "whatsapp": "", "address": "Nationwide"},
]

def load_contacts() -> List[Dict[str,str]]:
    data = _read_json(CONTACTS_FILE, DEFAULT_CONTACTS)
    if isinstance(data, list):
        return data
    return DEFAULT_CONTACTS

def save_contacts(contacts: List[Dict[str,str]]):
    _write_json(CONTACTS_FILE, contacts)

# ---------------------------
# Reminders persistence
# ---------------------------
def load_reminders() -> List[Dict[str,Any]]:
    data = _read_json(REMINDERS_FILE, [])
    if isinstance(data, list):
        return data
    return []

def save_reminders(reminders: List[Dict[str,Any]]):
    _write_json(REMINDERS_FILE, reminders)

# ---------------------------
# Phone / Message helpers
# ---------------------------
def normalize_phone_for_tel(num: str) -> str:
    num = (num or "").strip()
    allowed = "+0123456789"
    cleaned = "".join(ch for ch in num if ch in allowed)
    return cleaned or num

def normalize_phone_for_whatsapp(num: str) -> str:
    return "".join(ch for ch in (num or "") if ch.isdigit())

def google_maps_link(lat: str, lon: str) -> str:
    lat = (lat or "").strip()
    lon = (lon or "").strip()
    if not lat or not lon:
        return ""
    return f"https://maps.google.com/?q={urllib.parse.quote(lat)},{urllib.parse.quote(lon)}"

def build_message(user_msg: str, lat: str, lon: str) -> str:
    base = (user_msg or "").strip() or "Emergency! Please help."
    maps = google_maps_link(lat, lon)
    if maps:
        base += f"\nMy location: {maps}"
    return base

def whatsapp_link(phone: str, message: str) -> str:
    num = normalize_phone_for_whatsapp(phone)
    text = urllib.parse.quote(message or "")
    if not num:
        return ""
    return f"https://wa.me/{num}?text={text}"

def sms_link(phone: str, message: str) -> str:
    tel = normalize_phone_for_tel(phone)
    body = urllib.parse.quote(message or "")
    if not tel:
        return ""
    return f"sms:{tel}?&body={body}"

# ---------------------------
# Reminders utilities
# ---------------------------
def _parse_time_str(t: str) -> Tuple[int,int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", t or "")
    if not m:
        return (8,0)
    hh = max(0, min(23, int(m.group(1))))
    mm = max(0, min(59, int(m.group(2))))
    return (hh, mm)

def is_due_now(rem: Dict[str,Any], now: dt.datetime, tolerance_minutes: int = 2) -> bool:
    hh, mm = _parse_time_str(rem.get("time","08:00"))
    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta = abs((now - due).total_seconds()) / 60.0
    return (delta <= tolerance_minutes)

# ---------------------------
# Symptom Checker data
# ---------------------------
SYMPTOMS = [
    "fever", "headache", "chills", "vomiting", "diarrhea", "abdominal pain",
    "cough", "sore throat", "runny nose", "difficulty breathing",
    "chest pain", "fatigue", "loss of appetite", "joint pain",
    "rash", "dizziness", "high temperature (≥38°C)", "bloody stool",
    "shortness of breath", "sweating", "nausea", "weight loss", "night sweats",
    "persistent cough", "frequent urination", "excessive thirst", "stiffness", "swelling"
]

# Red flags mapping (keys appear in SYMPTOMS or mapped)
RED_FLAGS = {
    "chest pain": "Chest pain can indicate a heart or lung emergency.",
    "difficulty breathing": "Breathing difficulty is an emergency sign.",
    "shortness of breath": "Shortness of breath may require urgent care.",
    "bloody stool": "Blood in stool can be serious; seek urgent care.",
    "high temperature (≥38°C)": "High fever with other symptoms may need urgent care.",
    "persistent vomiting": "Risk of dehydration; seek care if severe.",
    "severe abdominal pain": "Could indicate appendicitis or another emergency.",
    "sudden weakness or slurred speech": "Possible stroke — seek emergency care immediately."
}

# Expanded condition rules with weights and thresholds
CONDITIONS = {
    "Malaria": {
        "weights": {"fever": 3, "chills": 2, "headache": 2, "fatigue": 1, "high temperature (≥38°C)": 2, "vomiting": 1},
        "advice": "Possible malaria. Rest, hydrate, and seek testing/treatment at a clinic.",
        "threshold": 4
    },
    "Typhoid": {
        "weights": {"fever": 2, "abdominal pain": 2, "headache": 1, "diarrhea": 2, "loss of appetite": 1, "vomiting": 1},
        "advice": "Possible typhoid. Drink clean water and see a doctor for testing.",
        "threshold": 4
    },
    "Common Cold / Flu": {
        "weights": {"cough": 1, "sore throat": 2, "runny nose": 2, "fatigue": 1, "headache": 1, "fever": 1},
        "advice": "Likely a cold or flu. Rest, fluids, and over-the-counter symptomatic care.",
        "threshold": 3
    },
    "COVID-19 (possible)": {
        "weights": {"fever": 2, "cough": 2, "sore throat": 1, "loss of appetite":1, "fatigue":2, "difficulty breathing":3},
        "advice": "Symptoms may match a respiratory infection such as COVID-19. Isolate and seek testing if available.",
        "threshold": 4
    },
    "Lower Respiratory Infection / Asthma": {
        "weights": {"cough": 2, "difficulty breathing": 3, "chest pain": 2, "shortness of breath":3, "fatigue": 1},
        "advice": "Possible chest infection or asthma exacerbation. Seek medical help if breathing is hard.",
        "threshold": 4
    },
    "Gastroenteritis / Food Poisoning": {
        "weights": {"vomiting": 2, "diarrhea": 2, "abdominal pain": 1, "nausea":1, "high temperature (≥38°C)":1},
        "advice": "Possible stomach infection or food poisoning. Hydrate with ORS; seek care if persistent.",
        "threshold": 3
    },
    "Dengue (consider regionally)": {
        "weights": {"fever": 2, "headache": 1, "joint pain": 2, "rash": 1, "high temperature (≥38°C)": 2},
        "advice": "Dengue possible—avoid NSAIDs, hydrate, and seek evaluation.",
        "threshold": 4
    },
    "Diabetes (possible indicators)": {
        "weights": {"frequent urination": 3, "excessive thirst": 3, "fatigue": 1, "weight loss":2},
        "advice": "Symptoms suggesting diabetes. See a clinic for blood sugar testing.",
        "threshold": 4
    },
    "Tuberculosis (possible)": {
        "weights": {"persistent cough": 3, "weight loss": 2, "night sweats": 2, "fever":1},
        "advice": "Persistent cough with weight loss/night sweats may suggest TB. Seek testing at a clinic.",
        "threshold": 4
    },
    "Arthritis (possible)": {
        "weights": {"joint pain": 2, "stiffness": 2, "swelling": 2},
        "advice": "Joint pain and stiffness may indicate arthritis or inflammatory condition. See a clinician for evaluation.",
        "threshold": 3
    },
    "Heart Attack (🚨 EMERGENCY)": {
        "weights": {"chest pain": 4, "shortness of breath": 4, "sweating": 2},
        "advice": "Severe chest pain with breathlessness and sweating could indicate a heart attack. Call emergency services immediately.",
        "threshold": 6
    },
    "Stroke (🚨 EMERGENCY suggestion)": {
        "weights": {"sudden weakness or slurred speech": 5, "dizziness":2, "sudden severe headache":3},
        "advice": "Sudden weakness or slurred speech may indicate stroke. Seek emergency care immediately.",
        "threshold": 5
    }
}

def score_conditions(selected: List[str]) -> List[Tuple[str,int,str,int]]:
    sel = set(selected)
    results = []
    for cond, spec in CONDITIONS.items():
        score = 0
        for s,w in spec["weights"].items():
            # Accept some mapping: allow 'shortness of breath' and 'difficulty breathing' synonyms
            if s in sel:
                score += w
            else:
                # synonyms mapping
                if s == "shortness of breath" and "difficulty breathing" in sel:
                    score += w
                if s == "difficulty breathing" and "shortness of breath" in sel:
                    score += w
                if s == "persistent cough" and "cough" in sel and "persistent cough" not in sel:
                    # small allowance: cough could be persistent
                    score += int(w/2)
        results.append((cond, score, spec["advice"], spec["threshold"]))
    results.sort(key=lambda x: x[1], reverse=True)
    return results

def red_flag_messages(selected: List[str]) -> List[str]:
    msgs = []
    sel = set(selected)
    # check known keys and some mappings
    for key, msg in RED_FLAGS.items():
        if key in sel:
            msgs.append(msg)
        # map phrases
        if key == "persistent vomiting" and "vomiting" in sel:
            msgs.append(msg)
        if key == "severe abdominal pain" and "abdominal pain" in sel:
            msgs.append(msg)
        if key == "sudden weakness or slurred speech":
            if "dizziness" in sel or "slurred speech" in sel or "sudden weakness" in sel:
                msgs.append(msg)
    # manual check for chest pain + shortness of breath combo
    if ("chest pain" in sel) and ("difficulty breathing" in sel or "shortness of breath" in sel):
        msgs.append("Combination of chest pain and breathing difficulty — this may be life-threatening.")
    return list(dict.fromkeys(msgs))  # unique

# ---------------------------
# Health Library data
# ---------------------------
HEALTH_LIBRARY: Dict[str, Dict[str, Any]] = {
    "First Aid": {
        "Bleeding": {
            "summary": "Apply direct pressure, clean with clean water, cover with a bandage.",
            "steps": [
                "Wash hands or wear gloves if available.",
                "Apply firm, direct pressure with a clean cloth.",
                "Elevate the injured area if possible.",
                "If bleeding is heavy or doesn't stop, seek emergency care."
            ],
            "prevention": ["Use gloves when treating wounds.", "Keep a first-aid kit accessible."]
        },
        "Burns": {
            "summary": "Cool burn under running water for 10–20 minutes; don't apply oil.",
            "steps": [
                "Remove tight items before swelling.",
                "Cool under running water for 10–20 minutes.",
                "Cover with a clean non-stick dressing.",
                "Seek care for large, deep, or face/genital burns."
            ]
        },
    },
    "Common Diseases": {
        "Malaria": {
            "summary": "Fever, chills, headache; prevent with nets and repellents; seek testing.",
            "symptoms": ["Fever", "Chills", "Headache", "Fatigue"],
            "treatment": ["Antimalarials as prescribed", "Hydration", "Rest"],
            "prevention": ["Use bed nets", "Eliminate standing water"]
        },
        "Typhoid": {
            "summary": "Fever, abdominal pain, diarrhoea; improve hygiene and water safety.",
            "symptoms": ["Fever", "Abdominal pain", "Diarrhea"],
            "prevention": ["Boil or treat water", "Wash hands"]
        },
        "Diabetes (basic info)": {
            "summary": "High blood sugar condition. Look out for thirst, frequent urination, weight loss.",
            "tips": ["See a clinic for testing", "Healthy diet and activity help manage blood sugar"]
        },
        "Pneumonia": {
            "summary": "Infection of the lungs causing cough, fever, and difficulty breathing. Seek medical care.",
            "tips": ["Keep hydrated", "Seek antibiotics if bacterial cause suspected"]
        }
    },
    "Mental Health": {
        "Stress": {
            "summary": "Manage with routines, breaks, and breathing exercises.",
            "tips": ["Try 4-7-8 breathing", "Break tasks into small steps"]
        },
        "Anxiety (mild)": {
            "summary": "Grounding techniques and routines can help; seek help if severe.",
            "tips": ["5-4-3-2-1 grounding method", "Keep a worry journal"]
        }
    },
    "Nutrition & Wellness": {
        "Hydration": {
            "summary": "Aim for regular fluid intake, especially in hot weather.",
            "tips": ["Carry a water bottle", "Increase fluids with activity or fever"]
        },
        "Healthy Plate": {
            "summary": "Half vegetables, quarter protein, quarter whole grains.",
            "tips": ["Include pulses/eggs/fish", "Limit added sugar"]
        }
    }
}

def search_library(query: str) -> List[Tuple[str,str]]:
    results = []
    q = (query or "").strip().lower()
    for cat, topics in HEALTH_LIBRARY.items():
        for topic, content in topics.items():
            blob = (topic + " " + json.dumps(content)).lower()
            if not q or q in topic.lower() or q in blob:
                results.append((cat, topic))
    return results

# ---------------------------
# UI / Pages
# ---------------------------
if "tip_index" not in st.session_state:
    st.session_state.tip_index = random.randrange(len(DAILY_TIPS))

def app_header():
    st.title("🏥 MediLink")
    st.write("Your trusted companion for basic health guidance and emergency support. *(Not a replacement for a doctor)*")

menu = st.sidebar.radio("Navigation", ["Home", "Symptom Checker", "Health Library", "Medication Reminder", "Emergency"])

app_header()

# ---------------- Home ----------------
if menu == "Home":
    st.subheader("Welcome 👋")
    today = dt.datetime.now()
    st.write(f"**Date:** {today.strftime('%A, %B %d, %Y')}")
    with st.container():
        st.markdown("### 🌿 Daily Health Tip")
        st.write(DAILY_TIPS[st.session_state.tip_index])
        col1, col2 = st.columns(2)
        with col1:
            if st.button("New Tip"):
                st.session_state.tip_index = random.randrange(len(DAILY_TIPS))
                st.rerun()
        with col2:
            st.caption("Tips are general and do not replace professional advice.")

    st.markdown("### Quick Actions")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("🩺 Symptom Checker"):
            st.session_state._goto = "Symptom Checker"
            st.rerun()
    with c2:
        if st.button("📚 Health Library"):
            st.session_state._goto = "Health Library"
            st.rerun()
    with c3:
        if st.button("🚨 Emergency"):
            st.session_state._goto = "Emergency"
            st.rerun()
    with c4:
        if st.button("💊 Medication Reminder"):
            st.session_state._goto = "Medication Reminder"
            st.rerun()

    # Show due reminders (in-app alert)
    reminders = load_reminders()
    now = dt.datetime.now()
    due_list = [r for r in reminders if is_due_now(r, now)]
    if due_list:
        st.warning("🔔 **Medication Due Now**")
        for r in due_list:
            st.write(f"- **{r.get('name','(Unnamed)')}** at **{r.get('time','')}** — {r.get('dosage','')}".strip())

# ---------------- Symptom Checker ----------------
elif menu == "Symptom Checker":
    st.subheader("🩺 Smarter Symptom Checker")
    st.caption("Select all symptoms that apply. For emergencies, call **112** (Nigeria).")

    selected = st.multiselect("Your symptoms:", SYMPTOMS, default=[])
    if st.button("Analyze"):
        flags = red_flag_messages(selected)
        if flags:
            with st.container():
                st.error("🚨 **Red Flags Detected** — consider urgent care:")
                for f in flags:
                    st.write(f"- {f}")
                st.write("If symptoms are severe or worsening, seek emergency help (call 112).")

        results = score_conditions(selected)
        st.markdown("### Possible Matches")
        found_any = False
        for cond, score, advice, threshold in results:
            if score >= threshold:
                found_any = True
                with st.expander(f"{cond} — Score {score} (threshold {threshold})", expanded=False):
                    st.write(advice)
        if not found_any:
            st.info("No strong match. Monitor symptoms, rest, hydrate, and consult a clinician if they persist or worsen.")
        st.caption("This tool is informational and not a diagnosis. When in doubt, contact a health professional.")

# ---------------- Health Library ----------------
elif menu == "Health Library":
    st.subheader("📚 Health Library (Offline)")
    query = st.text_input("Search topics or keywords", placeholder="e.g., Malaria, burns, hydration")
    matches = search_library(query)
    categories = ["All"] + list(HEALTH_LIBRARY.keys())
    cat_choice = st.selectbox("Filter by category", categories)
    if cat_choice != "All":
        matches = [(c,t) for (c,t) in matches if c == cat_choice]

    if not matches:
        st.info("No topics found. Try a different search.")
    else:
        for (cat, topic) in matches:
            content = HEALTH_LIBRARY[cat][topic]
            with st.expander(f"{topic} — *{cat}*"):
                if "summary" in content:
                    st.markdown(f"**Summary:** {content['summary']}")
                if "steps" in content:
                    st.markdown("**Steps:**")
                    for s in content["steps"]:
                        st.write(f"- {s}")
                if "symptoms" in content:
                    st.markdown("**Common Symptoms:**")
                    st.write(", ".join(content["symptoms"]))
                if "treatment" in content:
                    st.markdown("**Treatment:**")
                    for s in content["treatment"]:
                        st.write(f"- {s}")
                if "prevention" in content:
                    st.markdown("**Prevention:**")
                    for s in content["prevention"]:
                        st.write(f"- {s}")
                if "tips" in content:
                    st.markdown("**Tips:**")
                    for s in content["tips"]:
                        st.write(f"- {s}")
        st.caption("Information is educational and not a substitute for professional care.")

# ---------------- Medication Reminder ----------------
elif menu == "Medication Reminder":
    st.subheader("💊 Medication Reminder")
    st.caption("Reminders are stored locally in the medilink_data folder.")

    reminders = load_reminders()

    with st.container():
        st.markdown("### Add Reminder")
        col1, col2 = st.columns(2)
        with col1:
            med_name = st.text_input("Medicine name*", placeholder="e.g., Amoxicillin")
            dosage = st.text_input("Dosage / Note", placeholder="e.g., 500 mg after food")
        with col2:
            time_input = st.time_input("Time", dt.time(8,0))
            freq = st.selectbox("Frequency", ["Daily", "Twice a day", "Every 8 hours", "Custom (manual)"])
        if st.button("Save Reminder"):
            if not med_name:
                st.error("Medicine name is required.")
            else:
                hh = time_input.hour
                mm = time_input.minute
                reminders.append({
                    "name": med_name.strip(),
                    "time": f"{hh:02d}:{mm:02d}",
                    "frequency": freq,
                    "dosage": dosage.strip()
                })
                save_reminders(reminders)
                st.success(f"Saved reminder for **{med_name}** at **{hh:02d}:{mm:02d}**")
                st.rerun()

    if reminders:
        st.markdown("### Your Reminders")
        for i, r in enumerate(reminders):
            with st.container():
                st.write(f"**{r.get('name','(Unnamed)')}** — {r.get('dosage','')}")
                st.write(f"⏰ Time: **{r.get('time','')}**  |  📅 Frequency: **{r.get('frequency','Daily')}**")
                colA, colB = st.columns(2)
                with colA:
                    if st.button("Delete", key=f"del_{i}"):
                        del reminders[i]
                        save_reminders(reminders)
                        st.rerun()
                with colB:
                    now = dt.datetime.now()
                    if is_due_now(r, now):
                        st.warning("🔔 Due now")
                    else:
                        st.caption("Not due at this moment.")
    else:
        st.info("No reminders yet.")
    st.caption("Tip: For audible alerts, add the same time to your phone’s Clock/Calendar.")

# ---------------- Emergency ----------------
elif menu == "Emergency":
    st.subheader("🚨 Emergency")
    st.info("For immediate help in Nigeria, dial **112** (or your local emergency number).")

    contacts = load_contacts()

    with st.expander("➕ Add a local emergency contact"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Contact/Facility name*", placeholder="e.g., Garki Hospital")
            ctype = st.selectbox("Type*", ["Hospital", "Police", "Ambulance/EMS", "Fire Service", "Other"])
            phone = st.text_input("Phone number* (international format preferred)", placeholder="+2348012345678")
        with col2:
            whatsapp = st.text_input("WhatsApp number (optional, intl format)", placeholder="+2348012345678")
            address = st.text_input("Address / Area (optional)", placeholder="City, State")

        if st.button("Save Contact"):
            if not name or not phone:
                st.error("Name and Phone number are required.")
            else:
                contacts.append({
                    "name": name.strip(),
                    "type": ctype,
                    "phone": phone.strip(),
                    "whatsapp": whatsapp.strip(),
                    "address": address.strip()
                })
                save_contacts(contacts)
                st.success(f"Saved **{name}**")
                st.rerun()

    with st.expander("🗂️ Your Emergency Contacts", expanded=True):
        if contacts:
            for idx, c in enumerate(contacts):
                with st.container():
                    st.markdown(f"**{c['name']}** — *{c['type']}*")
                    if c.get("address"):
                        st.caption(c["address"])
                    tel_num = normalize_phone_for_tel(c["phone"])
                    st.markdown(f"[📞 Call](tel:{tel_num})  |  `{c['phone']}`")
                    colA, colB, colC = st.columns(3)
                    with colA:
                        if st.button("Remove", key=f"rm_{idx}"):
                            del contacts[idx]
                            save_contacts(contacts)
                            st.rerun()
                    with colB:
                        if c.get("whatsapp"):
                            wa_num = normalize_phone_for_whatsapp(c["whatsapp"])
                            st.markdown(f"[🟢 WhatsApp](https://wa.me/{wa_num})")
                        else:
                            st.caption("Add WhatsApp to enable quick chat.")
                    with colC:
                        # placeholder for future features
                        st.write("")
        else:
            st.info("No contacts yet. Add your nearest hospital/police station above.")

    st.markdown("---")
    st.subheader("📨 Send an Emergency Message (WhatsApp or SMS)")
    st.caption("Works best on a phone. On desktop, links open your default apps if available.")

    contact_names = [f"{c['name']} ({c['type']})" for c in contacts]
    if not contact_names:
        st.warning("Add at least one contact above to send messages.")
    else:
        sel = st.selectbox("Select contact", contact_names)
        selected_contact = contacts[contact_names.index(sel)]

        col1, col2 = st.columns(2)
        with col1:
            user_msg = st.text_area(
                "Your message",
                value="Emergency! I need help. Please contact me as soon as possible.",
                height=120
            )
        with col2:
            st.write("Optional location (manual entry):")
            lat = st.text_input("Latitude", placeholder="e.g., 6.465422")
            lon = st.text_input("Longitude", placeholder="e.g., 3.406448")
            st.caption("Tip: In Google Maps, long-press your location → copy coordinates.")

        final_msg = build_message(user_msg, lat, lon)
        st.write("**Preview:**")
        st.code(final_msg)

        colW, colS, colT = st.columns(3)
        with colW:
            wa_url = whatsapp_link(selected_contact.get("whatsapp",""), final_msg)
            if wa_url:
                st.markdown(f"[🟢 Send via WhatsApp]({wa_url})")
            else:
                st.caption("Add a WhatsApp number to this contact to enable WhatsApp messaging.")
        with colS:
            sms_url = sms_link(selected_contact.get("phone",""), final_msg)
            if sms_url:
                st.markdown(f"[✉️ Send via SMS]({sms_url})")
            else:
                st.caption("Phone number is missing or invalid for SMS link.")
        with colT:
            tel = normalize_phone_for_tel(selected_contact.get("phone",""))
            if tel:
                st.markdown(f"[📞 Call Now](tel:{tel})")
            else:
                st.caption("Phone number is missing or invalid for calling.")

    st.markdown("---")
    st.info("If you feel unwell or unsafe: call **112** (Nigeria) immediately and follow instructions.")


