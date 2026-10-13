"""Read-only final memory provenance; never grants verification or changes memory."""


def _signature(section, item):
    if section == 'open_questions':
        if isinstance(item, dict):
            return (str(item.get('question', '')).strip(), str(item.get('evidence', '')).strip())
        return (str(item).strip(),)
    if not isinstance(item, dict):
        return (str(item).strip(),)
    field = {'commitments': 'action', 'decisions': 'decision', 'risks': 'risk'}[section]
    if section == 'commitments':
        return (str(item.get(field, '')).strip(), str(item.get('owner', '')).strip(),
                str(item.get('evidence', '')).strip())
    return (str(item.get(field, '')).strip(), str(item.get('evidence', '')).strip())


def audit_final_provenance(final_memory, verified_memory, downstream_audit=None):
    """Classify final entries using the *actual* verified resolver output.

    Nonmatches are explicitly not claimed to be validator-approved. Earlier
    audit events are surfaced as clues, not proof of a particular recovery step.
    """
    verified_memory = verified_memory if isinstance(verified_memory, dict) else {}
    final_memory = final_memory if isinstance(final_memory, dict) else {}
    downstream_audit = downstream_audit if isinstance(downstream_audit, list) else []
    output = []
    for section in ('commitments', 'decisions', 'risks', 'open_questions'):
        verified = verified_memory.get(section) or []
        if section == 'open_questions' and '_verified_open_questions' in verified_memory:
            verified = verified_memory.get('_verified_open_questions') or []
        signatures = {_signature(section, x) for x in verified}
        for item in final_memory.get(section, []) or []:
            signature = _signature(section, item)
            is_verified = signature in signatures
            clues = [r.get('reason') for r in downstream_audit
                     if isinstance(r, dict) and r.get('section') == section
                     and r.get('disposition') == 'recovered'
                     and (r.get('value') == item or r.get('value') == signature[0])]
            output.append({
                'section': section,
                'value': item,
                'disposition': 'retained',
                'verification_status': 'verified' if is_verified else 'not_verified',
                'origin': 'verified_resolver' if is_verified else 'post_verification_or_legacy',
                'recovery_clues': clues,
            })
    return output
