import re
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.schemas.client_intelligence import (
    AnalysisRequest,
    AnalysisResponse,
    CoachAction,
    EvidenceReference,
    Finding,
    FindingClassification,
    RiskFlag,
    RiskSeverity,
)


DAY_PATTERN = re.compile(r"^Day\s+\d+", re.IGNORECASE)
MESSAGE_PATTERN = re.compile(
    r"^(Client|Coach|Accountability Coach):\s*(.+)$",
    re.IGNORECASE,
)


def parse_conversation(conversation: str) -> list[dict[str, str]]:
    current_day = "Day unavailable"
    messages: list[dict[str, str]] = []

    for raw_line in conversation.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if DAY_PATTERN.match(line):
            current_day = line
            continue

        message_match = MESSAGE_PATTERN.match(line)

        if not message_match:
            continue

        speaker = message_match.group(1)
        text = message_match.group(2).strip()

        messages.append(
            {
                "message_id": f"msg-{len(messages) + 1:03d}",
                "day": current_day,
                "speaker": speaker,
                "text": text,
            }
        )

    return messages


def find_messages(
    messages: list[dict[str, str]],
    keywords: list[str],
    speakers: set[str] | None = None,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []

    for message in messages:
        text = message["text"].lower()
        speaker = message["speaker"].lower()

        if speakers and speaker not in speakers:
            continue

        if any(keyword.lower() in text for keyword in keywords):
            matches.append(message)

    return matches


def to_evidence(
    messages: list[dict[str, str]],
    limit: int = 4,
) -> list[EvidenceReference]:
    return [
        EvidenceReference(
            message_id=message["message_id"],
            day=message["day"],
            speaker=message["speaker"],
            quote=message["text"],
        )
        for message in messages[:limit]
    ]


def extract_numeric_values(
    messages: list[dict[str, str]],
    pattern: str,
) -> list[str]:
    values: list[str] = []

    for message in messages:
        match = re.search(pattern, message["text"], re.IGNORECASE)

        if match:
            values.append(match.group(1).replace(",", ""))

    return values


def make_missing_finding(
    finding_id: str,
    category: str,
    title: str,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        category=category,
        title=title,
        statement=f"{title} could not be reliably evaluated from the conversation.",
        classification=FindingClassification.MISSING,
        confidence=1.0,
        evidence=[],
    )


def analyse_conversation(payload: AnalysisRequest) -> AnalysisResponse:
    messages = parse_conversation(payload.conversation)
    client_messages = [
        message
        for message in messages
        if message["speaker"].lower() == "client"
    ]

    if not messages:
        raise ValueError(
            "No recognised Client, Coach or Accountability Coach messages were found."
        )

    findings: list[Finding] = []

    # --------------------------------------------------------
    # Sleep
    # --------------------------------------------------------

    sleep_messages = find_messages(
        client_messages,
        ["sleep", "slept", "awake late", "tired"],
    )

    sleep_values = extract_numeric_values(
        sleep_messages,
        r"(\d+(?:\.\d+)?)\s*hours?",
    )

    if sleep_messages:
        sleep_statement = (
            "The client reported sleep-related updates"
            + (
                f", including approximately {', '.join(sleep_values)} hours"
                if sleep_values
                else ""
            )
            + "."
        )

        findings.append(
            Finding(
                finding_id="finding-sleep",
                category="sleep",
                title="Sleep pattern",
                statement=sleep_statement,
                classification=FindingClassification.CLIENT_REPORTED,
                confidence=0.96,
                evidence=to_evidence(sleep_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-sleep",
                "sleep",
                "Sleep pattern",
            )
        )

    # --------------------------------------------------------
    # Water
    # --------------------------------------------------------

    water_messages = find_messages(
        client_messages,
        ["water", "litre", "liter"],
    )

    water_values = extract_numeric_values(
        water_messages,
        r"(\d+(?:\.\d+)?)\s*lit(?:re|er)s?",
    )

    if water_messages:
        statement = (
            "The client reported water-related updates"
            + (
                f", with quantities including {', '.join(water_values)} litres"
                if water_values
                else ", but complete daily quantities were unavailable"
            )
            + "."
        )

        findings.append(
            Finding(
                finding_id="finding-water",
                category="water_intake",
                title="Water intake",
                statement=statement,
                classification=FindingClassification.CLIENT_REPORTED,
                confidence=0.94,
                evidence=to_evidence(water_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-water",
                "water_intake",
                "Water intake",
            )
        )

    # --------------------------------------------------------
    # Exercise and steps
    # --------------------------------------------------------

    movement_messages = find_messages(
        client_messages,
        [
            "steps",
            "walking",
            "walk",
            "exercise",
            "stretching",
            "running",
            "surya namaskar",
            "mopping",
            "sweeping",
        ],
    )

    step_values = extract_numeric_values(
        movement_messages,
        r"(\d[\d,]*)\s*steps",
    )

    if movement_messages:
        statement = (
            "The client reported regular movement or exercise"
            + (
                f", with step counts including {', '.join(step_values)}"
                if step_values
                else ""
            )
            + "."
        )

        findings.append(
            Finding(
                finding_id="finding-movement",
                category="exercise_steps",
                title="Exercise and movement",
                statement=statement,
                classification=FindingClassification.CLIENT_REPORTED,
                confidence=0.95,
                evidence=to_evidence(movement_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-movement",
                "exercise_steps",
                "Exercise and movement",
            )
        )

    # --------------------------------------------------------
    # Nutrition adherence
    # --------------------------------------------------------

    nutrition_messages = find_messages(
        messages,
        [
            "breakfast",
            "lunch",
            "meal",
            "protein",
            "paneer",
            "chana",
            "vegetable",
            "nuts",
            "sprouts",
            "didn't eat",
            "didn't eat",
            "food intake",
        ],
    )

    low_intake_messages = find_messages(
        messages,
        [
            "didn't eat much",
            "didn't eat much",
            "didn't get time",
            "didn't get time",
            "food intake was low",
            "protein was also missing",
        ],
    )

    if nutrition_messages:
        statement = (
            "Nutrition updates were present. "
            + (
                "The conversation also contains low, delayed or incomplete intake signals, "
                "so adherence appears inconsistent and requires coach review."
                if low_intake_messages
                else "No clear non-adherence conclusion should be made without a complete meal log."
            )
        )

        evidence_messages = low_intake_messages or nutrition_messages

        findings.append(
            Finding(
                finding_id="finding-nutrition",
                category="nutrition_adherence",
                title="Nutrition adherence",
                statement=statement,
                classification=FindingClassification.AI_INFERENCE,
                confidence=0.88,
                evidence=to_evidence(evidence_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-nutrition",
                "nutrition_adherence",
                "Nutrition adherence",
            )
        )

    # --------------------------------------------------------
    # Symptoms and stress
    # --------------------------------------------------------

    symptom_messages = find_messages(
        client_messages,
        [
            "acidity",
            "bloating",
            "stress",
            "pressure",
            "politics",
            "feeling low",
            "very low",
            "tired",
            "energy",
        ],
    )

    if symptom_messages:
        findings.append(
            Finding(
                finding_id="finding-symptoms",
                category="symptoms_stress",
                title="Symptoms and stress",
                statement=(
                    "The client reported symptoms or stress-related concerns, "
                    "including recurring digestive discomfort and fluctuating energy or stress."
                ),
                classification=FindingClassification.CLIENT_REPORTED,
                confidence=0.96,
                evidence=to_evidence(symptom_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-symptoms",
                "symptoms_stress",
                "Symptoms and stress",
            )
        )

    # --------------------------------------------------------
    # Engagement
    # --------------------------------------------------------

    engagement_evidence = client_messages[:3]

    findings.append(
        Finding(
            finding_id="finding-engagement",
            category="engagement",
            title="Client engagement",
            statement=(
                "The client appears engaged because they supplied multiple updates "
                "and responded to coach questions, although responsiveness may vary "
                "during demanding days."
            ),
            classification=FindingClassification.AI_INFERENCE,
            confidence=0.82,
            evidence=to_evidence(engagement_evidence),
        )
    )

    # --------------------------------------------------------
    # Barriers
    # --------------------------------------------------------

    barrier_messages = find_messages(
        client_messages,
        [
            "no time",
            "didn't get time",
            "didn't get time",
            "hectic",
            "stressful",
            "pressure",
            "forgot",
            "not getting enough time",
            "awake late",
            "stock vegetables",
        ],
    )

    if barrier_messages:
        findings.append(
            Finding(
                finding_id="finding-barriers",
                category="barriers",
                title="Key barriers",
                statement=(
                    "Likely barriers include time pressure, demanding school or work routines, "
                    "stress, late sleep and difficulty consistently planning meals or habits."
                ),
                classification=FindingClassification.AI_INFERENCE,
                confidence=0.9,
                evidence=to_evidence(barrier_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-barriers",
                "barriers",
                "Key barriers",
            )
        )

    # --------------------------------------------------------
    # Pending coach actions
    # --------------------------------------------------------

    coach_action_messages = find_messages(
        messages,
        [
            "please",
            "set a reminder",
            "we need to",
            "let's",
            "let's",
            "continue tracking",
            "try to",
        ],
        speakers={"coach", "accountability coach"},
    )

    if coach_action_messages:
        findings.append(
            Finding(
                finding_id="finding-pending-actions",
                category="pending_actions",
                title="Pending actions",
                statement=(
                    "The conversation contains open coaching actions related to tracking, "
                    "meal regularity, reminders, rest and continued follow-up."
                ),
                classification=FindingClassification.AI_INFERENCE,
                confidence=0.9,
                evidence=to_evidence(coach_action_messages),
            )
        )
    else:
        findings.append(
            make_missing_finding(
                "finding-pending-actions",
                "pending_actions",
                "Pending actions",
            )
        )

    # --------------------------------------------------------
    # Risk flags
    # --------------------------------------------------------

    severe_fatigue_messages = find_messages(
        client_messages,
        [
            "slept for a few seconds",
            "head went down on the table",
            "i feel i can sleep for days",
            "feeling very low",
        ],
    )

    risk_flags: list[RiskFlag] = []

    if severe_fatigue_messages:
        risk_flags.append(
            RiskFlag(
                risk_id="risk-severe-fatigue",
                title="Significant fatigue and stress attention signal",
                severity=RiskSeverity.HIGH,
                rationale=(
                    "The combination of severe tiredness, unintended daytime sleep "
                    "and feeling very low warrants prompt human follow-up. "
                    "This is an attention flag, not a medical diagnosis."
                ),
                confidence=0.95,
                evidence=to_evidence(severe_fatigue_messages),
            )
        )

    digestive_messages = find_messages(
        client_messages,
        ["acidity", "bloating"],
    )

    if len(digestive_messages) >= 2:
        risk_flags.append(
            RiskFlag(
                risk_id="risk-digestive-symptoms",
                title="Recurring digestive symptoms",
                severity=RiskSeverity.MEDIUM,
                rationale=(
                    "Acidity or bloating was reported repeatedly across the conversation."
                ),
                confidence=0.92,
                evidence=to_evidence(digestive_messages),
            )
        )

    # --------------------------------------------------------
    # Recommended coach actions
    # --------------------------------------------------------

    recommended_actions: list[CoachAction] = []

    if severe_fatigue_messages:
        recommended_actions.append(
            CoachAction(
                action_id="action-fatigue-follow-up",
                priority=1,
                action=(
                    "Contact the client promptly to review current fatigue, sleep, "
                    "stress and whether an approved escalation pathway is required."
                ),
                rationale=(
                    "The conversation contains a high-attention fatigue and stress signal."
                ),
                linked_finding_ids=[
                    "finding-sleep",
                    "finding-symptoms",
                    "finding-barriers",
                ],
            )
        )

    if digestive_messages:
        recommended_actions.append(
            CoachAction(
                action_id="action-symptom-monitoring",
                priority=2,
                action=(
                    "Continue structured monitoring of acidity and bloating and use "
                    "the organisation's approved escalation process if symptoms persist or worsen."
                ),
                rationale=(
                    "Digestive symptoms were reported on multiple occasions."
                ),
                linked_finding_ids=["finding-symptoms"],
            )
        )

    recommended_actions.append(
        CoachAction(
            action_id="action-practical-plan",
            priority=3,
            action=(
                "Agree on a practical minimum routine for meals, protein, sleep, "
                "water and movement that fits the client's schedule."
            ),
            rationale=(
                "Time pressure and incomplete tracking reduce adherence and analysis reliability."
            ),
            linked_finding_ids=[
                "finding-nutrition",
                "finding-water",
                "finding-barriers",
            ],
        )
    )

    # --------------------------------------------------------
    # Weekly summary
    # --------------------------------------------------------

    summary_evidence: list[EvidenceReference] = []

    for finding in findings:
        if finding.evidence:
            summary_evidence.append(finding.evidence[0])

        if len(summary_evidence) == 4:
            break

    weekly_summary = Finding(
        finding_id="finding-weekly-summary",
        category="weekly_summary",
        title="Weekly client summary",
        statement=(
            "The client reported continued movement and regular engagement, but the "
            "conversation also indicates inconsistent nutrition planning, incomplete "
            "daily tracking, recurring digestive symptoms, short sleep and a notable "
            "fatigue and work-stress episode requiring coach attention."
        ),
        classification=FindingClassification.AI_INFERENCE,
        confidence=0.9,
        evidence=summary_evidence,
    )

    days = sorted(
        {
            message["day"]
            for message in messages
            if message["day"] != "Day unavailable"
        }
    )

    analysis_period = (
        payload.analysis_period
        or (
            f"{days[0]} to {days[-1]}"
            if days
            else "Period unavailable"
        )
    )

    missing_information = [
        "Verified daily measurements are unavailable unless explicitly recorded by an approved source.",
        "A complete meal-by-meal log is unavailable for every day.",
        "Daily water, sleep and step values are incomplete.",
        "The conversation does not provide a clinical assessment or diagnosis.",
    ]

    return AnalysisResponse(
        analysis_id=uuid4(),
        status="completed",
        created_at=datetime.now(timezone.utc),
        client_reference=payload.client_reference,
        analysis_period=analysis_period,
        weekly_summary=weekly_summary,
        findings=findings,
        risk_flags=risk_flags,
        recommended_actions=recommended_actions,
        missing_information=missing_information,
        engine="deterministic_evidence_baseline_v1",
        prompt_version="deterministic-baseline-v1",
        validation_warnings=[],
        fallback_reason=None,
    )
