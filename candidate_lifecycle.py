"""Read-only, privacy-sensitive snapshots of memory candidates across pipeline stages.

The resulting trace contains transcript excerpts. Never publish it.
"""
from __future__ import annotations

import hashlib
import json

CATEGORIES = ('commitments', 'decisions', 'risks', 'open_questions')


def _rows(memory, category):
    rows = memory.get(category, []) if isinstance(memory, dict) else []
    return rows if isinstance(rows, list) else []


def _identity(category, row):
    if isinstance(row, dict):
        # Stable across metadata/provenance changes; category and text determine identity.
        keys = {'commitments': ('action', 'commitment', 'task'),
                'decisions': ('decision',), 'risks': ('risk',),
                'open_questions': ('question',)}[category]
        value = next((str(row.get(k, '')).strip() for k in keys if row.get(k)), '')
        if not value:
            value = json.dumps(row, sort_keys=True, default=str)
    else:
        value = str(row).strip()
    return hashlib.sha256((category + '\0' + value.casefold()).encode()).hexdigest()[:16]


def snapshot(memory):
    """Return a detached, JSON-safe view; never modify the supplied memory."""
    result = {}
    for category in CATEGORIES:
        result[category] = [
            {'id': _identity(category, row), 'value': json.loads(json.dumps(row, default=str))}
            for row in _rows(memory, category)
        ]
    return result


def transition(previous, current, stage):
    """Describe additions, removals and edits between two snapshots."""
    changes = []
    for category in CATEGORIES:
        before = {r['id']: r['value'] for r in previous.get(category, [])}
        after = {r['id']: r['value'] for r in current.get(category, [])}
        for candidate_id in sorted(before.keys() | after.keys()):
            if candidate_id not in before:
                status = 'added'
            elif candidate_id not in after:
                status = 'removed'
            elif before[candidate_id] != after[candidate_id]:
                status = 'modified'
            else:
                continue
            changes.append({'stage': stage, 'category': category,
                            'candidate_id': candidate_id, 'change': status,
                            'before': before.get(candidate_id),
                            'after': after.get(candidate_id)})
    return changes
