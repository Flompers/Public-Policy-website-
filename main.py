# main.py
import time  # New import for sleep
import json
import random
import os
from datetime import datetime, timedelta
import difflib
from fpdf import FPDF  # for PDF export; ensure 'fpdf' is installed

import streamlit as st
import pandas as pd


# === Try to import gTTS; if missing, disable audio ===
try:
    from gtts import gTTS
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# === Page Configuration ===
st.set_page_config(
    page_title="Public Policy Flashcards & Smart Scheduler",
    layout="centered",
    initial_sidebar_state="expanded",
)

# === Paths for persistence ===
TERMS_PATH = "terms.json"
PROGRESS_PATH = "progress.json"
AUDIO_DIR = "audio_tts"
PDF_PATH = "flashcards_unknown.pdf"  # temporary PDF path

if TTS_AVAILABLE:
    os.makedirs(AUDIO_DIR, exist_ok=True)

# === Load Terms with Debugging Inside Function ===
@st.cache_data
def load_terms():
    # 1. Ensure the file exists
    if not os.path.exists(TERMS_PATH):
        st.sidebar.error("⚠️ terms.json not found! Please ensure 'terms.json' exists.")
        return []

    # 2. Load JSON array of term objects
    with open(TERMS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 3. Debug: Print first five term→author pairs
    st.sidebar.markdown("### Loaded Authors Debug")
    for idx, e in enumerate(data[:5]):
        author_name = e.get("author", "❌ missing author")
        st.sidebar.write(f"{idx+1}. {e.get('term','<no term>')} → {author_name}")

    return data

terms_list = load_terms()
df = pd.DataFrame(terms_list)

# === Load Progress (Known and Scheduler Data) ===
def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return {"known_terms": [], "scheduler": {}}

def save_progress(data):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)

progress_data = load_progress()
known_terms = set(progress_data.get("known_terms", []))
scheduler = progress_data.get("scheduler", {})

# === Helper: SM-2 Spaced Repetition Scheduling ===
def schedule_next(term, quality):
    """
    Simplified SM-2 scheduling:
    quality: 0 (forgot) to 5 (perfect)
    """
    entry = scheduler.get(term, {"interval": 0, "repetitions": 0, "ef": 2.5})
    interval = entry["interval"]
    repetitions = entry["repetitions"]
    ef = entry["ef"]

    if quality < 3:
        repetitions = 0
        interval = 1
    else:
        ef = max(1.3, ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        repetitions += 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = int(interval * ef)

    next_due = (datetime.now() + timedelta(days=interval)).isoformat()
    scheduler[term] = {"interval": interval, "repetitions": repetitions, "ef": ef, "next_due": next_due}
    progress_data["scheduler"] = scheduler
    save_progress(progress_data)

# === Audio Pronunciation (only if gTTS available) ===
def get_audio_path(term):
    safe_name = term.replace(" ", "_").replace("/", "_")
    return os.path.join(AUDIO_DIR, f"{safe_name}.mp3")

def ensure_audio(term):
    if not TTS_AVAILABLE:
        return None
    path = get_audio_path(term)
    if not os.path.exists(path):
        try:
            tts = gTTS(text=term, lang="en")
            tts.save(path)
        except Exception:
            return None
    return path

# === Sidebar: Reset Buttons ===
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Reset Options")
if st.sidebar.button("🔄 Reset Quiz Counters"):
    st.session_state.quiz_correct_count = 0
    st.session_state.quiz_total_asked = 0
    st.sidebar.success("🔁 Quiz counters reset.")

if st.sidebar.button("🗑️ Clear All Progress"):
    known_terms.clear()
    scheduler.clear()
    progress_data["known_terms"] = []
    progress_data["scheduler"] = {}
    save_progress(progress_data)
    st.session_state.quiz_correct_count = 0
    st.session_state.quiz_total_asked = 0
    st.sidebar.success("🗑️ All progress wiped.")


# === Sidebar: Pomodoro Tracker (Manual Refresh) ===
st.sidebar.markdown("---")
st.sidebar.subheader("⏲️ Pomodoro Tracker (Manual Refresh)")

# 1) Initialize or reset pomodoro_end in session_state if missing
if "pomodoro_end" not in st.session_state:
    st.session_state.pomodoro_end = None

# 2) Button to start a new 25-minute Pomodoro
if st.sidebar.button("▶️ Start 25-min Pomodoro"):
    st.session_state.pomodoro_end = datetime.now() + timedelta(minutes=25)

# 3) Button to stop the Pomodoro early
if st.sidebar.button("⏹️ Stop Pomodoro"):
    st.session_state.pomodoro_end = None

# 4) If pomodoro_end is set, show remaining time (or “Done”)
if st.session_state.pomodoro_end:
    remaining_secs = (st.session_state.pomodoro_end - datetime.now()).total_seconds()

    if remaining_secs <= 0:
        st.sidebar.success("✅ Pomodoro done! Take a 5-min break.")
        st.session_state.pomodoro_end = None
    else:
        mins, secs = divmod(int(remaining_secs), 60)
        st.sidebar.write(f"Time left: {mins:02d}:{secs:02d}")

        # 5) A manual “Refresh” button to recalculate and redraw the timer
        if st.sidebar.button("🔄 Refresh Timer"):
            # Re-run the script (nothing else needed; Streamlit will redraw)
            pass  # nothing here — clicking will simply rerun the script

# 6) If no Pomodoro is running, show a hint
else:
    st.sidebar.write("No Pomodoro running. Click ▶️ to start.")

# === Sidebar: Tag/Topic Filtering ===
st.sidebar.markdown("---")
st.sidebar.subheader("🏷️ Filter by Tags")
# Collect all unique tags from terms_list
all_tags = set()
for entry in terms_list:
    tags = entry.get("tags", [])
    for t in tags:
        all_tags.add(t)
all_tags = sorted(all_tags)

selected_tags = st.sidebar.multiselect("Select Tags", options=all_tags)
if selected_tags:
    filtered_tags_terms = [e for e in terms_list if set(e.get("tags", [])) & set(selected_tags)]
else:
    filtered_tags_terms = terms_list.copy()

# === Sidebar: Progress & Filters (after reset, pomodoro, tags) ===
st.sidebar.markdown("---")
st.sidebar.header("📊 Progress & Filters")

# Known terms count and progress bar
known_count = len(known_terms)
total_terms = len(terms_list)
st.sidebar.metric(label="✅ Known", value=f"{known_count}/{total_terms}")
st.sidebar.progress(known_count / total_terms if total_terms > 0 else 0)

# Export known terms as CSV
if known_terms:
    df_known = pd.DataFrame([{"term": t} for t in sorted(known_terms)])
    csv_data = df_known.to_csv(index=False).encode("utf-8")
    st.sidebar.download_button(
        label="📥 Download Known Terms CSV",
        data=csv_data,
        file_name="known_terms.csv",
        mime="text/csv",
    )

# Week Filter
st.sidebar.markdown("---")
st.sidebar.subheader("Filter by Week")
all_weeks = sorted({entry.get("week", 0) for entry in terms_list})
week_options = ["All"] + [str(w) for w in all_weeks]
selected_week = st.sidebar.selectbox("Select Week", week_options)

# Start with tag‐filtered terms; apply week filter next
if selected_week == "All":
    week_filtered = filtered_tags_terms.copy()
else:
    w = int(selected_week)
    week_filtered = [e for e in filtered_tags_terms if e.get("week") == w]

# Scheduler Filter: show only due terms
st.sidebar.markdown("---")
due_only = st.sidebar.checkbox("Show Only Due Terms", value=False)
if due_only:
    now_iso = datetime.now().isoformat()
    filtered_terms = [
        e for e in week_filtered
        if scheduler.get(e["term"], {}).get("next_due", "") <= now_iso
    ]
else:
    filtered_terms = week_filtered.copy()

# === Main Title ===
st.title("📚 Public Policy Flashcards & Smart Scheduler")
st.markdown(
    "Use the sidebar to filter by tags and weeks, track known terms, and see which are due for review.  \n"
    "You can also start a Pomodoro, reset progress, or export a PDF of unknown flashcards.  \n"
    "Choose a mode below: Flashcard Lookup or Quick Quiz."
)
st.markdown("---")
import unicodedata

# …earlier parts of main.py remain unchanged…

# === PDF Export of Unknown Flashcards ===
# (Prints a sanitized list: term at top, blank lines for definition)
st.subheader("📄 Printable Flashcards PDF")
if st.button("🖨️ Generate PDF for Unknown Terms"):
    # Filter out known terms
    unknown_terms = [e for e in filtered_terms if e["term"] not in known_terms]
    if not unknown_terms:
        st.info("🎉 You have no unknown terms under these filters!")
    else:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)

        # Use a basic Latin-1 font (like "Arial") but sanitize text
        pdf.set_font("Arial", size=16)

        for entry in unknown_terms:
            # 1) Normalize to NFKD, then remove anything not encodable in Latin-1
            raw_term = entry["term"]
            normalized = unicodedata.normalize("NFKD", raw_term)
            sanitized = normalized.encode("latin-1", "ignore").decode("latin-1")

            pdf.add_page()
            pdf.cell(0, 10, txt=sanitized, ln=True)

            # 2) Leave blank space for the definition (approx. 8 lines)
            pdf.set_font("Arial", size=12)
            for _ in range(8):
                pdf.ln(10)
            pdf.set_font("Arial", size=16)

        # 3) Save to a temporary path and offer download
        pdf.output(PDF_PATH)
        with open(PDF_PATH, "rb") as f:
            pdf_bytes = f.read()
        st.success(f"PDF generated with {len(unknown_terms)} pages.")
        st.download_button(
            label="⬇️ Download Flashcards PDF",
            data=pdf_bytes,
            file_name="flashcards_unknown.pdf",
            mime="application/pdf",
        )
st.markdown("---")

# === Initialize Quick Quiz Session State ===
if "quiz_current_term" not in st.session_state:
    st.session_state.quiz_current_term = None
if "quiz_correct_count" not in st.session_state:
    st.session_state.quiz_correct_count = 0
if "quiz_total_asked" not in st.session_state:
    st.session_state.quiz_total_asked = 0
if "quiz_checked" not in st.session_state:
    st.session_state.quiz_checked = False
if "quiz_ratio" not in st.session_state:
    st.session_state.quiz_ratio = 0.0

# === Mode Selector ===
mode = st.radio(
    "Choose a study mode:",
    ("Flashcard Lookup", "Quick Quiz"),
    horizontal=True
)

# === 1) Flashcard Lookup Mode ===
if mode == "Flashcard Lookup":
    st.subheader("🔍 Flashcard Lookup")

    available_terms = sorted([e["term"] for e in filtered_terms])
    # You can also add a live search here if you want. For now, a simple selectbox:
    choice = st.selectbox("▸ Pick a term to study:", [""] + available_terms)

    if choice:
        entry = next((e for e in filtered_terms if e["term"] == choice), None)
        if entry:
            # Flashcard Flip
            if "show_definition_for" not in st.session_state:
                st.session_state.show_definition_for = None

            if st.session_state.show_definition_for != choice:
                st.markdown(f"### **{entry['term']}**")

                c1, c2, c3 = st.columns(3)
                with c1:
                    if entry.get("hint"):
                        if st.button("💡 Show Hint"):
                            st.session_state.show_definition_for = f"HINT::{choice}"
                with c2:
                    if st.button("🔄 Show Definition"):
                        st.session_state.show_definition_for = choice
                with c3:
                    author_name = entry.get("author", "Unknown")
                    if st.button("👤 Show Author"):
                        st.info(f"**Author:** {author_name}")

            if st.session_state.show_definition_for in (choice, f"HINT::{choice}"):
                st.markdown(f"### **{entry['term']}**")

                # If hint-only was clicked
                if st.session_state.show_definition_for == f"HINT::{choice}":
                    st.info(f"**Hint:** {entry['hint']}")
                    if st.button("🔄 Now Show Definition"):
                        st.session_state.show_definition_for = choice

                if st.session_state.show_definition_for == choice:
                    st.markdown(f"**Definition:**  \n{entry['definition']}")

                    # Multimedia: image
                    if entry.get("image_url"):
                        try:
                            st.image(entry["image_url"], caption="Illustration", use_column_width=True)
                        except:
                            st.warning("⚠️ Could not load image.")

                    # Multimedia: example link
                    if entry.get("example_link"):
                        st.markdown(f"[🔗 View Example]({entry['example_link']})")

                    # Audio pronunciation (if available)
                    audio_path = ensure_audio(entry["term"])
                    if audio_path:
                        try:
                            audio_bytes = open(audio_path, "rb").read()
                            st.audio(audio_bytes, format="audio/mp3")
                        except:
                            pass  # skip audio if something goes wrong

                    # Related terms
                    if entry.get("related_terms"):
                        related = entry["related_terms"]
                        if related:
                            st.markdown("**Related Terms:** " + ", ".join(f"• {r}" for r in related))

                    # Mark Known/Unknown and schedule next review
                    st.markdown("---")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Mark as Known", key=f"known_{choice}"):
                            known_terms.add(choice)
                            progress_data["known_terms"] = list(known_terms)
                            save_progress(progress_data)
                    with col2:
                        if st.button("❌ Mark as Unknown", key=f"unknown_{choice}"):
                            known_terms.discard(choice)
                            progress_data["known_terms"] = list(known_terms)
                            save_progress(progress_data)

                    # Spaced Repetition: Quality slider
                    st.markdown("---")
                    st.markdown("**🔁 Rate Your Recall**")
                    quality = st.slider(
                        "0 = forgot completely, 5 = perfect recall",
                        min_value=0, max_value=5, value=3, key=f"slider_{choice}"
                    )
                    if st.button("Set Next Review", key=f"schedule_{choice}"):
                        schedule_next(choice, quality)
                        st.success("Next review date scheduled.")


# === 2) Quick Quiz Mode ===
else:
    st.subheader("📝 Quick Quiz Mode")
    st.markdown(
        "Click “Next Random Term” to get a term. Type your answer, ask for a hint if needed, "
        "then check your answer. You’ll see a similarity score and can mark Partial Correct. "
        "You can also show the author."
    )

    # (1) The original “Next Random Term” button at the top:
    if st.button("🔀 Next Random Term"):
        if filtered_terms:
            st.session_state.quiz_current_term = random.choice(filtered_terms)
            st.session_state.quiz_total_asked += 1
            st.session_state.quiz_checked = False
            st.session_state.quiz_ratio = 0.0
        else:
            st.warning("No terms available under these filters.")

    # (2) If there is a current term, show it:
    if st.session_state.quiz_current_term:
        term_obj = st.session_state.quiz_current_term
        st.markdown(f"### **What is:** `{term_obj['term']}`?")
        user_answer = st.text_area("Type your definition here:", height=100, key="user_answer")

        # Buttons: Hint / Show Author / Check Answer
        c1, c2, c3 = st.columns(3)
        with c1:
            if term_obj.get("hint"):
                if st.button("💡 Show Hint", key=f"quiz_hint_{term_obj['term']}"):
                    st.info(f"**Hint:** {term_obj['hint']}")
        with c2:
            author_name = term_obj.get("author", "Unknown")
            if st.button("👤 Show Author", key=f"quiz_author_{term_obj['term']}"):
                st.info(f"**Author:** {author_name}")
        with c3:
            if st.button("✔️ Check My Answer", key=f"check_{term_obj['term']}"):
                correct_def = term_obj["definition"].lower().strip()
                user_ans_norm = user_answer.lower().strip()
                ratio = difflib.SequenceMatcher(None, user_ans_norm, correct_def).ratio()
                st.session_state.quiz_ratio = ratio
                st.session_state.quiz_checked = True

                pct = int(ratio * 100)
                if ratio >= 0.8:
                    st.success(f"✅ Your answer is {pct}% similar to the official definition → Correct!")
                elif ratio >= 0.4:
                    st.info(f"➗ Your answer is {pct}% similar → Partially correct.")
                else:
                    st.error(f"❌ Your answer is only {pct}% similar → Incorrect or incomplete.")

        # (3) After checking, show definition and classification buttons
        if st.session_state.quiz_checked:
            st.markdown("---")
            st.markdown(f"**Correct definition:**  \n\n{term_obj['definition']}")
            if term_obj.get("image_url"):
                try:
                    st.image(term_obj["image_url"], caption="Illustration", use_column_width=True)
                except:
                    st.warning("⚠️ Could not load image.")
            if term_obj.get("example_link"):
                st.markdown(f"[🔗 View Example]({term_obj['example_link']})")

            # Audio pronunciation
            audio_path = ensure_audio(term_obj["term"]) if TTS_AVAILABLE else None
            if audio_path:
                try:
                    audio_bytes = open(audio_path, "rb").read()
                    st.audio(audio_bytes, format="audio/mp3")
                except:
                    pass

            # Related terms
            if term_obj.get("related_terms"):
                rel = term_obj["related_terms"]
                if rel:
                    st.markdown("**Related Terms:** " + ", ".join(f"• {r}" for r in rel))

            # Classification buttons (Fully / Partial / Incorrect)
            st.markdown("---")
            st.markdown("**How would you classify your answer?**")
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("✅ Fully Correct", key=f"correct_{term_obj['term']}"):
                    st.session_state.quiz_correct_count += 1
                    schedule_next(term_obj["term"], 5)
                    # clear current term so classification UI goes away
                    st.session_state.quiz_current_term = None
            with col2:
                if st.button("➗ Partially Correct", key=f"partial_{term_obj['term']}"):
                    schedule_next(term_obj["term"], 3)
                    st.session_state.quiz_current_term = None
            with col3:
                if st.button("❌ Incorrect", key=f"wrong_{term_obj['term']}"):
                    schedule_next(term_obj["term"], 0)
                    st.session_state.quiz_current_term = None

            # ─── NEW: Next Button After Classification ────────────────────────────────
            st.markdown("---")
            if st.button("🔀 Next Random Term", key="next_after_classification"):
                if filtered_terms:
                    st.session_state.quiz_current_term = random.choice(filtered_terms)
                    st.session_state.quiz_total_asked += 1
                    st.session_state.quiz_checked = False
                    st.session_state.quiz_ratio = 0.0
                else:
                    st.warning("No terms available under these filters.")
            # ────────────────────────────────────────────────────────────────────────────

    # (4) Quiz Score Display
    st.markdown("---")
    score = st.session_state.get("quiz_correct_count", 0)
    asked = st.session_state.get("quiz_total_asked", 0)
    percentage = (score / asked * 100) if asked > 0 else 0
    st.metric(label="Score (Correct / Asked)", value=f"{score}/{asked}", delta=f"{percentage:.1f}%")


st.markdown("---")
st.caption("🔑 Your progress (known terms & next review dates) is saved locally. Keep practicing! 🚀")
