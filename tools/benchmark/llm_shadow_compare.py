#!/usr/bin/env python3
"""v12.26 read-only, batched local-LLM adjudication of grounded benchmark events.

Never loads expected gold until AFTER predictions are written. Never writes meeting archives.
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
from tools.benchmark.memory_benchmark import DEFAULT_CASE_ROOT, DEFAULT_RUN_ROOT, CATEGORY_CONFIG, run_case, score_memory
from tools.benchmark.shadow_compare import _latest_run, _overlap, norm

KINDS = ('commitments', 'decisions', 'risks', 'open_questions', 'none')
BAD_OWNERS = {'remote','mic','unknown','speaker','you',''}
SCHEMA = {'type':'object','properties':{'items':{'type':'array','items':{'type':'object','properties':{
    'id':{'type':'integer'}, 'category':{'type':'string','enum':list(KINDS)},
    'text':{'type':'string'}, 'owner':{'type':'string'},
    'evidence':{'type':'string'}, 'reason':{'type':'string'}},
    'required':['id','category','text','owner','evidence','reason'],'additionalProperties':False}}},
    'required':['items'],'additionalProperties':False}

def anchored(evidence, transcript):
    compact=norm(transcript).casefold()
    quote=norm(evidence)
    return bool(len(quote)>=20 and quote.casefold() in compact)

def event_evidence(event, transcript):
    q=event.get('evidence') or []
    if isinstance(q,str):q=[q]
    return next((norm(s) for s in q if anchored(s, transcript)), '')

def adjudication_prompt(batch):
    return ("You adjudicate individual conversational events for DURABLE meeting memory. "
      "Judge each event independently using ONLY its supplied exact transcript evidence. "
      "Return exactly one item per id. Categories: commitments, decisions, risks, open_questions, none. "
      "A commitment requires explicit actionable FUTURE work. A meeting scheduled is normally a commitment, "
      "NOT a decision. Decisions require a settled policy/choice, including negative choices. "
      "An open question must be material, unresolved, and not a rhetorical or illustrative question. "
      "A risk needs a specific stated exposure and plausible consequence, not an invented business concern. "
      "Ignore past work, completed demos, generic intentions, and vague help. "
      "Do not turn Remote/Mic into names; use empty owner if speaker identity is unverified. "
      "When evidence is inconclusive choose none. Output concise self-contained text and a VERBATIM continuous "
      "evidence substring of the supplied evidence, never paraphrase evidence. Explain each classification briefly. "
      "Do not include events absent from inputs.\n\nEVENTS:\n"+json.dumps(batch,ensure_ascii=False))

def add_unique(mem, category, item):
    key=CATEGORY_CONFIG[category]['text_key']
    s=item[key]
    if any(_overlap(s, existing[key])>=.83 for existing in mem[category]):return False
    mem[category].append(item)
    return True

def resolve_llm_shadow(trace, transcript, participants=None, *, batch_size=5, llm=None):
    """Injectable llm(prompt, schema) -> JSON string; default is installed local backend."""
    if llm is None:
        from ai import ask_llm
        llm=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    out={'topics':[],'commitments':[],'decisions':[],'risks':[],'open_questions':[],'follow_ups':[]}
    diag={'candidate_count':0,'batch_count':0,'accepted':[],'rejected':[],'uncertain_ownership':[],'errors':[]}
    events=[]
    for i, e in enumerate(trace.get('merged_events') or []):
        quote=event_evidence(e, transcript)
        if not quote:
            diag['rejected'].append({'id':i,'reason':'no exact source evidence'})
            continue
        events.append({'id':i,'type':e.get('event_type',''),'subject':norm(e.get('subject','')),
                       'speaker_channel':e.get('speaker',''),'evidence':quote[:1900]})
    diag['candidate_count']=len(events)
    known={norm(p.get('name','')).casefold():norm(p.get('name','')) for p in (participants or []) if isinstance(p,dict)}
    for offset in range(0,len(events),batch_size):
        batch=events[offset:offset+batch_size]
        diag['batch_count']+=1
        try:
            response=json.loads(llm(adjudication_prompt(batch), SCHEMA))
            decisions=response.get('items',[])
            if not isinstance(decisions,list):raise ValueError('items is not a list')
        except Exception as exc:
            diag['errors'].append({'batch':offset//batch_size,'error':str(exc)[:300]})
            continue
        by_id={e['id']:e for e in batch}
        seen=set()
        for pred in decisions:
            if not isinstance(pred,dict):continue
            idx=pred.get('id')
            if idx not in by_id or idx in seen:continue
            seen.add(idx)
            original=by_id[idx]
            category=pred.get('category','none')
            statement=norm(pred.get('text',''))
            evidence=norm(pred.get('evidence',''))
            owner=norm(pred.get('owner',''))
            reject=None
            if category not in KINDS or category=='none':reject='not durable'
            elif not statement:reject='empty claim'
            elif not anchored(evidence,original['evidence']):reject='evidence not exact substring of event'
            elif category=='commitments' and owner.casefold() not in known:
                # Keep verified action internally even if speaker identity is unknown.
                diag['uncertain_ownership'].append({'id':idx,'action':statement,'owner_claim':owner,'evidence':evidence})
                reject='uncertain owner (diagnostic only)'
            if reject:
                diag['rejected'].append({'id':idx,'reason':reject,'claim':statement,'category':category})
                continue
            if category=='commitments':item={'owner':known[owner.casefold()],'action':statement,'status':'open','evidence':evidence}
            elif category=='open_questions':item={'question':statement,'evidence':evidence}
            elif category=='decisions':item={'decision':statement,'evidence':evidence}
            else:item={'risk':statement,'evidence':evidence}
            if add_unique(out,category,item):diag['accepted'].append({'id':idx,'category':category,'text':statement})
        for row in batch:
            if row['id'] not in seen:diag['rejected'].append({'id':row['id'],'reason':'no model response'})
    return out,diag

def main(argv=None):
    ap=argparse.ArgumentParser(description='Read-only local-LLM event adjudication comparison (v12.26)')
    ap.add_argument('--all',action='store_true');ap.add_argument('--cases',nargs='+')
    ap.add_argument('--reuse',action='store_true',help='Reuse latest existing baseline trace (default)')
    ap.add_argument('--fresh',action='store_true',help='Regenerate existing baseline before adjudication')
    ap.add_argument('--batch-size',type=int,default=5)
    ap.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT)
    ap.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    a=ap.parse_args(argv)
    if a.batch_size<1 or a.batch_size>10:ap.error('batch-size must be between 1 and 10')
    if not a.all and not a.cases:ap.error('specify --all or --cases')
    cases=sorted(p for p in a.case_root.iterdir() if p.is_dir() and (a.all or p.name in a.cases)) if a.case_root.exists() else []
    if not cases:ap.error('no matching private benchmark cases')
    out_dir=a.run_root/'llm_shadow_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir.mkdir(parents=True,exist_ok=True)
    report=['# v12.26 local LLM event-level shadow comparison','','No production memory files were modified.','','| Case | Category | Existing P/R | Shadow P/R | Correct Existing / Shadow |','|---|---|---|---|---|']
    for case in cases:
        print(f'[{case.name}] loading baseline...',flush=True)
        try:
            if a.fresh:
                base=Path(run_case(case,a.run_root)['output_dir'])
            else:
                base=_latest_run(case.name,a.run_root)
                if base is None:raise FileNotFoundError('no baseline trace; use --fresh')
            trace=json.loads((base/'memory_trace.json').read_text())
            existing=json.loads((base/'actual_memory.json').read_text())
            transcript=(case/'meeting_transcript_cleaned.md').read_text()
            metadata=json.loads((case/'meeting_metadata.json').read_text())
            print(f'[{case.name}] adjudicating events...',flush=True)
            start=time.perf_counter()
            shadow,diagnostics=resolve_llm_shadow(trace,transcript,metadata.get('participants'),batch_size=a.batch_size)
            dest=out_dir/case.name;dest.mkdir()
            # Persist predictions BEFORE opening benchmark labels.
            (dest/'shadow_memory.json').write_text(json.dumps(shadow,indent=2))
            (dest/'shadow_diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
            gold=json.loads((case/'expected_memory.json').read_text())
            bs=score_memory(existing,gold);ss=score_memory(shadow,gold)
            (dest/'comparison.json').write_text(json.dumps({'baseline_score':bs,'shadow_score':ss,'baseline_path':str(base),'adjudication_seconds':round(time.perf_counter()-start,2)},indent=2))
            for cat in CATEGORY_CONFIG:
                old,new=bs['categories'][cat],ss['categories'][cat]
                report.append(f"| {case.name} | {cat} | {old['precision']:.2f}/{old['recall']:.2f} | {new['precision']:.2f}/{new['recall']:.2f} | {old['matched_count']} / {new['matched_count']} |")
            print(f"[{case.name}] existing={'PASS' if bs['passed'] else 'FAIL'}, shadow={'PASS' if ss['passed'] else 'FAIL'}",flush=True)
        except Exception as exc:
            report.append(f'| {case.name} | ERROR | {type(exc).__name__}: {exc} | | |')
            print(f'[{case.name}] ERROR: {exc}',file=sys.stderr)
    (out_dir/'comparison.md').write_text('\n'.join(report)+'\n')
    print(f'\nReport: {out_dir}/comparison.md')
    print('Private outputs remain under ignored benchmark_runs/.')
    return 0
if __name__=='__main__':raise SystemExit(main())
