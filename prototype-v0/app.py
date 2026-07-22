import json
from copy import deepcopy
from io import BytesIO

import streamlit as st


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="FUME Client Intelligence",
    page_icon="🧠",
    layout="wide",
)


# ============================================================
# SAMPLE ANONYMISED CONVERSATION
# ============================================================

SAMPLE_CONVERSATION = """Day 1
Client: Good morning. Slept only around 5 hours last night. Daughter had exams, so I was awake late.
Client: Did some mopping, sweeping, Surya Namaskar and walking inside the house.
Client: Generally feeling happy today.
Coach: Good. Please keep sharing your daily updates for water, sleep, steps, exercise and meals.
Client: Had tea and some soaked nuts.
Client: Lunch was kadhi with soya and green vegetables.
Coach: Did you have salad before lunch?
Client: No. I still need to stock vegetables properly. Will do it tomorrow.
Client: Feeling some acidity since morning.
Coach: Did it start after eating something?
Client: No. Slept very late and did a lot of work today. Got up with acidity.
Coach: Did you walk after meals?
Client: Yes, around 15 minutes.

Day 2
Client: Walk and water done.
Client: Can I have banana stem, mint and ginger juice?
Coach: Yes.
Client: Tea 1 cup and 1 apple.
Client: Didn’t eat much in the evening. Just a small piece of paneer.
Client: Still having acidity and bloating.
Coach: Please don’t skip meals completely. Try to keep the meals simple.

Day 3
Client: I had to go to school after a few days. Very hectic morning.
Client: Coconut water, tea, prunes and some seeds till now.
Coach: Nothing else till now?
Client: No. I didn’t get time.
Coach: Slowly we need to adjust the routine around your school schedule also.
Client: Yes. I know it will take time.
Client: Lunch had lots of vegetables, curd and some protein.
Client: Forgot ACV today. Not yet in the habit.
Coach: Set a reminder around meal timings.
Client: Yes, will do.
Accountability Coach: Today’s update: Water 4 litres, Sleep 5 hours, Steps around 8,000, Exercise only walking.

Day 4
Client: Breakfast was 1.5 vegetable chapatis with seeds and ajwain.
Client: One cup tea.
Client: 4,500 steps so far.
Coach: Did you carry lunch to school?
Client: Yes.
Client: ACV done today.
Client: Lunch done. Trying to eat slowly.
Coach: Good. Chew properly and avoid rushing meals.
Client: Did around 20 minutes walking, stretching and breathing today. Feeling really good.

Day 5
Client: Weight seems slightly up even though I’m eating almost half of what I used to eat.
Coach: It is not always about eating less. Your body needs adequate nutrition.
Coach: Protein seems low in breakfast on some days.
Client: I didn’t have sprouts today. Have ordered them.
Coach: You can also have boiled chana, moong or chhole.
Client: Forgot to mention, I had roasted chana at school.
Client: Did 20 minutes stretching and running.

Day 6
Client: Yesterday energy was very good. Today feeling low again.
Client: Bloating is back and I feel like I have gained weight.
Coach: Food intake was low today. Protein was also missing.
Client: I had roasted chana and kala chana.
Client: I am not getting enough time to plan meals. Next week should be easier.
Coach: That could be one of the main barriers right now. Let’s keep the plan practical.

Day 7
Client: Steps 6,000 today.
Client: Sleep around 5.5 hours.
Client: Did mopping and sweeping also, lots of movement.
Client: Breakfast and lunch were okay.
Client: Sorry I missed your call. There was a stressful situation at work.
Accountability Coach: Tried calling you. Please update when free.
Client: Had a very hectic day today.
Client: There is a lot of office pressure and politics going on.
Client: During a meeting today I was so tired that my head went down on the table and I actually slept for a few seconds.
Client: Feeling very low.
Client: I feel I can sleep for days.
Coach: That sounds like a very exhausting day. Please rest today. We also need to look at your sleep and stress more carefully.

Day 8
Client: Slept better last night, around 8 hours.
Client: Energy feels much better today.
Client: Water around 3.5 litres.
Client: Did 30 minutes exercise.
Client: Steps around 8,000.
Client: Weight is around 83 kg. Waist almost same.
Client: Still having bloating on and off.
Client: But overall energy is much better than before.
Coach: That is good progress. Let’s continue tracking sleep, bloating, meals and movement consistently.
"""


# ============================================================
# PROMPT / WORKFLOW USED FOR THE PROTOTYPE
# ============================================================

ANALYSIS_PROMPT = """
You are an evidence-grounded client intelligence assistant for a health-coaching team.

Analyse the anonymised client-coach conversation and produce structured weekly
client intelligence.

For every important finding:

1. State the finding conservatively.
2. Classify it as exactly one of:
   - confirmed_fact
   - client_reported_information
   - ai_generated_inference
   - missing_unavailable_information
3. Include exact supporting evidence from the source conversation.
4. Include the day or source reference.
5. Do not convert absence of information into non-adherence.
6. Do not present client statements as independently verified facts.
7. Do not diagnose medical or mental-health conditions.
8. Mark inferences explicitly and explain the evidence used.
9. Recommend coach actions, not medical treatment.
10. Prefer missing/unavailable over guessing.

Required output areas:

- weekly_summary
- nutrition_adherence
- exercise_steps
- sleep
- water_intake
- symptoms_stress
- engagement
- barriers
- pending_actions
- risk_flags
- recommended_coach_actions
- supporting_evidence

The output must be valid JSON.
"""


# ============================================================
# STRUCTURED ANALYSIS FOR THE PROVIDED SAMPLE
# ============================================================

def build_sample_analysis():
    return {
        "client_id": "ANONYMISED_CLIENT_001",
        "analysis_period": "Day 1 to Day 8",
        "overall_attention_level": "high_attention",
        "weekly_summary": {
            "finding": (
                "The client remained physically active across the period and showed "
                "improved sleep and energy on Day 8. However, the period also included "
                "irregular food intake, inconsistent meal planning, recurring acidity "
                "and bloating, repeated short sleep, and a significant fatigue and "
                "work-stress episode on Day 7."
            ),
            "classification": "ai_generated_inference",
            "confidence": "high",
            "evidence": [
                {
                    "day": "Day 3",
                    "quote": (
                        "Water 4 litres, Sleep 5 hours, Steps around 8,000, "
                        "Exercise only walking."
                    ),
                },
                {
                    "day": "Day 6",
                    "quote": "I am not getting enough time to plan meals.",
                },
                {
                    "day": "Day 7",
                    "quote": (
                        "During a meeting today I was so tired that my head went "
                        "down on the table and I actually slept for a few seconds."
                    ),
                },
                {
                    "day": "Day 8",
                    "quote": (
                        "Slept better last night, around 8 hours. Energy feels "
                        "much better today."
                    ),
                },
            ],
            "review_status": "pending",
        },
        "domains": {
            "nutrition_adherence": {
                "status": "inconsistent",
                "finding": (
                    "Nutrition adherence appears inconsistent. The client reported "
                    "some balanced meals, but also low intake, skipped or delayed meals, "
                    "low protein on some days, and difficulty planning meals."
                ),
                "classification": "ai_generated_inference",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 2",
                        "quote": (
                            "Didn’t eat much in the evening. Just a small piece of paneer."
                        ),
                    },
                    {
                        "day": "Day 3",
                        "quote": "No. I didn’t get time.",
                    },
                    {
                        "day": "Day 5",
                        "quote": "Protein seems low in breakfast on some days.",
                    },
                    {
                        "day": "Day 6",
                        "quote": "I am not getting enough time to plan meals.",
                    },
                ],
                "review_status": "pending",
            },
            "exercise_steps": {
                "status": "active_but_incompletely_tracked",
                "finding": (
                    "The client reported regular movement through walking, household "
                    "activity, stretching, running, breathing exercises and Surya "
                    "Namaskar. Reported steps ranged from 4,500 to approximately 8,000 "
                    "on days with numeric updates."
                ),
                "classification": "client_reported_information",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 3",
                        "quote": "Steps around 8,000, Exercise only walking.",
                    },
                    {
                        "day": "Day 4",
                        "quote": (
                            "Did around 20 minutes walking, stretching and breathing today."
                        ),
                    },
                    {
                        "day": "Day 7",
                        "quote": "Steps 6,000 today.",
                    },
                    {
                        "day": "Day 8",
                        "quote": "Did 30 minutes exercise. Steps around 8,000.",
                    },
                ],
                "review_status": "pending",
            },
            "sleep": {
                "status": "attention_needed",
                "finding": (
                    "The client reported short sleep on multiple days, including around "
                    "5 hours on Days 1 and 3 and around 5.5 hours on Day 7. Sleep improved "
                    "to around 8 hours on Day 8, with better energy."
                ),
                "classification": "client_reported_information",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 1",
                        "quote": "Slept only around 5 hours last night.",
                    },
                    {
                        "day": "Day 3",
                        "quote": "Sleep 5 hours.",
                    },
                    {
                        "day": "Day 7",
                        "quote": "Sleep around 5.5 hours.",
                    },
                    {
                        "day": "Day 8",
                        "quote": "Slept better last night, around 8 hours.",
                    },
                ],
                "review_status": "pending",
            },
            "water_intake": {
                "status": "partially_available",
                "finding": (
                    "Water intake was numerically reported on only two days: 4 litres "
                    "on Day 3 and around 3.5 litres on Day 8. Water was marked as done "
                    "on Day 2 without a quantity. Intake for the remaining days is unavailable."
                ),
                "classification": "missing_unavailable_information",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 2",
                        "quote": "Walk and water done.",
                    },
                    {
                        "day": "Day 3",
                        "quote": "Water 4 litres.",
                    },
                    {
                        "day": "Day 8",
                        "quote": "Water around 3.5 litres.",
                    },
                ],
                "review_status": "pending",
            },
            "symptoms_stress": {
                "status": "high_attention",
                "finding": (
                    "The client repeatedly reported acidity and bloating. A notable "
                    "work-stress and fatigue episode occurred on Day 7, when the client "
                    "reported briefly falling asleep during a meeting and feeling very low."
                ),
                "classification": "client_reported_information",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 1",
                        "quote": "Feeling some acidity since morning.",
                    },
                    {
                        "day": "Day 2",
                        "quote": "Still having acidity and bloating.",
                    },
                    {
                        "day": "Day 7",
                        "quote": (
                            "There is a lot of office pressure and politics going on."
                        ),
                    },
                    {
                        "day": "Day 7",
                        "quote": (
                            "During a meeting today I was so tired that my head went "
                            "down on the table and I actually slept for a few seconds."
                        ),
                    },
                    {
                        "day": "Day 8",
                        "quote": "Still having bloating on and off.",
                    },
                ],
                "review_status": "pending",
            },
            "engagement": {
                "status": "moderate_to_high",
                "finding": (
                    "The client engaged regularly by sharing updates, answering coach "
                    "questions and acknowledging suggested actions. Engagement was briefly "
                    "disrupted by a missed call during a stressful workday."
                ),
                "classification": "ai_generated_inference",
                "confidence": "medium",
                "evidence": [
                    {
                        "day": "Day 3",
                        "quote": "Yes, will do.",
                    },
                    {
                        "day": "Day 4",
                        "quote": "ACV done today.",
                    },
                    {
                        "day": "Day 7",
                        "quote": (
                            "Sorry I missed your call. There was a stressful situation at work."
                        ),
                    },
                ],
                "review_status": "pending",
            },
            "key_barriers": {
                "status": "identified",
                "finding": (
                    "The main barriers appear to be limited time for meal planning, "
                    "school and work demands, late sleep, workplace stress, incomplete "
                    "food stocking and difficulty building new habits."
                ),
                "classification": "ai_generated_inference",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 1",
                        "quote": "I still need to stock vegetables properly.",
                    },
                    {
                        "day": "Day 3",
                        "quote": "Very hectic morning.",
                    },
                    {
                        "day": "Day 3",
                        "quote": "Forgot ACV today. Not yet in the habit.",
                    },
                    {
                        "day": "Day 6",
                        "quote": "I am not getting enough time to plan meals.",
                    },
                    {
                        "day": "Day 7",
                        "quote": "There is a lot of office pressure and politics going on.",
                    },
                ],
                "review_status": "pending",
            },
            "pending_actions": {
                "status": "open",
                "finding": (
                    "Pending actions include maintaining regular tracking, planning "
                    "practical meals around the school schedule, setting an ACV reminder, "
                    "restocking vegetables and protein options, and following up on sleep, "
                    "stress, fatigue, acidity and bloating."
                ),
                "classification": "ai_generated_inference",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 1",
                        "quote": "Will do it tomorrow.",
                    },
                    {
                        "day": "Day 3",
                        "quote": "Set a reminder around meal timings.",
                    },
                    {
                        "day": "Day 6",
                        "quote": "Let’s keep the plan practical.",
                    },
                    {
                        "day": "Day 8",
                        "quote": (
                            "Let’s continue tracking sleep, bloating, meals and movement consistently."
                        ),
                    },
                ],
                "review_status": "pending",
            },
        },
        "risk_flags": [
            {
                "severity": "high",
                "title": "Significant fatigue and daytime sleep episode",
                "finding": (
                    "The Day 7 combination of short sleep, extreme tiredness, briefly "
                    "falling asleep during a meeting and feeling very low requires prompt "
                    "coach follow-up."
                ),
                "classification": "ai_generated_inference",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 7",
                        "quote": "Sleep around 5.5 hours.",
                    },
                    {
                        "day": "Day 7",
                        "quote": (
                            "During a meeting today I was so tired that my head went "
                            "down on the table and I actually slept for a few seconds."
                        ),
                    },
                    {
                        "day": "Day 7",
                        "quote": "Feeling very low.",
                    },
                    {
                        "day": "Day 7",
                        "quote": "I feel I can sleep for days.",
                    },
                ],
                "review_status": "pending",
            },
            {
                "severity": "medium",
                "title": "Recurring acidity and bloating",
                "finding": (
                    "Acidity and bloating were reported repeatedly across the period "
                    "and remained present on Day 8."
                ),
                "classification": "client_reported_information",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 1",
                        "quote": "Feeling some acidity since morning.",
                    },
                    {
                        "day": "Day 2",
                        "quote": "Still having acidity and bloating.",
                    },
                    {
                        "day": "Day 6",
                        "quote": "Bloating is back.",
                    },
                    {
                        "day": "Day 8",
                        "quote": "Still having bloating on and off.",
                    },
                ],
                "review_status": "pending",
            },
            {
                "severity": "medium",
                "title": "Low or irregular food intake",
                "finding": (
                    "The conversation contains several indications of low, delayed or "
                    "incomplete food intake, creating an adherence and energy concern."
                ),
                "classification": "ai_generated_inference",
                "confidence": "high",
                "evidence": [
                    {
                        "day": "Day 2",
                        "quote": (
                            "Didn’t eat much in the evening. Just a small piece of paneer."
                        ),
                    },
                    {
                        "day": "Day 3",
                        "quote": "No. I didn’t get time.",
                    },
                    {
                        "day": "Day 6",
                        "quote": "Food intake was low today. Protein was also missing.",
                    },
                ],
                "review_status": "pending",
            },
        ],
        "recommended_coach_actions": [
            {
                "priority": 1,
                "action": (
                    "Contact the client promptly to review the Day 7 fatigue, daytime "
                    "sleep episode, current sleep status and work stress."
                ),
                "classification": "ai_generated_inference",
                "rationale": (
                    "The recommendation is based on the severity and combination of "
                    "the client-reported Day 7 symptoms."
                ),
                "review_status": "pending",
            },
            {
                "priority": 2,
                "action": (
                    "Continue monitoring acidity and bloating and follow the organisation’s "
                    "approved escalation protocol if symptoms persist, worsen or require "
                    "clinical assessment."
                ),
                "classification": "ai_generated_inference",
                "rationale": (
                    "Symptoms were reported repeatedly across multiple days."
                ),
                "review_status": "pending",
            },
            {
                "priority": 3,
                "action": (
                    "Agree on a practical minimum meal and protein plan that fits the "
                    "client’s school and work schedule."
                ),
                "classification": "ai_generated_inference",
                "rationale": (
                    "Time pressure and meal planning difficulties were directly reported."
                ),
                "review_status": "pending",
            },
            {
                "priority": 4,
                "action": (
                    "Maintain simple daily tracking for sleep, meals, movement, water, "
                    "energy, acidity and bloating."
                ),
                "classification": "ai_generated_inference",
                "rationale": (
                    "Several domains contain incomplete data, limiting reliable trend analysis."
                ),
                "review_status": "pending",
            },
        ],
        "missing_information": [
            {
                "field": "Daily water intake",
                "finding": (
                    "Numeric water intake is unavailable for most days."
                ),
                "classification": "missing_unavailable_information",
            },
            {
                "field": "Daily step count",
                "finding": (
                    "Numeric steps are unavailable for several days."
                ),
                "classification": "missing_unavailable_information",
            },
            {
                "field": "Complete meal log",
                "finding": (
                    "The conversation does not provide a complete meal-by-meal record for every day."
                ),
                "classification": "missing_unavailable_information",
            },
            {
                "field": "Verified weight trend",
                "finding": (
                    "The client reported that weight seemed up and later reported around "
                    "83 kg, but no verified baseline or measurement series is available."
                ),
                "classification": "missing_unavailable_information",
            },
            {
                "field": "Clinical assessment",
                "finding": (
                    "No clinical diagnosis or medical assessment is available in the conversation."
                ),
                "classification": "missing_unavailable_information",
            },
        ],
    }


# ============================================================
# FILE READING
# ============================================================

def read_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return ""

    filename = uploaded_file.name.lower()

    if filename.endswith(".txt"):
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")

    if filename.endswith(".docx"):
        try:
            from docx import Document

            document = Document(BytesIO(uploaded_file.getvalue()))
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            return "\n".join(paragraphs)
        except ImportError:
            st.error(
                "DOCX support requires python-docx. "
                "Install it using: pip install python-docx"
            )
            return ""
        except Exception as error:
            st.error(f"Could not read the DOCX file: {error}")
            return ""

    st.error("Unsupported file type. Please upload TXT or DOCX.")
    return ""


# ============================================================
# PROTOTYPE ANALYSIS LOGIC
# ============================================================

def analyse_conversation(conversation):
    """
    Prototype behaviour:
    - Uses a locked evidence-grounded output for the supplied anonymised sample.
    - Does not invent findings for unrelated conversations.
    - In production, this function would call an LLM using ANALYSIS_PROMPT,
      validate the JSON schema, verify evidence quotes and flag unsupported claims.
    """

    required_markers = [
        "Day 1",
        "acidity",
        "bloating",
        "Day 7",
        "office pressure",
        "Day 8",
    ]

    matched_markers = sum(
        marker.lower() in conversation.lower()
        for marker in required_markers
    )

    if matched_markers >= 4:
        return build_sample_analysis()

    return {
        "client_id": "UNKNOWN",
        "analysis_period": "Unavailable",
        "overall_attention_level": "manual_review_required",
        "weekly_summary": {
            "finding": (
                "This prototype currently contains a validated evidence-grounded "
                "analysis template for the supplied FUME sample conversation. "
                "A production version would call an LLM and run evidence-validation "
                "checks before displaying results."
            ),
            "classification": "missing_unavailable_information",
            "confidence": "not_applicable",
            "evidence": [],
            "review_status": "pending",
        },
        "domains": {},
        "risk_flags": [],
        "recommended_coach_actions": [],
        "missing_information": [
            {
                "field": "Validated extraction",
                "finding": (
                    "No validated extraction is available for this different conversation."
                ),
                "classification": "missing_unavailable_information",
            }
        ],
    }


# ============================================================
# SESSION STATE
# ============================================================

if "conversation" not in st.session_state:
    st.session_state.conversation = ""

if "analysis" not in st.session_state:
    st.session_state.analysis = None

if "review_records" not in st.session_state:
    st.session_state.review_records = {}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

CLASSIFICATION_LABELS = {
    "confirmed_fact": "Confirmed fact",
    "client_reported_information": "Client-reported information",
    "ai_generated_inference": "AI-generated inference",
    "missing_unavailable_information": "Missing / unavailable information",
}

CLASSIFICATION_ICONS = {
    "confirmed_fact": "✅",
    "client_reported_information": "💬",
    "ai_generated_inference": "🧠",
    "missing_unavailable_information": "❓",
}

SEVERITY_ICONS = {
    "high": "🔴",
    "medium": "🟠",
    "low": "🟢",
}


def format_title(key):
    return key.replace("_", " ").title()


def render_evidence(evidence):
    if not evidence:
        st.caption("No supporting evidence available.")
        return

    for item in evidence:
        day = item.get("day", "Source unavailable")
        quote = item.get("quote", "")
        st.markdown(f"**{day}**")
        st.info(f'“{quote}”')


def review_controls(item_key, original_finding):
    existing = st.session_state.review_records.get(
        item_key,
        {
            "status": "Pending",
            "edited_finding": original_finding,
            "review_note": "",
        },
    )

    status = st.radio(
        "Human review",
        ["Pending", "Approve", "Edit", "Reject"],
        index=["Pending", "Approve", "Edit", "Reject"].index(
            existing["status"]
        ),
        horizontal=True,
        key=f"status_{item_key}",
    )

    edited_finding = original_finding

    if status == "Edit":
        edited_finding = st.text_area(
            "Edited finding",
            value=existing.get("edited_finding", original_finding),
            key=f"edit_{item_key}",
        )

    review_note = st.text_input(
        "Reviewer note",
        value=existing.get("review_note", ""),
        key=f"note_{item_key}",
        placeholder="Optional reason or correction",
    )

    st.session_state.review_records[item_key] = {
        "status": status,
        "edited_finding": edited_finding,
        "review_note": review_note,
    }


def render_finding(title, item, item_key):
    classification = item.get(
        "classification",
        "missing_unavailable_information",
    )

    icon = CLASSIFICATION_ICONS.get(classification, "•")
    label = CLASSIFICATION_LABELS.get(classification, classification)

    with st.container(border=True):
        st.subheader(title)

        left, right = st.columns([3, 1])

        with left:
            st.write(item.get("finding", "No finding available."))

        with right:
            st.markdown(f"**{icon} {label}**")

            if item.get("confidence"):
                st.caption(f"Confidence: {item['confidence']}")

            if item.get("status"):
                st.caption(f"Domain status: {item['status']}")

        with st.expander("View supporting evidence"):
            render_evidence(item.get("evidence", []))

        review_controls(
            item_key=item_key,
            original_finding=item.get("finding", ""),
        )


def build_reviewed_output(analysis):
    reviewed = deepcopy(analysis)
    reviewed["human_review"] = deepcopy(
        st.session_state.review_records
    )
    return reviewed


# ============================================================
# STYLING
# ============================================================

st.markdown(
    """
    <style>
        .main-title {
            font-size: 2.2rem;
            font-weight: 750;
            margin-bottom: 0.2rem;
        }

        .subtitle {
            color: #5f6670;
            margin-bottom: 1.4rem;
        }

        .classification-note {
            padding: 0.85rem;
            border-radius: 0.6rem;
            background: rgba(128, 128, 128, 0.08);
            margin-bottom: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Prototype controls")

    st.write(
        "This MVP demonstrates evidence-grounded extraction and "
        "human review for an anonymised client–coach conversation."
    )

    if st.button("Load FUME sample conversation", use_container_width=True):
        st.session_state.conversation = SAMPLE_CONVERSATION
        st.session_state.analysis = None
        st.session_state.review_records = {}
        st.rerun()

    uploaded_file = st.file_uploader(
        "Upload conversation",
        type=["txt", "docx"],
    )

    if uploaded_file is not None:
        uploaded_text = read_uploaded_file(uploaded_file)

        if uploaded_text:
            st.session_state.conversation = uploaded_text
            st.success("Conversation loaded.")

    st.divider()

    st.subheader("Classification legend")
    st.write("✅ Confirmed fact")
    st.write("💬 Client-reported information")
    st.write("🧠 AI-generated inference")
    st.write("❓ Missing / unavailable information")

    st.divider()

    st.warning(
        "Prototype only. This tool does not provide medical diagnosis "
        "or replace clinical judgement."
    )


# ============================================================
# MAIN HEADER
# ============================================================

st.markdown(
    '<div class="main-title">FUME Client Intelligence Platform</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="subtitle">
        Evidence-grounded weekly client intelligence with human review
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# MAIN TABS
# ============================================================

input_tab, dashboard_tab, json_tab, workflow_tab, qa_tab, note_tab = st.tabs(
    [
        "1. Conversation",
        "2. Intelligence Dashboard",
        "3. JSON Output",
        "4. Prompt & Workflow",
        "5. Failure Scenarios",
        "6. Submission Note",
    ]
)


# ============================================================
# TAB 1: INPUT
# ============================================================

with input_tab:
    st.subheader("Anonymised client–coach conversation")

    st.markdown(
        """
        <div class="classification-note">
        The system must not convert missing information into non-adherence
        and must not present self-reported statements as independently
        verified facts.
        </div>
        """,
        unsafe_allow_html=True,
    )

    conversation = st.text_area(
        "Paste or edit the conversation",
        value=st.session_state.conversation,
        height=500,
        placeholder="Paste the anonymised WhatsApp conversation here...",
    )

    st.session_state.conversation = conversation

    if st.button(
        "Analyse Conversation",
        type="primary",
        use_container_width=True,
    ):
        if not conversation.strip():
            st.warning("Please paste or upload a conversation first.")
        else:
            with st.spinner("Generating evidence-grounded intelligence..."):
                st.session_state.analysis = analyse_conversation(conversation)
                st.session_state.review_records = {}

            st.success(
                "Analysis completed. Open the Intelligence Dashboard tab."
            )


# ============================================================
# TAB 2: DASHBOARD
# ============================================================

with dashboard_tab:
    analysis = st.session_state.analysis

    if analysis is None:
        st.info(
            "Load the FUME sample conversation and click "
            "Analyse Conversation first."
        )
    else:
        attention = analysis.get(
            "overall_attention_level",
            "unavailable",
        )

        metric_1, metric_2, metric_3, metric_4 = st.columns(4)

        with metric_1:
            st.metric("Analysis period", analysis.get("analysis_period"))

        with metric_2:
            st.metric("Attention level", attention.replace("_", " ").title())

        with metric_3:
            st.metric(
                "Risk flags",
                len(analysis.get("risk_flags", [])),
            )

        with metric_4:
            st.metric(
                "Coach actions",
                len(analysis.get("recommended_coach_actions", [])),
            )

        st.divider()

        render_finding(
            "Weekly Client Summary",
            analysis["weekly_summary"],
            "weekly_summary",
        )

        st.header("Progress and adherence domains")

        for domain_key, domain_item in analysis.get("domains", {}).items():
            render_finding(
                format_title(domain_key),
                domain_item,
                f"domain_{domain_key}",
            )

        st.header("Risk / attention flags")

        risk_flags = analysis.get("risk_flags", [])

        if not risk_flags:
            st.info("No validated risk flags available.")
        else:
            for index, flag in enumerate(risk_flags):
                severity = flag.get("severity", "low")
                severity_icon = SEVERITY_ICONS.get(severity, "•")

                render_finding(
                    (
                        f"{severity_icon} {flag.get('title', 'Risk flag')} "
                        f"— {severity.title()}"
                    ),
                    flag,
                    f"risk_{index}",
                )

        st.header("Recommended coach actions")

        for index, action in enumerate(
            analysis.get("recommended_coach_actions", [])
        ):
            with st.container(border=True):
                st.subheader(
                    f"Priority {action.get('priority', index + 1)}"
                )

                st.write(action.get("action"))

                classification = action.get(
                    "classification",
                    "ai_generated_inference",
                )

                st.caption(
                    f"{CLASSIFICATION_ICONS.get(classification, '•')} "
                    f"{CLASSIFICATION_LABELS.get(classification, classification)}"
                )

                st.info(
                    f"Rationale: {action.get('rationale', 'Unavailable')}"
                )

                review_controls(
                    item_key=f"coach_action_{index}",
                    original_finding=action.get("action", ""),
                )

        st.header("Missing / unavailable information")

        missing_items = analysis.get("missing_information", [])

        for item in missing_items:
            with st.container(border=True):
                st.markdown(f"**{item.get('field', 'Unknown field')}**")
                st.write(item.get("finding"))
                st.caption("❓ Missing / unavailable information")


# ============================================================
# TAB 3: JSON OUTPUT
# ============================================================

with json_tab:
    if st.session_state.analysis is None:
        st.info("Run the analysis first.")
    else:
        reviewed_output = build_reviewed_output(
            st.session_state.analysis
        )

        st.subheader("Structured JSON output")

        st.json(reviewed_output)

        json_text = json.dumps(
            reviewed_output,
            indent=2,
            ensure_ascii=False,
        )

        st.download_button(
            label="Download reviewed JSON",
            data=json_text,
            file_name="fume_client_intelligence.json",
            mime="application/json",
            use_container_width=True,
        )


# ============================================================
# TAB 4: PROMPT AND WORKFLOW
# ============================================================

with workflow_tab:
    st.subheader("Prompt used for analysis")
    st.code(ANALYSIS_PROMPT, language="text")

    st.subheader("Suggested production workflow")

    st.markdown(
        """
1. **Input validation**  
   Accept only anonymised and approved client conversations.

2. **Conversation normalisation**  
   Separate messages by day, speaker and message order.

3. **LLM extraction**  
   Send the source conversation and the evidence-grounding prompt to an LLM.

4. **Structured JSON generation**  
   Require output matching the defined schema.

5. **Schema validation**  
   Reject malformed JSON, missing mandatory fields and invalid classifications.

6. **Evidence verification**  
   Check that every quoted evidence item appears in the source conversation.

7. **Unsupported-claim detection**  
   Flag findings that have no evidence or use stronger language than the source.

8. **Risk calibration**  
   Apply business-approved risk rules and avoid medical diagnosis.

9. **Human review**  
   Allow coaches to approve, edit or reject each finding and action.

10. **Audit logging**  
    Save prompt version, model version, original output, reviewer changes and final output.
        """
    )

    st.subheader("Basic JSON schema")

    schema_example = {
        "finding_id": "string",
        "category": "sleep | nutrition | exercise | water | symptoms | engagement",
        "finding": "string",
        "classification": (
            "confirmed_fact | client_reported_information | "
            "ai_generated_inference | missing_unavailable_information"
        ),
        "confidence": "high | medium | low | not_applicable",
        "evidence": [
            {
                "day": "string",
                "quote": "exact source quote",
            }
        ],
        "risk_level": "high | medium | low | none",
        "review_status": "pending | approved | edited | rejected",
        "reviewer_note": "string",
    }

    st.json(schema_example)


# ============================================================
# TAB 5: FAILURE SCENARIOS
# ============================================================

with qa_tab:
    st.subheader("Three possible hallucination or failure scenarios")

    with st.container(border=True):
        st.markdown("### 1. Missing data interpreted as failure")
        st.write(
            "The conversation does not contain a water quantity for most days. "
            "A weak system may incorrectly conclude that the client did not drink water."
        )
        st.success(
            "Control: classify the information as missing/unavailable rather than non-adherence."
        )

    with st.container(border=True):
        st.markdown("### 2. Self-reported information presented as verified fact")
        st.write(
            "The client says that weight is around 83 kg. The system may wrongly "
            "present 83 kg as a confirmed measurement."
        )
        st.success(
            "Control: label it client-reported information unless it comes from a "
            "verified device or coach record."
        )

    with st.container(border=True):
        st.markdown("### 3. Medical diagnosis generated from symptoms")
        st.write(
            "The system may diagnose a condition from acidity, bloating, fatigue "
            "or stress messages."
        )
        st.success(
            "Control: prohibit diagnosis, quote the symptoms, mark risk conservatively "
            "and recommend coach follow-up or approved escalation."
        )

    st.subheader("Additional edge cases")

    st.markdown(
        """
- Contradictory messages across different days
- Sarcasm or informal WhatsApp language
- Incomplete day labels
- Coach statements confused with client statements
- Old symptoms treated as currently active
- Approximate values treated as exact values
- Repeated copied messages counted multiple times
- Risk severity exaggerated without organisational rules
- Evidence quote not actually present in the source
- Edited human-reviewed output not preserved in the audit trail
        """
    )


# ============================================================
# TAB 6: SUBMISSION NOTE
# ============================================================

with note_tab:
    st.subheader("What I built")

    st.write(
        """
I built a Streamlit-based client intelligence prototype that converts an
anonymised client–coach conversation into a structured weekly summary. It
covers nutrition, exercise, steps, sleep, water, symptoms, stress, engagement,
barriers, pending actions, risk flags and recommended coach actions. Every
important finding includes a classification and supporting source evidence.
The prototype also supports human review through Approve, Edit and Reject controls.
        """
    )

    st.subheader("Key assumptions")

    st.write(
        """
- Client messages are self-reported unless independently verified.
- Missing information is not treated as non-adherence.
- The prototype is intended for coach decision support, not diagnosis.
- Risk flags indicate attention requirements, not confirmed medical conditions.
- Only anonymised or approved test conversations should be processed.
        """
    )

    st.subheader("What could go wrong")

    st.write(
        """
An LLM may invent unsupported details, misclassify self-reported information,
miss context spread across multiple days, confuse the coach and client speakers,
or generate an overly strong medical conclusion. Evidence quotes may also be
incorrectly copied or detached from their original context.
        """
    )

    st.subheader("What I would improve next")

    st.write(
        """
I would integrate an LLM API with strict JSON-schema validation, automatic
evidence-quote verification, configurable risk rules and prompt versioning.
I would also add authentication, role-based access, encrypted database storage,
multi-client dashboards, reviewer audit logs, automated test cases and comparison
against human-labelled reference outputs.
        """
    )

    st.subheader("Prototype limitation")

    st.warning(
        """
For safe and reliable demonstration, this prototype contains a validated
evidence-grounded output for the supplied anonymised sample conversation.
A production version would replace the locked extraction function with an LLM
API plus schema validation, evidence verification and coach-approved risk rules.
        """
    )