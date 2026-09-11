import type { LongitudinalEvidenceReference, WhatChangedResponse } from '../types';

function evidenceLabel(evidence: LongitudinalEvidenceReference) {
  return evidence.analysis_id
    ? `Analysis ${evidence.artifact_kind?.replace('_', ' ') ?? 'artifact'}: ${evidence.artifact_id}`
    : `Action Item: ${evidence.action_field}`;
}

export function WhatChangedPanel({ response }: { response: WhatChangedResponse }) {
  return <section className="what-changed" aria-labelledby="what-changed-title">
    <div><div className="eyebrow">Trusted comparison</div><h2 id="what-changed-title">What changed</h2></div>
    <div className="what-changed__cards">{response.items.map((item, index) => <article className="what-changed__card" key={`${item.signal_id ?? item.change_kind}-${index}`}>
      <span className="badge">{item.change_kind.replace('_', ' ')}</span><h3>{item.summary}</h3>
      {item.evidence.length > 0 && <ul>{item.evidence.map((evidence, evidenceIndex) => <li key={evidenceIndex}>Evidence: {evidenceLabel(evidence)} ({evidence.evidence_role})</li>)}</ul>}
    </article>)}</div>
  </section>;
}
