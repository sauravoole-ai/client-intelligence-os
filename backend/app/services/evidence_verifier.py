from dataclasses import dataclass

from backend.app.schemas.client_intelligence import (
    EvidenceReference,
    FindingClassification,
)


class EvidenceValidationError(ValueError):
    pass


@dataclass
class EvidenceValidationResult:
    evidence: list[EvidenceReference]
    warnings: list[str]


def materialize_evidence(
    evidence_message_ids: list[str],
    message_index: dict[str, dict[str, str]],
    classification: FindingClassification,
    item_label: str,
) -> EvidenceValidationResult:
    if classification == FindingClassification.MISSING:
        return EvidenceValidationResult(evidence=[], warnings=[])

    deduplicated_ids: list[str] = []
    seen_ids: set[str] = set()

    for message_id in evidence_message_ids:
        if message_id in seen_ids:
            continue

        if message_id not in message_index:
            raise EvidenceValidationError(
                f"Unknown evidence message ID for {item_label}: {message_id}"
            )

        seen_ids.add(message_id)
        deduplicated_ids.append(message_id)

    if not deduplicated_ids:
        raise EvidenceValidationError(
            f"Non-missing evidence for {item_label} requires at least one valid message ID"
        )

    evidence: list[EvidenceReference] = []

    for message_id in deduplicated_ids:
        source = message_index[message_id]
        evidence.append(
            EvidenceReference(
                message_id=message_id,
                day=source["day"],
                speaker=source["speaker"],
                quote=source["text"],
            )
        )

    warnings: list[str] = []

    if (
        classification == FindingClassification.CONFIRMED_FACT
        and evidence
        and all(item.speaker.lower() == "client" for item in evidence)
    ):
        warnings.append(
            "Confirmed fact evidence from client-only sources must be downgraded to client_reported_information."
        )

    return EvidenceValidationResult(evidence=evidence, warnings=warnings)


def validate_required_categories(findings: list[object]) -> None:
    required_categories = [
        "nutrition_adherence",
        "exercise_steps",
        "sleep",
        "water_intake",
        "symptoms_stress",
        "engagement",
        "barriers",
        "pending_actions",
    ]

    categories = [getattr(finding, "category", "") for finding in findings]

    if len(categories) != len(required_categories):
        raise EvidenceValidationError(
            "Each required category must appear exactly once in the findings list."
        )

    if len(set(categories)) != len(required_categories):
        raise EvidenceValidationError(
            "Duplicate or missing required categories were found in the findings list."
        )

    if set(categories) != set(required_categories):
        raise EvidenceValidationError(
            "Required categories were not satisfied by the findings list."
        )
