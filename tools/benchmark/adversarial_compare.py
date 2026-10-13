#!/usr/bin/env python3
"""v12.31 shadow-only adversarial review following v12.30 full-meeting veto.

Uses category batches with chronological full transcript to reject locally plausible
but globally resolved/demonstration/duplicate material. Never changes baseline memory.
"""
from __future__ import annotations
import argparse, copy, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.benchmark.durability_compare import durability_filter
from tools.benchmark.category_recovery_compare import recover,CATEGORIES
from tools.benchmark.memory_benchmark import DEFAULT_CASE_ROOT,DEFAULT_RUN_ROOT,run_case,score_memory
from tools.benchmark.shadow_compare import _latest_run
from tools.benchmark.enrichment_compare import _text,_is_duplicate

SCHEMA={'type':'object','properties':{'keep_indices':{'type':'array','items':{'type':'integer'}},'reasons':{'type':'array','items':{'type':'object','properties':{'index':{'type':'integer'},'reason':{'type':'string'}},'required':['index','reason'],'additionalProperties':False}}},'required':['keep_indices','reasons'],'additionalProperties':False}

CATEGORY_RULES={
'commitments':'Keep only an explicit concrete future task with grounded attribution; reject conversations, intentions, demos, duplicates, and tasks already completed. Unknown speaker identity is NOT grounds to invent an owner.',
'decisions':'Keep only decisions actually agreed in this meeting, including explicit decisions NOT to do something. Reject software features, demos, proposed choices, and actions to arrange meetings.',
'risks':'Keep only an actively relevant material exposure with concrete, specifically supported consequence. Do NOT elevate product setup requirements, hypothetical if/then examples, or routine business uncertainty into risks.',
'open_questions':'Keep only important unresolved future-facing issues whose answer is not provided ANYWHERE later in the transcript. Reject training/demo questions, routine clarification, rhetorical talk, and duplicates. An owner is NOT necessary.'}

def global_prompt(category, additions, baseline, transcript):
    entries=[{'index':i,'claim':_text(category,item),'evidence':item.get('evidence','') if isinstance(item,dict) else ''} for i,item in enumerate(additions)]
    return ('You are a SECOND, independent, highly conservative final auditor. You must examine the ENTIRE meeting chronologically, especially everything AFTER each candidate evidence. '
            'Your job is to VETO false positive memories, not to maximize recall. Never create new claims. Only keep candidates that are truly durable and distinct. '
            'CATEGORY RULE: '+CATEGORY_RULES[category]+'\n'
            'Every kept index must have evidence genuinely supporting that candidate and remain valid at meeting end. '
            'If candidate evidence comes from a hypothetical/demo/example, reject. If the issue was answered anywhere later, reject. '
            'If a risk consequence is speculative or a mere product setup dependency, reject. '
            'If multiple candidate indices express one underlying fact, keep at most one. '
            'Output JSON keep_indices and reasons for each rejected candidate. Uncertain cases: reject.\n'
            'CATEGORY: '+category+'\nBASELINE: '+json.dumps([_text(category,x) for x in baseline],ensure_ascii=False)+'\n'
            'CANDIDATES: '+json.dumps(entries,ensure_ascii=False)+'\nFULL MEETING TRANSCRIPT:\n'+transcript)

def global_veto(baseline,proposed,transcript,*,reviewer=None,max_chars=95000):
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    enriched=copy.deepcopy(baseline)
    diag={'accepted':[],'rejected':[],'errors':[],'skipped_categories':[]}
    if len(transcript)>max_chars:
        diag['errors'].append('Full transcript exceeds maximum context; fail closed, no additions')
        return enriched,diag
    for cat in CATEGORIES:
        base=list(baseline.get(cat,[]))
        incoming=list(proposed.get(cat,[]))
        # v12.29 result is baseline + additions; preserve all baseline items untouched.
        extras=[]
        for item in incoming:
            if not _is_duplicate(cat,item,base): extras.append(item)
        if not extras:continue
        try:
            result=json.loads(reviewer(global_prompt(cat,extras,base,transcript),SCHEMA))
            keep=result.get('keep_indices',[])
            if not isinstance(keep,list) or len(keep)!=len(set(str(x) for x in keep)) or any(type(i) is not int or i<0 or i>=len(extras) for i in keep):
                raise ValueError('invalid keep_indices')
        except Exception as exc:
            diag['errors'].append({'category':cat,'error':str(exc)[:200]})
            diag['rejected'] += [{'category':cat,'claim':_text(cat,x),'reason':'global_review_failed_closed'} for x in extras]
            continue
        enriched.setdefault(cat,copy.deepcopy(base))
        for i,item in enumerate(extras):
            if i in keep and not _is_duplicate(cat,item,enriched[cat]):
                enriched[cat].append(copy.deepcopy(item));diag['accepted'].append({'category':cat,'claim':_text(cat,item)})
            else:
                diag['rejected'].append({'category':cat,'claim':_text(cat,item),'reason':'global_veto'})
    return enriched,diag


COUNTER_SCHEMA={"type":"object","properties":{
 "accept":{"type":"boolean"},
 "support_quote":{"type":"string"},
 "counterevidence_quote":{"type":"string"},
 "reason":{"type":"string"}},
 "required":["accept","support_quote","counterevidence_quote","reason"],"additionalProperties":False}

def adversarial_prompt(category, item, baseline, transcript):
    """Ask a second reviewer to disprove rather than merely reapprove a candidate."""
    return ("Act as a skeptical meeting-memory auditor. Independently try to DISPROVE this proposed addition, "
      "using the entire meeting (including later dialogue). Do not defer to the previous reviewer. "
      "A true statement is not necessarily a durable meeting memory. "
      "Reject anything discussed as a walkthrough, a hypothetical/example, a previously completed action, "
      "a product behavior, an answered question, a possible but not articulated risk, or a near-duplicate "
      "of baseline. Do not infer future obligations or decisions from descriptions. "
      "For a question, it must be a genuine, material unresolved business issue at the END; "
      "no owner is needed. For risks, a concrete adverse consequence must be described in the meeting "
      "as a live concern, not inferred from a condition. For commitments, a specific future task and "
      "reliable actor must be established. For decisions, actual agreement IN THIS MEETING is mandatory. "
      "If you cannot find a specific supporting quote or if you have material uncertainty, reject. "
      "Set accept true only with a continuous verbatim support_quote from the transcript (20+ chars). "
      "Provide counterevidence_quote for any passage that defeats or qualifies the claim, or empty string. "
      "If no disconfirming excerpt exists, use empty string. Return JSON only.\n"
      "CATEGORY: "+category+"\nRULE: "+CATEGORY_RULES[category]+"\nCANDIDATE: "+json.dumps(item,ensure_ascii=False)+
      "\nBASELINE: "+json.dumps([_text(category,x) for x in baseline],ensure_ascii=False)+
      "\nCHRONOLOGICAL TRANSCRIPT:\n"+transcript)

def adversarial_audit(baseline, proposed, transcript, *, reviewer=None, max_chars=95000):
    """Baseline immutable; accept only separately grounded, re-reviewed additions."""
    from tools.benchmark.llm_shadow_compare import anchored
    enriched=copy.deepcopy(baseline)
    diag={'accepted':[],'rejected':[],'errors':[]}
    if len(transcript)>max_chars:
        diag['errors'].append('Transcript exceeds guarded context length; no additions')
        return enriched,diag
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    for cat in CATEGORIES:
        incoming=proposed.get(cat,[])
        if not incoming:continue
        existing=enriched.setdefault(cat,copy.deepcopy(baseline.get(cat,[])))
        for item in incoming:
            if _is_duplicate(cat,item,existing):continue
            claim=_text(cat,item)
            try:
                raw=reviewer(adversarial_prompt(cat,item,existing,transcript),COUNTER_SCHEMA)
                result=json.loads(raw) if isinstance(raw,str) else raw
                quote=result.get('support_quote','')
                if not isinstance(quote,str) or not anchored(quote,transcript) or len(quote.strip())<20:
                    reason='insufficient_verbatim_support'
                elif result.get('accept') is not True:
                    reason='independent_veto'
                elif result.get('counterevidence_quote'):
                    reason='unresolved_counterevidence'
                else:reason=None
                if reason:
                    diag['rejected'].append({'category':cat,'claim':claim,'reason':reason,'reviewer_reason':result.get('reason','')})
                    continue
                if isinstance(item,dict):
                    item=copy.deepcopy(item);item['evidence']=quote
                if _is_duplicate(cat,item,existing):
                    diag['rejected'].append({'category':cat,'claim':claim,'reason':'duplicate'})
                    continue
                existing.append(copy.deepcopy(item))
                diag['accepted'].append({'category':cat,'claim':claim,'quote':quote})
            except Exception as exc:
                diag['errors'].append({'category':cat,'claim':claim,'error':str(exc)[:200]})
                diag['rejected'].append({'category':cat,'claim':claim,'reason':'review_error_fail_closed'})
    return enriched,diag

def main(argv=None):
    p=argparse.ArgumentParser(description='v12.31 independent adversarial audit comparison')
    p.add_argument('--all',action='store_true');p.add_argument('--cases',nargs='+');p.add_argument('--fresh',action='store_true')
    p.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT);p.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    p.add_argument('--review-budget',type=int,default=12);p.add_argument('--max-contexts',type=int,default=16)
    a=p.parse_args(argv)
    if not(a.all or a.cases):p.error('supply --all or --cases')
    if not 1<=a.review_budget<=100 or not 1<=a.max_contexts<=50:p.error('invalid budgets')
    cases=sorted(x for x in a.case_root.iterdir() if x.is_dir() and (a.all or x.name in a.cases)) if a.case_root.exists() else []
    if not cases:p.error('no private cases found')
    target=a.run_root/'adversarial_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');target.mkdir(parents=True,exist_ok=True)
    rows=['# v12.31 Independent Adversarial Audit Shadow Comparison','','| Case | Category | Baseline P/R | v12.30 P/R | v12.31 P/R |','|---|---|---|---|---|']
    failures=0
    for case in cases:
        try:
            print(f'[{case.name}] starting',flush=True)
            path=Path(run_case(case,a.run_root)['output_dir']) if a.fresh else _latest_run(case.name,a.run_root)
            if path is None:raise FileNotFoundError('No baseline run found')
            baseline=json.loads((path/'actual_memory.json').read_text())
            transcript=(case/'meeting_transcript_cleaned.md').read_text()
            metadata=json.loads((case/'meeting_metadata.json').read_text())
            recovered,recovery_diag=recover(baseline,transcript,metadata.get('participants',[]),max_contexts=a.max_contexts)
            local,local_diag=durability_filter(baseline,recovered,transcript,review_budget=a.review_budget)
            global_result,global_diag=global_veto(baseline,local,transcript)
            adversarial_result,adversarial_diag=adversarial_audit(baseline,global_result,transcript)
            # Write predictions before accessing gold.
            out=target/case.name;out.mkdir()
            for name,obj in [('baseline_memory.json',baseline),('local_memory.json',local),('shadow_memory.json',adversarial_result),('global_memory.json',global_result),('diagnostics.json',{'recovery':recovery_diag,'local_review':local_diag,'global_review':global_diag,'adversarial_review':adversarial_diag,'baseline_dir':str(path)})]:
                (out/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False))
            gold=json.loads((case/'expected_memory.json').read_text())
            results={'baseline':score_memory(baseline,gold),'local':score_memory(local,gold),'global':score_memory(global_result,gold),'adversarial':score_memory(adversarial_result,gold)}
            (out/'comparison.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
            for cat in CATEGORIES:
                vals=[results[k]['categories'][cat] for k in ('baseline','global','adversarial')]
                scores=['%.2f/%.2f'%(x['precision'],x['recall']) for x in vals]
                rows.append('| '+case.name+' | '+cat+' | '+' | '.join(scores)+' |')
            print(f"[{case.name}] global={'PASS' if results['adversarial']['passed'] else 'FAIL'} accepted={len(adversarial_diag['accepted'])} errors={len(adversarial_diag['errors'])}",flush=True)
        except Exception as exc:
            failures+=1;rows.append(f'| {case.name} | ERROR {type(exc).__name__}: {exc} | | | |');print(f'[{case.name}] ERROR: {exc}',file=sys.stderr)
    (target/'comparison.md').write_text('\n'.join(rows)+'\n')
    print('Report:',target/'comparison.md')
    return 1 if failures else 0
if __name__=='__main__':raise SystemExit(main())
