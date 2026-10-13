#!/usr/bin/env python3
"""Read-only v12.25 exploratory evidence-linked shadow comparison.

The shadow is a conservative, deterministic event adjudicator, NOT a replacement
for the MLX resolver. It reads only grounded trace events; it never reads gold
until after constructing its candidate memory. Its purpose is to quantify the
value/limitations of event-level evidence selection before investing in LLM calls.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.benchmark.memory_benchmark import (DEFAULT_CASE_ROOT, DEFAULT_RUN_ROOT, CATEGORY_CONFIG,
                                              run_case, score_memory)

_FUTURE = re.compile(r"\b(i(?:'ll| will| am going to)|we(?:'ll| will| are going to)|going to|will|next week|tomorrow|this week)\b", re.I)
_SPECIFIC = re.compile(r"\b(send|share|schedule|set up|invite|ask|follow up|update|revise|publish|save|distribute|reach out|research|investigate|document|clarify|obtain|provide|prepare|talk to)\b", re.I)
_OPEN = re.compile(r"\b(tbd|not (?:yet )?(?:decided|known|clear|determined)|don't know|do not know|still (?:open|unclear)|have to figure|need to figure)\b", re.I)
_DECISION = re.compile(r"\b(we (?:agreed|decided)|let's use|we (?:will|won't|are not going to)|do not (?:change|update)|don't (?:change|update))\b", re.I)
_RISK = re.compile(r"\b(risk|concern|could|might|hard to|capacity|shortfall|attrition|turnover|lack|gap)\b", re.I)
_BANNED = {'mic', 'remote', 'unknown', 'you', 'speaker', ''}
_STOP = {'the','a','an','to','for','with','and','of','on','in','that','is','it','we','i','this','will','would','like','about','be','some','all','up'}

def norm(s): return re.sub(r'\s+', ' ', str(s or '')).strip()
def tokens(s): return set(re.findall(r'[a-z0-9]{3,}', norm(s).lower())) - _STOP

def _overlap(a, b):
    a, b = tokens(a), tokens(b)
    return len(a & b) / min(len(a), len(b)) if a and b else 0

def _evidence_valid(event, transcript):
    evidence = event.get('evidence') or []
    if isinstance(evidence, str): evidence=[evidence]
    # Do not invent evidence: require an exact contiguous anchor, allowing whitespace differences.
    compact = norm(transcript).casefold()
    return [norm(e) for e in evidence if len(norm(e)) > 15 and norm(e).casefold() in compact]

def _append_unique(items, category, item):
    key = CATEGORY_CONFIG[category]['text_key']
    candidate = item[key]
    for old in items:
        if _overlap(candidate, old[key]) >= .88:
            return
    items.append(item)

def resolve_shadow(trace, transcript):
    """Classify grounded events without consulting the expected benchmark labels."""
    out = {'topics':[], 'commitments':[], 'decisions':[], 'risks':[], 'open_questions':[], 'follow_ups':[]}
    diag={'considered':0,'evidence_rejected':0,'unresolved_owner':0,'accepted':[],'skipped':[]}
    ident = {str(k).casefold(): v for k,v in (trace.get('identity_map') or {}).items() if isinstance(v,str)}
    # Use bounded grounded event candidates, with verified evidence, rather than synthesized summary.
    for event in trace.get('merged_events') or []:
        diag['considered']+=1
        subject=norm(event.get('subject'))
        ev=_evidence_valid(event, transcript)
        if not ev or not subject:
            diag['evidence_rejected']+=1
            continue
        kind=str(event.get('event_type') or '').lower()
        evidence=' '.join(ev)
        who=str(event.get('speaker') or '').strip()
        owner=ident.get(who.casefold(), who)
        if kind in ('commitment','next_step','assignment') and _SPECIFIC.search(subject) and _FUTURE.search(evidence):
            if owner.casefold() in _BANNED:
                diag['unresolved_owner']+=1
                diag['skipped'].append({'reason':'uncertain_owner','subject':subject})
                continue
            item={'owner':owner,'action':subject[0].upper()+subject[1:].rstrip('.')+'.','status':'open','evidence':ev[0]}
            _append_unique(out['commitments'],'commitments',item)
            diag['accepted'].append({'category':'commitments','subject':subject})
        elif kind in ('question','uncertainty') and (_OPEN.search(evidence) or ('?' in evidence and kind=='question')):
            # Require question semantics in the subject and concrete underlying evidence.
            if kind == 'question' and not (subject.startswith(('who','what','when','where','how','which','whether')) or '?' in subject): continue
            question=subject[0].upper()+subject[1:].rstrip('?.')+'?'
            _append_unique(out['open_questions'],'open_questions',{'question':question,'evidence':ev[0]})
            diag['accepted'].append({'category':'open_questions','subject':subject})
        elif kind in ('decision','agreement') and _DECISION.search(evidence):
            _append_unique(out['decisions'],'decisions',{'decision':subject,'evidence':ev[0]})
            diag['accepted'].append({'category':'decisions','subject':subject})
        elif kind=='concern' and _RISK.search(evidence) and _RISK.search(subject):
            _append_unique(out['risks'],'risks',{'risk':subject,'evidence':ev[0]})
            diag['accepted'].append({'category':'risks','subject':subject})
    return out, diag

def _latest_run(case, run_root):
    candidates=list(run_root.glob(f'*/{case}/memory_trace.json'))
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0].parent if candidates else None

def _score_row(score,cat):
    c=score['categories'][cat]
    return f"{c['matched_count']}/{c['expected_count']} ; {c['precision']:.2f} ; {c['recall']:.2f}"

def compare_one(case_dir, run_root, reuse, output_dir):
    name=case_dir.name
    start=time.perf_counter()
    if reuse:
        existing=_latest_run(name,run_root)
        if existing is None: raise FileNotFoundError(f'No previous run for {name}; omit --reuse')
        base_dir=existing
    else:
        result=run_case(case_dir,run_root)
        base_dir=Path(result['output_dir'])
    trace=json.loads((base_dir/'memory_trace.json').read_text())
    baseline=json.loads((base_dir/'actual_memory.json').read_text())
    gold=json.loads((case_dir/'expected_memory.json').read_text())
    transcript=(case_dir/'meeting_transcript_cleaned.md').read_text()
    shadow, diag=resolve_shadow(trace, transcript)
    b_score=score_memory(baseline,gold)
    s_score=score_memory(shadow,gold)
    target=output_dir/name
    target.mkdir(parents=True,exist_ok=True)
    payload={'case':name,'baseline_dir':str(base_dir),'baseline_score':b_score,'shadow_score':s_score,
             'shadow_diagnostics':diag,'comparison_elapsed_seconds':round(time.perf_counter()-start,2),
             'shadow_experimental':True}
    for fn,obj in [('shadow_memory.json',shadow),('comparison.json',payload)]:
        (target/fn).write_text(json.dumps(obj,indent=2))
    return payload

def main(argv=None):
    p=argparse.ArgumentParser(description='Compare production v12 memory with read-only event-linked v12.25 shadow.')
    p.add_argument('--cases', nargs='+', help='Case names, e.g. case-one case-two')
    p.add_argument('--all',action='store_true')
    p.add_argument('--reuse',action='store_true',help='Use latest existing baseline run instead of calling the LLM')
    p.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT)
    p.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    p.add_argument('--output-root',type=Path,default=DEFAULT_RUN_ROOT/'shadow_comparisons')
    a=p.parse_args(argv)
    if not a.all and not a.cases: p.error('Supply --cases NAME [NAME ...] or --all')
    cases=sorted(d for d in a.case_root.iterdir() if d.is_dir() and (a.all or d.name in a.cases)) if a.case_root.exists() else []
    missing=set(a.cases or [])-{d.name for d in cases}
    if missing: p.error('Unknown cases: '+', '.join(sorted(missing)))
    if not cases: p.error('No private benchmark cases found')
    output=a.output_root/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=True)
    lines=['# Evidence-linked shadow comparison (experimental)','',
           'Shadow output is advisory only; production memories and private gold are unchanged.','',
           '| Case | Category | Baseline match; precision; recall | Shadow match; precision; recall |',
           '|---|---|---|---|']
    error=False
    for case in cases:
        try: r=compare_one(case,a.run_root,a.reuse,output)
        except Exception as exc:
            error=True;print(f'{case.name}: ERROR {exc}',file=sys.stderr);continue
        for cat in CATEGORY_CONFIG:
            lines.append(f"| {case.name} | {cat} | {_score_row(r['baseline_score'],cat)} | {_score_row(r['shadow_score'],cat)} |")
        print(f"{case.name}: baseline={'PASS' if r['baseline_score']['passed'] else 'FAIL'} shadow={'PASS' if r['shadow_score']['passed'] else 'FAIL'}")
    (output/'comparison.md').write_text('\n'.join(lines)+'\n')
    print(f'Comparison: {output / "comparison.md"}')
    return 2 if error else 0 # Failing quality is a measurement, not a CLI execution error.

if __name__=='__main__':raise SystemExit(main())
