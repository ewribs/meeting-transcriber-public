#!/usr/bin/env python3
"""v12.27: non-mutating baseline-protected experimental memory enrichment.

Gold data is read only after both prediction files are written. All outputs stay
under ignored benchmark_runs/. Never writes to source meetings or archives.
"""
from __future__ import annotations
import argparse
import copy
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
from tools.benchmark.llm_shadow_compare import resolve_llm_shadow, anchored, BAD_OWNERS

CATEGORIES = tuple(CATEGORY_CONFIG)
VERDICT_SCHEMA = {'type':'object','properties':{'accept':{'type':'boolean'},'reason':{'type':'string'},
    'category':{'type':'string','enum':list(CATEGORIES)+['none']},'evidence':{'type':'string'},
    'owner':{'type':'string'}},'required':['accept','reason','category','evidence','owner'],
    'additionalProperties':False}


def _text(category, item):
    key=CATEGORY_CONFIG[category]['text_key']
    return norm(item.get(key,'')) if isinstance(item,dict) else norm(item)


def context_excerpt(transcript, evidence, radius=550):
    """Find source quote with whitespace-insensitive offsets and include neighbors."""
    t=re.sub(r'\s+', ' ', transcript)
    q=norm(evidence)
    index=t.casefold().find(q.casefold())
    if index<0:return ''
    return t[max(0,index-radius):min(len(t), index+len(q)+radius)]


def _is_duplicate(category, item, existing):
    target=_text(category,item)
    for prior in existing:
        text=_text(category,prior)
        if target.casefold()==text.casefold() or _overlap(target,text)>=.77:
            return True
    return False


def adjudication_review_prompt(category,item, excerpt, baseline):
    return ("You are a strict second reviewer of ONE proposed addition to established meeting memory. "
      "Reject unless the ORIGINAL dialogue establishes this as a durable, distinct memory not already recorded. "
      "Assess precise event status (proposed vs accepted, hypothetical vs actual, past vs future), "
      "whether a question is still unresolved, and whether a risk has explicit exposure and consequence. "
      "A plan to have a meeting is a commitment, not a policy decision. Do not convert walkthrough "
      "examples into decisions or actions. A vague statement is insufficient. "
      "For commitments, accept only a reliable named owner from the source context, not Remote, Mic, "
      "Unknown, or a guessed identity. Reject rather than invent attribution. "
      "The final evidence MUST be a verbatim continuous substring from SOURCE CONTEXT; choose the "
      "shortest sufficient proof. Return structured JSON. If rejected, set category none. "
      "Never treat BASELINE content as source evidence.\n"
      'CATEGORY: '+category+'\nCANDIDATE: '+json.dumps(item,ensure_ascii=False)+
      '\nBASELINE SAME CATEGORY: '+json.dumps([_text(category,x) for x in baseline],ensure_ascii=False)+
      '\nSOURCE CONTEXT: '+excerpt)


def enrich_baseline(baseline, shadow, transcript, participants, *, reviewer=None):
    """Apply only positively reverified distinct items to a deep copy of baseline."""
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    enriched=copy.deepcopy(baseline)
    diag={'proposed':0,'accepted':[],'rejected':[],'review_errors':[]}
    valid_names={norm(p.get('name','')).casefold():norm(p.get('name','')) for p in (participants or []) if isinstance(p,dict)}
    for category in CATEGORIES:
        enriched.setdefault(category,[])
        for item in shadow.get(category,[]):
            diag['proposed']+=1
            claim=_text(category,item)
            evidence=norm(item.get('evidence','')) if isinstance(item,dict) else ''
            if not claim or not evidence or not anchored(evidence,transcript):
                diag['rejected'].append({'category':category,'claim':claim,'reason':'missing exact evidence'});continue
            if _is_duplicate(category,item,enriched[category]):
                diag['rejected'].append({'category':category,'claim':claim,'reason':'duplicate baseline memory'});continue
            excerpt=context_excerpt(transcript,evidence)
            if not excerpt:
                diag['rejected'].append({'category':category,'claim':claim,'reason':'no source context'});continue
            try:
                verdict=json.loads(reviewer(adjudication_review_prompt(category,item,excerpt,enriched[category]),VERDICT_SCHEMA))
            except Exception as exc:
                diag['review_errors'].append({'category':category,'claim':claim,'error':str(exc)[:180]});continue
            reviewed_evidence=norm(verdict.get('evidence',''))
            reviewed_category=verdict.get('category')
            owner=norm(verdict.get('owner',''))
            reason=norm(verdict.get('reason',''))
            reject=None
            if verdict.get('accept') is not True or reviewed_category!=category:reject='context reviewer rejected: '+reason
            elif not anchored(reviewed_evidence,excerpt):reject='review evidence not exact source substring'
            elif category=='commitments' and (owner.casefold() in BAD_OWNERS or owner.casefold() not in valid_names):
                reject='no verified named commitment owner'
            elif category=='commitments' and norm(item.get('owner','')).casefold()!=owner.casefold():
                reject='owner not independently consistent'
            if reject:
                diag['rejected'].append({'category':category,'claim':claim,'reason':reject});continue
            addition=copy.deepcopy(item)
            if isinstance(addition,dict):
                addition['evidence']=reviewed_evidence
                if category=='commitments':addition['owner']=valid_names[owner.casefold()]
            if _is_duplicate(category,addition,enriched[category]):
                diag['rejected'].append({'category':category,'claim':claim,'reason':'post-review duplicate'});continue
            enriched[category].append(addition)
            diag['accepted'].append({'category':category,'claim':claim,'evidence':reviewed_evidence})
    return enriched,diag


def compare(argv=None):
    parser=argparse.ArgumentParser(description='v12.27 baseline-protected read-only enrichment comparison')
    parser.add_argument('--all',action='store_true')
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--fresh',action='store_true',help='rerun baseline first; default uses newest trace')
    parser.add_argument('--batch-size',type=int,default=5)
    parser.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT)
    parser.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    args=parser.parse_args(argv)
    if not args.all and not args.cases:parser.error('supply --all or --cases')
    if not 1<=args.batch_size<=10:parser.error('batch size must be 1..10')
    cases=sorted(p for p in args.case_root.iterdir() if p.is_dir() and (args.all or p.name in args.cases)) if args.case_root.exists() else []
    if not cases:parser.error('no private benchmark cases found')
    out=args.run_root/'enrichment_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=True)
    rows=['# v12.27 baseline-protected enrichment comparison','',
          'Experimental only. No application/archive meeting memories were modified.','',
          '| Case | Category | Baseline correct/expected | Enriched correct/expected | Baseline P/R | Enriched P/R |',
          '|---|---|---|---|---|---|']
    failures=0
    for case in cases:
        print(f'[{case.name}] preparing baseline',flush=True)
        dest=out/case.name;dest.mkdir()
        try:
            if args.fresh:
                base=Path(run_case(case,args.run_root)['output_dir'])
            else:
                base=_latest_run(case.name,args.run_root)
                if base is None:raise FileNotFoundError('no existing memory trace; run --fresh')
            baseline=json.loads((base/'actual_memory.json').read_text())
            trace=json.loads((base/'memory_trace.json').read_text())
            transcript=(case/'meeting_transcript_cleaned.md').read_text()
            participants=json.loads((case/'meeting_metadata.json').read_text()).get('participants',[])
            started=time.perf_counter()
            shadow,shadow_diag=resolve_llm_shadow(trace,transcript,participants,batch_size=args.batch_size)
            enriched,enrich_diag=enrich_baseline(baseline,shadow,transcript,participants)
            # Immutable baseline check and persist predictions BEFORE reading gold.
            (dest/'baseline_memory.json').write_text(json.dumps(baseline,indent=2))
            (dest/'candidate_memory.json').write_text(json.dumps(shadow,indent=2))
            (dest/'enriched_memory.json').write_text(json.dumps(enriched,indent=2))
            (dest/'diagnostics.json').write_text(json.dumps({'shadow':shadow_diag,'enrichment':enrich_diag,'elapsed_seconds':round(time.perf_counter()-started,2),'baseline_path':str(base)},indent=2))
            gold=json.loads((case/'expected_memory.json').read_text())
            b=score_memory(baseline,gold);e=score_memory(enriched,gold)
            (dest/'comparison.json').write_text(json.dumps({'baseline':b,'enriched':e},indent=2))
            for category in CATEGORIES:
                x=b['categories'][category];y=e['categories'][category]
                rows.append(f"| {case.name} | {category} | {x['matched_count']}/{x['expected_count']} | {y['matched_count']}/{y['expected_count']} | {x['precision']:.2f}/{x['recall']:.2f} | {y['precision']:.2f}/{y['recall']:.2f} |")
            print(f"[{case.name}] baseline={'PASS' if b['passed'] else 'FAIL'} enrichment={'PASS' if e['passed'] else 'FAIL'} additions={len(enrich_diag['accepted'])}",flush=True)
        except Exception as exc:
            failures+=1
            rows.append(f'| {case.name} | ERROR | {type(exc).__name__}: {exc} | | | |')
            print(f'[{case.name}] ERROR: {exc}',file=sys.stderr,flush=True)
    (out/'comparison.md').write_text('\n'.join(rows)+'\n')
    print(f'\nReport: {out}/comparison.md')
    print('All artifacts remain in ignored benchmark_runs/.')
    return 1 if failures else 0

if __name__=='__main__':raise SystemExit(compare())
