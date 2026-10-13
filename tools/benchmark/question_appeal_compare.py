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

# A real quote can be about a different nearby question. Require shared topic
# terms before allowing the LLM's appeal decision to publish a memory.
_QUESTION_STOPWORDS = frozenset("a an and are as at be by can could did do does for from have how in is it of on or our should that the their there these they this to under we what when where which who why will with would you your exact specific process question".split())

def question_quote_matches_claim(claim, quote):
    import re
    def key_terms(text):
        return {x for x in re.findall(r"[a-z0-9]+", text.casefold()) if len(x)>=4 and x not in _QUESTION_STOPWORDS}
    key = key_terms(claim)
    return bool(key and key.intersection(key_terms(quote)))

# v12.32: isolated question appeal, after the adversarial audit. This cannot publish
# new commitments, decisions, risks, or any baseline edits.
QUESTION_APPEAL_SCHEMA={"type":"object","properties":{
    "explicit_question_quote":{"type":"string"},
    "later_answer_quote":{"type":"string"},
    "demo_or_hypothetical":{"type":"boolean"},
    "business_issue":{"type":"boolean"},
    "explanation":{"type":"string"}},
    "required":["explicit_question_quote","later_answer_quote","demo_or_hypothetical","business_issue","explanation"],
    "additionalProperties":False}

def question_appeal(baseline, globally_approved, adversarial_result, transcript, *, reviewer=None, locally_approved=None, uncertainty_evidence=None):
    """Reconsider only questions the first global reviewer accepted but adversarial reviewer vetoed.

    A second LLM must cite an actual question and any later answer. Its finding does
    not override evidence anchoring, demonstrations, or the baseline. Shadow only.
    """
    from tools.benchmark.llm_shadow_compare import anchored
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    output=copy.deepcopy(adversarial_result)
    diag={'accepted':[],'rejected':[],'errors':[]}
    baseline_q=baseline.get('open_questions',[])
    # Reconsider high-quality locally reviewed questions vetoed at either later stage.
    # The appeal still requires independent verbatim evidence and a whole-meeting answer check.
    pool = list(globally_approved.get('open_questions', []))
    for candidate in (locally_approved or {}).get('open_questions', []):
        if not _is_duplicate('open_questions', candidate, pool):
            pool.append(candidate)
    uncertainty_evidence = uncertainty_evidence or {}
    for question in pool:
        if _is_duplicate('open_questions',question,output.get('open_questions',[])):
            continue
        claim=_text('open_questions',question)
        supplied_quote = uncertainty_evidence.get(claim, '')
        if supplied_quote:
            # Only use a quote that independently passed the discovery checks.
            if (not isinstance(supplied_quote, str) or len(supplied_quote.strip()) < 20
                    or not anchored(supplied_quote, transcript)
                    or not question_quote_matches_claim(claim, supplied_quote)):
                diag['rejected'].append({'question':claim,'reason':'invalid_discovery_evidence'})
                continue
        prompt=("Independently audit an unresolved BUSINESS question or UNCERTAINTY. The prior audit vetoed it, "
                "but the meeting-level review accepted it. You are NOT deciding whether it was assigned "
                "to an owner. An uncertainty can be expressed as a statement such as 'we do not yet "
                "know the allocation' rather than an interrogative. Extract one VERBATIM contiguous "
                "quote (at least 20 characters) supporting the actual unknown; do NOT require a "
                "literal question mark. If DISCOVERY EVIDENCE is supplied, evaluate its exact wording "
                "instead of rejecting it just because it is not a grammatical question. "
                "Separately search the COMPLETE later "
                "transcript for an answer; if answered, cite the exact verbatim answer in "
                "later_answer_quote. If no answer appears, return empty string. Mark "
                "demo_or_hypothetical=true for product walkthroughs, training examples, and what-if "
                "questions that don't concern a real pending business choice. business_issue=true "
                "only if this remains consequential beyond this meeting. Do not invent a quote. "
                "Return only schema-valid JSON.\nCANDIDATE: "+claim+
                "\nDISCOVERY EVIDENCE (independently verified verbatim, if present): "+supplied_quote+
                "\nBASELINE QUESTIONS: "+json.dumps(baseline_q,ensure_ascii=False)+
                "\nCOMPLETE TRANSCRIPT:\n"+transcript)
        try:
            raw=reviewer(prompt,QUESTION_APPEAL_SCHEMA)
            v=json.loads(raw) if isinstance(raw,str) else raw
            quote=v.get('explicit_question_quote','')
            # Discovery already established a verbatim, topically aligned quote.
            # Keep that source evidence authoritative for *support*, but the
            # independent reviewer still has veto power over answer/durability.
            if supplied_quote:
                quote = supplied_quote
            answer=v.get('later_answer_quote','')
            if not isinstance(quote,str) or len(quote.strip())<20 or not anchored(quote,transcript):
                reason='missing_exact_question_evidence'
            elif not question_quote_matches_claim(claim, quote):
                reason='question_evidence_mismatch'
            elif not isinstance(answer,str) or (answer and not anchored(answer,transcript)):
                reason='unverifiable_answer_quote'
            elif answer:
                reason='answered_in_meeting'
            elif v.get('demo_or_hypothetical') is not False:
                reason='demo_or_hypothetical'
            elif v.get('business_issue') is not True:
                reason='not_durable_business_issue'
            elif _is_duplicate('open_questions',question,output.get('open_questions',[])):
                reason='duplicate'
            else:
                reason=None
            if reason:
                diag['rejected'].append({'question':claim,'reason':reason,'explanation':str(v.get('explanation',''))[:500]})
            else:
                output.setdefault('open_questions',[]).append(copy.deepcopy(question))
                diag['accepted'].append({'question':claim,'support_quote':quote,'explanation':str(v.get('explanation',''))[:500]})
        except Exception as exc:
            diag['errors'].append({'question':claim,'error':str(exc)[:200]})
    return output,diag

# v12.39: independent narrow dispute review. The first appeal can confuse an
# ordinary fact gap with an outstanding action-worthy business question, or
# call a real organizational issue a demo. Do not trust that binary verdict.
DISPUTE_SCHEMA={"type":"object","properties":{
    "durable_unresolved":{"type":"boolean"},
    "resolved_later":{"type":"boolean"},
    "demonstration_or_example":{"type":"boolean"},
    "specific_pending_business_consequence":{"type":"boolean"},
    "support_quote":{"type":"string"},
    "explanation":{"type":"string"}},
    "required":["durable_unresolved","resolved_later","demonstration_or_example",
                "specific_pending_business_consequence","support_quote","explanation"],
    "additionalProperties":False}

def disputed_uncertainty_review(baseline, current, discovery, first_appeal_diag,
                                transcript, *, reviewer=None):
    """Shadow-only reconsideration: challenge new accepts and demo vetoes.

    This is independent of benchmark gold and never removes baseline memories.
    Both acceptance and reversal require transcript-grounded evidence.
    """
    from tools.benchmark.llm_shadow_compare import anchored
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    output=copy.deepcopy(current)
    diagnostics={'kept':[], 'removed':[], 'rescued':[], 'rejected':[], 'errors':[]}
    baseline_questions=list(baseline.get('open_questions',[]))
    discovered={item['question']:item['evidence_quote'] for item in discovery.get('proposed',[])}
    appealed={item['question'] for item in first_appeal_diag.get('accepted',[])}
    rejected_demo={item['question'] for item in first_appeal_diag.get('rejected',[])
                   if item.get('reason')=='demo_or_hypothetical'}
    for claim in sorted(appealed|rejected_demo):
        if any(_is_duplicate('open_questions', claim,[b]) for b in baseline_questions):
            continue
        proof=discovered.get(claim,'')
        if not (proof and len(proof)>=20 and anchored(proof,transcript)
                and question_quote_matches_claim(claim,proof)):
            diagnostics['rejected'].append({'question':claim,'reason':'discovery_evidence_missing'})
            if claim in appealed:
                output['open_questions']=[x for x in output.get('open_questions',[]) if x!=claim]
            continue
        prompt=("You are a SKEPTICAL second reviewer of an unresolved business question. "
                "A factual information gap is NOT automatically durable meeting memory. "
                "Require a specific consequential issue that remains pending after this meeting, "
                "rather than an incidental cost mention, example, training demonstration, or "
                "routine request for clarification. A strategic allocation or accountability "
                "uncertainty is NOT a product demonstration merely because it is conditional. "
                "Read the complete transcript. Find any later answer or explicit resolution. "
                "Set durable_unresolved true ONLY if the issue is still pending. "
                "Set specific_pending_business_consequence true ONLY when the transcript "
                "shows why the unknown matters to decisions, commitments, or future planning. "
                "Quote EXACT verbatim evidence; never paraphrase the quote. "
                "Return JSON using the schema.\nCANDIDATE: "+claim+
                "\nDISCOVERY EVIDENCE: "+proof+
                "\nCOMPLETE TRANSCRIPT:\n"+transcript)
        try:
            raw=reviewer(prompt,DISPUTE_SCHEMA)
            v=json.loads(raw) if isinstance(raw,str) else raw
            cited=v.get('support_quote','')
            accept=(v.get('durable_unresolved') is True
                    and v.get('resolved_later') is False
                    and v.get('demonstration_or_example') is False
                    and v.get('specific_pending_business_consequence') is True
                    and isinstance(cited,str) and len(cited)>=20
                    and anchored(cited,transcript)
                    and question_quote_matches_claim(claim,cited))
            if accept:
                if claim not in appealed and not _is_duplicate('open_questions',claim,output.get('open_questions',[])):
                    output.setdefault('open_questions',[]).append(claim)
                    diagnostics['rescued'].append({'question':claim,'quote':cited})
                else:
                    diagnostics['kept'].append({'question':claim,'quote':cited})
            else:
                if claim in appealed:
                    output['open_questions']=[x for x in output.get('open_questions',[]) if x!=claim]
                    diagnostics['removed'].append({'question':claim,'reason':'dispute_not_durable',
                                                   'explanation':str(v.get('explanation',''))[:300]})
                else:
                    diagnostics['rejected'].append({'question':claim,'reason':'dispute_not_durable'})
        except Exception as exc:
            diagnostics['errors'].append({'question':claim,'error':str(exc)[:180]})
            # Fail closed for *new* memories; never modify the authoritative baseline.
            if claim in appealed:
                output['open_questions']=[x for x in output.get('open_questions',[]) if x!=claim]
    return output,diagnostics

# v12.36: deterministic retrieval of uncertainty-bearing transcript turns.
# Avoid forcing one model call to identify small but consequential uncertainties
# from a long transcript. Candidate formulation and the final independent
# appeal continue to use their existing fail-closed evidence checks.
_UNCERTAINTY_CUES = (
    'don\'t know', 'do not know', 'not sure', 'unclear', 'not clear',
    'trying to get', 'trying to find', 'need to understand', 'need to validate', 'tbd',
    'how much', 'who owns', 'who is responsible', 'who\'s signing',
    'haven\'t decided', 'has not been decided', 'still unknown',
    'no idea', 'figure that', 'what happens', 'not yet determined',
)

def retrieve_uncertainty_passages(transcript, *, max_passages=24, max_chars=16000):
    """Find transcript turns likely to state unresolved facts, in document order.

    This is recall-oriented retrieval only. It neither generates nor approves
    a memory, and its output is never published as an authoritative fact.
    """
    import re
    if not isinstance(transcript, str) or not transcript.strip():
        return []
    # Split on time-coded turns; retain speaker and timestamp in snippets.
    sections=re.split(r'(?=\[\d{2}:\d{2}(?::\d{2})?\]\s*\*\*)',transcript)
    passages=[]
    for index, turn in enumerate(sections):
        text=turn.strip()
        if not text or not any(cue in text.casefold() for cue in _UNCERTAINTY_CUES):
            continue
        # The subject of an uncertainty often appears in the preceding turn:
        # "search funding ..." followed by "how much of that ...".
        # Preserve neighboring context for candidate *formulation*, not proof.
        prior = sections[index - 1].strip()[-450:] if index else ''
        following = sections[index + 1].strip()[:200] if index + 1 < len(sections) else ''
        excerpt = ((prior + '\n') if prior else '') + text[:950]
        if following:
            excerpt += '\n' + following
        passages.append(excerpt)
    # Spread the quota across the timeline instead of favoring only the start.
    if len(passages)>max_passages:
        indices=[round(i*(len(passages)-1)/(max_passages-1)) for i in range(max_passages)]
        passages=[passages[i] for i in indices]
    out=[];length=0
    for passage in passages:
        if length+len(passage)>max_chars:break
        out.append(passage);length+=len(passage)
    return out

# v12.35: recover explicit unresolved uncertainty, not merely question marks.
# Candidates are created independently of gold targets and must pass the same
# final evidence-aligned appeal. This path never changes baseline memory.
UNCERTAINTY_SCHEMA={"type":"object","properties":{
    "questions":{"type":"array","items":{"type":"object","properties":{
        "question":{"type":"string"},"evidence_quote":{"type":"string"}},
        "required":["question","evidence_quote"],"additionalProperties":False}}},
    "required":["questions"],"additionalProperties":False}

def discover_uncertainty_questions(transcript, *, reviewer=None, max_chars=95000, max_items=8):
    """Conservatively turn explicit *unresolved statements* into question candidates.

    Does not use expected benchmark memory or specific business keywords. The
    evidence quote must be verbatim and topically aligned. Every proposed item
    is still independently audited by question_appeal before publication.
    """
    from tools.benchmark.llm_shadow_compare import anchored
    diagnostics={'proposed':[],'rejected':[],'errors':[]}
    if not isinstance(transcript,str) or len(transcript)>max_chars:
        diagnostics['errors'].append('transcript_missing_or_exceeds_limit')
        return [],diagnostics
    if reviewer is None:
        from ai import ask_llm
        reviewer=lambda prompt,schema:ask_llm(prompt,response_format=schema)
    passages=retrieve_uncertainty_passages(transcript)
    diagnostics['retrieved_passages']=len(passages)
    if not passages:
        return [], diagnostics
    retrieval_text='\n\n--- NEXT TRANSCRIPT TURN ---\n\n'.join(passages)
    prompt=("Find at most 8 important BUSINESS uncertainties explicitly stated "
        "in the following full meeting transcript. Focus on statements of missing "
        "information, unknown amounts, undecided ownership, unconfirmed plans, "
        "or details someone is still trying to obtain—even if not phrased as a "
        "question. Resolve pronouns like 'that' from surrounding context. "
        "Name both the subject (e.g. the funding being discussed) and the "
        "specific unknown (e.g. allocation to a spending category). "
        "Do not convert an unknown amount or allocation into a question "
        "about benchmarking methodology. Do NOT include rhetorical or demo/training questions, "
        "ordinary uncertainty about conversation, hypothetical concerns, or "
        "anything answered later in the transcript. Express each as a short, "
        "self-contained question with NO invented details. Every item MUST "
        "include a verbatim contiguous supporting quote of 20+ characters "
        "that actually states its uncertainty. Do not over-generate; if none "
        "qualify, use an empty list. Return schema-valid JSON.\n"
        "RETRIEVED CHRONOLOGICAL TRANSCRIPT TURNS (NOT THE WHOLE MEETING):\n"+retrieval_text)
    try:
        raw=reviewer(prompt,UNCERTAINTY_SCHEMA)
        value=json.loads(raw) if isinstance(raw,str) else raw
        candidates=value.get('questions')
        if not isinstance(candidates,list):raise ValueError('invalid_questions')
        for entry in candidates[:max_items]:
            if not isinstance(entry,dict):continue
            claim=entry.get('question','');quote=entry.get('evidence_quote','')
            if not isinstance(claim,str) or not isinstance(quote,str) or len(quote.strip())<20 or not anchored(quote,transcript):
                diagnostics['rejected'].append({'question':str(claim)[:180],'reason':'no_exact_uncertainty_evidence'})
            elif not question_quote_matches_claim(claim,quote):
                diagnostics['rejected'].append({'question':claim,'reason':'question_evidence_mismatch'})
            else:
                diagnostics['proposed'].append({'question':claim,'evidence_quote':quote})
    except Exception as exc:
        diagnostics['errors'].append(str(exc)[:250])
    return [x['question'] for x in diagnostics['proposed']],diagnostics

def main(argv=None):
    p=argparse.ArgumentParser(description='v12.39 disputed uncertainty review comparison')
    p.add_argument('--all',action='store_true');p.add_argument('--cases',nargs='+');p.add_argument('--fresh',action='store_true')
    p.add_argument('--case-root',type=Path,default=DEFAULT_CASE_ROOT);p.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT)
    p.add_argument('--review-budget',type=int,default=12);p.add_argument('--max-contexts',type=int,default=16)
    a=p.parse_args(argv)
    if not(a.all or a.cases):p.error('supply --all or --cases')
    if not 1<=a.review_budget<=100 or not 1<=a.max_contexts<=50:p.error('invalid budgets')
    cases=sorted(x for x in a.case_root.iterdir() if x.is_dir() and (a.all or x.name in a.cases)) if a.case_root.exists() else []
    if not cases:p.error('no private cases found')
    target=a.run_root/'question_appeal_comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');target.mkdir(parents=True,exist_ok=True)
    rows=['# v12.39 Disputed-Uncertainty Review Shadow Comparison','','| Case | Category | Baseline P/R | v12.34 P/R | v12.39 P/R |','|---|---|---|---|---|']
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
            appeal_result,appeal_diag=question_appeal(baseline,global_result,adversarial_result,transcript,locally_approved=local)
            uncertainty_candidates,uncertainty_diag=discover_uncertainty_questions(transcript)
            uncertainty_pool={'open_questions':uncertainty_candidates}
            evidence_map={item['question']:item['evidence_quote'] for item in uncertainty_diag['proposed']}
            final_result,uncertainty_appeal_diag=question_appeal(
                baseline,uncertainty_pool,appeal_result,transcript,uncertainty_evidence=evidence_map)
            final_result,dispute_diag=disputed_uncertainty_review(
                baseline,final_result,uncertainty_diag,uncertainty_appeal_diag,transcript)
            # Write predictions before accessing gold.
            out=target/case.name;out.mkdir()
            for name,obj in [('baseline_memory.json',baseline),('local_memory.json',local),('shadow_memory.json',final_result),('adversarial_memory.json',adversarial_result),('global_memory.json',global_result),('diagnostics.json',{'recovery':recovery_diag,'local_review':local_diag,'global_review':global_diag,'adversarial_review':adversarial_diag,'question_appeal':appeal_diag,'uncertainty_discovery':uncertainty_diag,'uncertainty_appeal':uncertainty_appeal_diag,'dispute_review':dispute_diag,'baseline_dir':str(path)})]:
                (out/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False))
            gold=json.loads((case/'expected_memory.json').read_text())
            results={'baseline':score_memory(baseline,gold),'local':score_memory(local,gold),'global':score_memory(global_result,gold),'adversarial':score_memory(adversarial_result,gold),'appeal':score_memory(appeal_result,gold),'uncertainty':score_memory(final_result,gold)}
            (out/'comparison.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
            for cat in CATEGORIES:
                vals=[results[k]['categories'][cat] for k in ('baseline','appeal','uncertainty')]
                scores=['%.2f/%.2f'%(x['precision'],x['recall']) for x in vals]
                rows.append('| '+case.name+' | '+cat+' | '+' | '.join(scores)+' |')
            print(f"[{case.name}] appeal={'PASS' if results['uncertainty']['passed'] else 'FAIL'} rescued_questions={len(uncertainty_appeal_diag['accepted'])} errors={len(uncertainty_appeal_diag['errors'])}",flush=True)
        except Exception as exc:
            failures+=1;rows.append(f'| {case.name} | ERROR {type(exc).__name__}: {exc} | | | |');print(f'[{case.name}] ERROR: {exc}',file=sys.stderr)
    (target/'comparison.md').write_text('\n'.join(rows)+'\n')
    print('Report:',target/'comparison.md')
    return 1 if failures else 0
if __name__=='__main__':raise SystemExit(main())
