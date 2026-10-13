#!/usr/bin/env python3
"""v12.29 shadow-only durability review of v12.28 recovered candidates.

Two independently reviewable phases: v12.28 candidate generation, then a bounded
category-specific durability pass. Gold labels are read only after predictions
are written. Never writes authoritative meeting memory.
"""
from __future__ import annotations
import argparse, copy, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.benchmark.category_recovery_compare import recover, CATEGORIES
from tools.benchmark.memory_benchmark import DEFAULT_CASE_ROOT, DEFAULT_RUN_ROOT, CATEGORY_CONFIG, run_case, score_memory
from tools.benchmark.shadow_compare import _latest_run, norm
from tools.benchmark.enrichment_compare import _is_duplicate, _text, context_excerpt
from tools.benchmark.llm_shadow_compare import anchored

VERDICT_SCHEMA={'type':'object','properties':{
 'durable':{'type':'boolean'},'reason_code':{'type':'string','enum':['durable','not_durable','already_resolved','hypothetical','unsupported_consequence','duplicate','uncertain_owner','weak_evidence','wrong_category']},
 'rationale':{'type':'string'},'evidence':{'type':'string'}},
 'required':['durable','reason_code','rationale','evidence'],'additionalProperties':False}
CONTRACTS={
 'commitments':'An explicit future obligation or accepted assignment with a concrete object; NOT past work, a meeting demo, a generic willingness to help, or a mere proposal. Owner must already have been verified by prior stage.',
 'decisions':'A settled, meeting-specific choice or explicit rejection agreed in the dialogue; NOT product capabilities, proposals, implementation descriptions, or scheduling an exploratory conversation.',
 'risks':'A current concrete exposure with a transcript-supported possible harmful consequence. Conditional outcomes are allowed; a generic challenge, hypothetical, or mere capability limitation is insufficient.',
 'open_questions':'An important issue whose answer remained unknown at meeting end. Rhetorical, teaching/demo, quoted, trivial, or subsequently answered questions are not durable. No owner is required.'}

def review_prompt(cat,item,excerpt,baseline_text):
    return ('You are a conservative DURABILITY reviewer of one meeting-memory ADDITION, not an extractor. '
      'First confirm it is distinct from existing authoritative memory. Judge whether it deserves tracking '
      'AFTER the meeting, not merely whether the source text is true. Apply CATEGORY CONTRACT exactly: '+CONTRACTS[cat]+
      ' Reject if a later passage in SOURCE CONTEXT answers or negates the claim. '
      'If rejected, choose the most specific reason_code. If accepted, reason_code MUST equal durable. '
      'Evidence must be a verbatim continuous excerpt from SOURCE CONTEXT of >= 20 characters that supports '
      'the material claim. A model assertion without matching source evidence must be rejected. '
      'Do not invent a new owner or use baseline text as evidence. Return ONLY JSON per schema.\n'
      'CATEGORY: '+cat+'\nCANDIDATE: '+json.dumps(item,ensure_ascii=False)+
      '\nALREADY RETAINED: '+json.dumps(baseline_text,ensure_ascii=False)+
      '\nSOURCE CONTEXT (chronological): '+excerpt)

def prioritize(category,item):
    """Order review opportunities; not a validity test. Avoid gold-derived ranking."""
    s=_text(category,item).lower()
    patterns={
      'commitments':r'\b(send|update|ask|share|meet|schedule|follow up|contact|prepare|review|obtain|join|provide)\b',
      'decisions':r'\b(agree|decide|will not|do not|won.t|use|exclude|retain|instead)\b',
      'risks':r'\b(could|may|risk|capacity|impact|delay|exposure|shortage|loss|funding|uncertain)\b',
      'open_questions':r'\b(who|what|how|which|whether|when|unknown|tbd|unresolved)\b'}
    return len(re.findall(patterns[category],s))

def durability_filter(baseline,recovered,transcript, *, reviewer=None,review_budget=12):
    """Review recovered additions; keep baseline byte-equivalent and fail closed on errors.

    Budget limits how many suggestions are *reviewed* per category, never how many
    verified items are allowed in authoritative memory.
    """
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda p,s:ask_llm(p,response_format=s)
    result=copy.deepcopy(baseline)
    diagnostics={'accepted':[],'rejected':[],'skipped_budget':[],'errors':[],'considered':0,'reviewed':0}
    for cat in CATEGORIES:
        result.setdefault(cat,[])
        originals=baseline.get(cat,[])
        additions=[]
        for item in recovered.get(cat,[]):
            if _is_duplicate(cat,item,originals): continue
            additions.append(item)
        additions.sort(key=lambda item:-prioritize(cat,item))
        seen=[]
        for index,item in enumerate(additions):
            claim=_text(cat,item)
            diagnostics['considered']+=1
            if index>=review_budget:
                diagnostics['skipped_budget'].append({'category':cat,'claim':claim,'reason':'review budget, not a validity decision'});continue
            if _is_duplicate(cat,item,seen):
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':'duplicate'});continue
            seen.append(item)
            evidence=norm(item.get('evidence','')) if isinstance(item,dict) else ''
            if not evidence or not anchored(evidence,transcript):
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':'weak_evidence'});continue
            excerpt=context_excerpt(transcript,evidence,radius=1400)
            if not excerpt:
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':'weak_evidence'});continue
            diagnostics['reviewed']+=1
            try:
                verdict=json.loads(reviewer(review_prompt(cat,item,excerpt,[_text(cat,x) for x in result[cat]]),VERDICT_SCHEMA))
            except Exception as exc:
                diagnostics['errors'].append({'category':cat,'claim':claim,'error':str(exc)[:180]});continue
            reason=norm(verdict.get('reason_code',''))
            quote=norm(verdict.get('evidence',''))
            if verdict.get('durable') is not True or reason!='durable':
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':reason or 'not_durable','rationale':norm(verdict.get('rationale',''))});continue
            if not anchored(quote,excerpt) or not anchored(quote,transcript):
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':'weak_evidence'});continue
            new=copy.deepcopy(item)
            if isinstance(new,dict):new['evidence']=quote
            if _is_duplicate(cat,new,result[cat]):
                diagnostics['rejected'].append({'category':cat,'claim':claim,'reason_code':'duplicate'});continue
            result[cat].append(new)
            diagnostics['accepted'].append({'category':cat,'claim':claim,'evidence':quote})
    return result,diagnostics

def main(argv=None):
    p=argparse.ArgumentParser(description='v12.29 baseline-protected durability comparison (shadow only)')
    p.add_argument('--all',action='store_true');p.add_argument('--cases',nargs='+')
    p.add_argument('--fresh',action='store_true');p.add_argument('--review-budget',type=int,default=12)
    p.add_argument('--max-contexts',type=int,default=16)
    p.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT)
    p.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    a=p.parse_args(argv)
    if not a.all and not a.cases:p.error('supply --all or --cases')
    if a.review_budget<1 or a.review_budget>100:p.error('review-budget must be 1..100')
    if a.max_contexts<1 or a.max_contexts>50:p.error('max-contexts must be 1..50')
    cases=sorted(f for f in a.case_root.iterdir() if f.is_dir() and (a.all or f.name in a.cases)) if a.case_root.exists() else []
    if not cases:p.error('no private benchmark cases')
    root=a.run_root/'durability_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');root.mkdir(parents=True,exist_ok=True)
    lines=['# v12.29 durability-aware comparison','','Shadow only; private gold labels read after predictions are persisted.','','| Case | Category | Baseline P/R | Enriched P/R | Matched baseline → enriched |','|---|---|---|---|---|']
    failures=0
    for case in cases:
        try:
            print(f'[{case.name}] preparing...',flush=True)
            baseline_dir=Path(run_case(case,a.run_root)['output_dir']) if a.fresh else _latest_run(case.name,a.run_root)
            if baseline_dir is None:raise FileNotFoundError('baseline absent; run baseline benchmark or supply --fresh')
            baseline=json.loads((baseline_dir/'actual_memory.json').read_text())
            transcript=(case/'meeting_transcript_cleaned.md').read_text()
            metadata=json.loads((case/'meeting_metadata.json').read_text())
            start=time.monotonic()
            recovered,recovery_diag=recover(baseline,transcript,metadata.get('participants',[]),max_contexts=a.max_contexts)
            enriched,diag=durability_filter(baseline,recovered,transcript,review_budget=a.review_budget)
            out=root/case.name;out.mkdir()
            for name,data in [('baseline_memory.json',baseline),('recovered_memory.json',recovered),('enriched_memory.json',enriched),('diagnostics.json',{'recovery':recovery_diag,'durability':diag,'elapsed_seconds':round(time.monotonic()-start,2),'baseline_dir':str(baseline_dir)})]:
                (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False))
            gold=json.loads((case/'expected_memory.json').read_text())
            b=score_memory(baseline,gold);e=score_memory(enriched,gold)
            (out/'comparison.json').write_text(json.dumps({'baseline':b,'enriched':e},indent=2))
            for cat in CATEGORIES:
                x,y=b['categories'][cat],e['categories'][cat]
                lines.append(f"| {case.name} | {cat} | {x['precision']:.2f}/{x['recall']:.2f} | {y['precision']:.2f}/{y['recall']:.2f} | {x['matched_count']}/{x['expected_count']} → {y['matched_count']}/{y['expected_count']} |")
            print(f"[{case.name}] baseline={'PASS' if b['passed'] else 'FAIL'} enriched={'PASS' if e['passed'] else 'FAIL'} accepted={len(diag['accepted'])} reviewed={diag['reviewed']}",flush=True)
        except Exception as exc:
            failures+=1;lines.append(f'| {case.name} | ERROR | {type(exc).__name__}: {exc} | | |')
            print(f'[{case.name}] ERROR {exc}',file=sys.stderr,flush=True)
    (root/'comparison.md').write_text('\n'.join(lines)+'\n')
    print(f'Report: {root}/comparison.md')
    return 1 if failures else 0
if __name__=='__main__':raise SystemExit(main())
