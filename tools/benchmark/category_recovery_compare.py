#!/usr/bin/env python3
"""v12.28 experimental category-aware recovery; NEVER changes stored meeting memory.

Read baseline trace, identify transcript evidence anchors without reading gold labels,
ask the local model to propose category-specific claims, then independently verify
claims with category-aware review prompts. Writes only to ignored benchmark_runs/.
"""
from __future__ import annotations
import argparse, copy, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.benchmark.memory_benchmark import DEFAULT_CASE_ROOT, DEFAULT_RUN_ROOT, CATEGORY_CONFIG, run_case, score_memory
from tools.benchmark.shadow_compare import _latest_run, norm
from tools.benchmark.llm_shadow_compare import anchored, BAD_OWNERS
from tools.benchmark.enrichment_compare import _is_duplicate, _text, context_excerpt

CATEGORIES=tuple(CATEGORY_CONFIG)
TRIGGERS={
 'commitments':r"\b(?:i(?:'| a)?m going to|i will|i'll|we(?:'| a)?re going to|we will|we'll|i(?:'| a)?ll (?:ask|send|share|update)|i got the feedback|reach out|follow up)\b",
 'decisions':r"\b(?:let's use|we(?:'| a)?re not going to|we will not|don't (?:update|change|introduce)|agreed|decided|we(?:'| a)?ll use|for now)\b",
 'risks':r"\b(?:risk|concern|challenge|capacity|attrition|turnover|headcount|demand|funding|impact|strain|pressure|forecast|not know|uncertain|cannot|can't)\b",
 'open_questions':r"(?:\?|\b(?:tbd|unknown|not sure|don't know|who(?:'s| is)|how much|what (?:is|will)|unresolved|unclear)\b)"
}
# Distinct contracts prevent importing future-work rules into open-question review.
CONTRACTS={
 'commitments':"Require a concrete FUTURE action that the speaker explicitly undertakes or accepts. Not a suggestion, already-completed act, demonstration, or vague helpfulness. Distinguish the speaker channel from a person's identity; provide an owner only with independent identity evidence. If the action is valid but identity uncertain, return valid with empty owner so it can be held in diagnostics.",
 'decisions':"Require a settled choice agreed to during this meeting, including negative decisions. Do not treat the scheduling of a meeting, product description, illustrative scenario, or unaccepted proposal as a decision.",
 'risks':"Require a concrete source-grounded exposure and a possible consequence (which may be conditional); an outcome does NOT need to have occurred. Reject generic speculative concerns or consequences not supported by the source excerpt.",
 'open_questions':"Require an important unresolved issue or explicit uncertainty. The question need not have an owner, assignee, acceptance, or answer. Check whether the provided later context resolves it. Reject rhetorical/training/example questions or ones answered in this excerpt."
}
PROPOSE_SCHEMA={'type':'object','properties':{'items':{'type':'array','items':{'type':'object','properties':{
 'category':{'type':'string','enum':list(CATEGORIES)+['none']},'claim':{'type':'string'},'evidence':{'type':'string'},'owner':{'type':'string'}},
 'required':['category','claim','evidence','owner'],'additionalProperties':False}}},'required':['items'],'additionalProperties':False}
REVIEW_SCHEMA={'type':'object','properties':{'valid':{'type':'boolean'},'category':{'type':'string','enum':list(CATEGORIES)+['none']},
 'reason':{'type':'string'},'evidence':{'type':'string'},'owner':{'type':'string'}},
 'required':['valid','category','reason','evidence','owner'],'additionalProperties':False}

def transcript_chunks(transcript, max_chars=1700):
    """Group timestamped turns, keeping long turns intact across neighboring context."""
    parts=re.split(r'(?=\[\d\d:\d\d(?::\d\d)?\]\s*\*\*)',transcript)
    chunks=[];pending=''
    for part in parts:
        if not part.strip():continue
        if len(pending)+len(part)>max_chars and pending:
            chunks.append(pending);pending=''
        if len(part)>max_chars:
            for i in range(0,len(part),max_chars):
                if pending:chunks.append(pending);pending=''
                chunks.append(part[i:i+max_chars])
        else:pending+=part
    if pending:chunks.append(pending)
    return chunks

def select_contexts(transcript,category, *, max_contexts=16):
    chunks=transcript_chunks(transcript)
    rx=re.compile(TRIGGERS[category],re.I)
    rated=[]
    for i,chunk in enumerate(chunks):
        hits=len(rx.findall(chunk))
        if not hits:continue
        excerpt=(chunks[i-1][-380:] if i else '')+'\n'+chunk+'\n'+(chunks[i+1][:380] if i+1<len(chunks) else '')
        rated.append((hits,i,excerpt))
    # Prefer breadth over a single noisy turn and keep chronological ordering.
    chosen=sorted(sorted(rated,key=lambda r:(-r[0],r[1]))[:max_contexts],key=lambda r:r[1])
    return [{'chunk':i,'source':ex[:2700]} for _,i,ex in chosen]

def proposed_prompt(category,contexts,baseline):
    return ('Extract only durable '+category+' candidates from provided SOURCE excerpts. '+CONTRACTS[category]+
        ' Do not produce entries already covered in BASELINE. Produce <= 8 items. Each evidence must be '
        'a continuous exact quotation from SOURCE (at least 20 characters). Never use baseline as evidence. '
        'No real person may be inferred from Remote or Mic. Return JSON per schema. '
        '\nBASELINE: '+json.dumps([_text(category,x) for x in baseline],ensure_ascii=False)+
        '\nSOURCE: '+json.dumps(contexts,ensure_ascii=False))

def review_prompt(category,candidate,context,participants):
    return ('Independently verify ONE proposed durable meeting memory. Apply ONLY this category contract: '+
        CONTRACTS[category]+' The claim may paraphrase dialogue but EVERY material claim must be supported. '
        'Evidence output MUST be a verbatim continuous substring of SOURCE of >= 20 characters. '
        'Do not rely on the initial model judgment. Classify wrong categories as none. '
        'Use actual person names only if source proves speaker identity; otherwise empty owner. '
        '\nPARTICIPANTS (existence alone does not establish speaker identity): '+json.dumps(participants,ensure_ascii=False)+
        '\nCANDIDATE: '+json.dumps(candidate,ensure_ascii=False)+'\nSOURCE: '+context)

def recover(baseline,transcript,participants=None, *, llm=None,max_contexts=16):
    if llm is None:
        from ai import ask_llm
        llm=lambda p,s:ask_llm(p,response_format=s)
    result=copy.deepcopy(baseline)
    diagnostics={'proposed':[],'accepted':[],'rejected':[],'uncertain_ownership':[],'errors':[],'categories':{}}
    # Verifying presence in participant metadata is not sufficient for speaker attribution.
    names={norm(p.get('name','')).casefold():norm(p.get('name','')) for p in (participants or []) if isinstance(p,dict)}
    for cat in CATEGORIES:
        result.setdefault(cat,[])
        contexts=select_contexts(transcript,cat,max_contexts=max_contexts)
        diagnostics['categories'][cat]={'contexts':len(contexts),'candidates':0,'accepted':0}
        if not contexts:continue
        # Bounded groups so context does not overwhelm a smaller local model.
        for idx in range(0,len(contexts),4):
            group=contexts[idx:idx+4]
            try:
                response=json.loads(llm(proposed_prompt(cat,group,result[cat]),PROPOSE_SCHEMA))
                items=response.get('items',[])
                if not isinstance(items,list):raise ValueError('invalid items')
            except Exception as exc:
                diagnostics['errors'].append({'category':cat,'stage':'propose','message':str(exc)[:200]});continue
            source='\n'.join(g['source'] for g in group)
            for item in items[:8]:
                if not isinstance(item,dict) or item.get('category')!=cat:continue
                claim=norm(item.get('claim',''));quote=norm(item.get('evidence',''))
                diagnostics['categories'][cat]['candidates']+=1
                diagnostics['proposed'].append({'category':cat,'claim':claim})
                if not claim or not anchored(quote,source) or not anchored(quote,transcript):
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'unanchored proposed evidence'});continue
                key=CATEGORY_CONFIG[cat]['text_key']
                candidate={key:claim,'evidence':quote}
                if _is_duplicate(cat,candidate,result[cat]):
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'duplicate'});continue
                context=context_excerpt(transcript,quote,radius=950)
                if not context:
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'no source context'});continue
                try:
                    verdict=json.loads(llm(review_prompt(cat,item,context,participants or []),REVIEW_SCHEMA))
                except Exception as exc:
                    diagnostics['errors'].append({'category':cat,'stage':'review','message':str(exc)[:200]});continue
                reason=norm(verdict.get('reason',''));review_quote=norm(verdict.get('evidence',''))
                if verdict.get('valid') is not True or verdict.get('category')!=cat:
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'review: '+reason});continue
                if not anchored(review_quote,context) or not anchored(review_quote,transcript):
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'unanchored review evidence'});continue
                candidate['evidence']=review_quote
                if cat=='commitments':
                    owner=norm(verdict.get('owner',''))
                    if owner.casefold() in BAD_OWNERS or owner.casefold() not in names:
                        diagnostics['uncertain_ownership'].append({'claim':claim,'evidence':review_quote,'owner_claim':owner})
                        continue
                    # Never trust metadata alone as proof of speaker identity; reviewer must cite context.
                    if owner.casefold() not in norm(context).casefold():
                        diagnostics['uncertain_ownership'].append({'claim':claim,'evidence':review_quote,'owner_claim':owner,'reason':'name absent from context'})
                        continue
                    candidate.update({'owner':names[owner.casefold()],'action':claim,'status':'open'})
                if _is_duplicate(cat,candidate,result[cat]):
                    diagnostics['rejected'].append({'category':cat,'claim':claim,'reason':'post-review duplicate'});continue
                result[cat].append(candidate)
                diagnostics['accepted'].append({'category':cat,'claim':claim,'evidence':review_quote})
                diagnostics['categories'][cat]['accepted']+=1
    return result,diagnostics

def main(argv=None):
    ap=argparse.ArgumentParser(description='v12.28 read-only category-specific transcript recovery')
    ap.add_argument('--all',action='store_true');ap.add_argument('--cases',nargs='+')
    ap.add_argument('--fresh',action='store_true');ap.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT)
    ap.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    ap.add_argument('--max-contexts',type=int,default=16)
    a=ap.parse_args(argv)
    if not a.all and not a.cases:ap.error('specify --all or --cases')
    if a.max_contexts<1 or a.max_contexts>50:ap.error('--max-contexts must be 1..50')
    cases=sorted(p for p in a.case_root.iterdir() if p.is_dir() and (a.all or p.name in a.cases)) if a.case_root.exists() else []
    if not cases:ap.error('no private benchmark cases found')
    root=a.run_root/'category_recovery_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');root.mkdir(parents=True,exist_ok=True)
    rows=['# v12.28 category-aware transcript recovery','','Shadow only. No authoritative meeting files modified.','','| Case | Category | Baseline correct/expected | Enriched correct/expected | Baseline P/R | Enriched P/R |','|---|---|---|---|---|---|']
    failed=0
    for case in cases:
        try:
            print(f'[{case.name}] loading baseline...',flush=True)
            base=Path(run_case(case,a.run_root)['output_dir']) if a.fresh else _latest_run(case.name,a.run_root)
            if base is None:raise FileNotFoundError('no baseline trace; run existing benchmark or add --fresh')
            baseline=json.loads((base/'actual_memory.json').read_text())
            transcript=(case/'meeting_transcript_cleaned.md').read_text()
            participants=json.loads((case/'meeting_metadata.json').read_text()).get('participants',[])
            started=time.perf_counter()
            enriched,diag=recover(baseline,transcript,participants,max_contexts=a.max_contexts)
            dest=root/case.name;dest.mkdir()
            # Persist prediction PRIOR to reading private expected benchmark gold.
            for filename,obj in [('baseline_memory.json',baseline),('enriched_memory.json',enriched),('diagnostics.json',dict(diag,baseline_path=str(base),elapsed_seconds=round(time.perf_counter()-started,2)))]:
                (dest/filename).write_text(json.dumps(obj,indent=2,ensure_ascii=False))
            gold=json.loads((case/'expected_memory.json').read_text())
            bs=score_memory(baseline,gold);es=score_memory(enriched,gold)
            (dest/'comparison.json').write_text(json.dumps({'baseline':bs,'enriched':es},indent=2))
            for cat in CATEGORIES:
                b,e=bs['categories'][cat],es['categories'][cat]
                rows.append(f"| {case.name} | {cat} | {b['matched_count']}/{b['expected_count']} | {e['matched_count']}/{e['expected_count']} | {b['precision']:.2f}/{b['recall']:.2f} | {e['precision']:.2f}/{e['recall']:.2f} |")
            print(f"[{case.name}] baseline={'PASS' if bs['passed'] else 'FAIL'} enriched={'PASS' if es['passed'] else 'FAIL'} additions={len(diag['accepted'])}",flush=True)
        except Exception as exc:
            failed+=1;rows.append(f'| {case.name} | ERROR | {type(exc).__name__}: {exc} | | | |')
            print(f'[{case.name}] ERROR: {exc}',file=sys.stderr,flush=True)
    (root/'comparison.md').write_text('\n'.join(rows)+'\n')
    print(f'\nReport: {root}/comparison.md')
    return 1 if failed else 0
if __name__=='__main__':raise SystemExit(main())
