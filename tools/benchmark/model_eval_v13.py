#!/usr/bin/env python3
"""v13 shadow-only event-discovery harness. No production imports or writes.

Reads private_benchmarks/<case>/meeting_transcript_cleaned.md. Writes only under
benchmark_runs/model_eval_v13. Does not send private data to remote servers.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ('commitment','decision','risk','open_question')
SYSTEM = '''Extract grounded business meeting memory *candidates* from this transcript segment.
Output one valid JSON object {"events": [{"category": "commitment|decision|risk|open_question", "claim": "standalone factual statement or question", "owner": null, "evidence": "exact contiguous verbatim excerpt of the supplied segment", "status": "future|decided|unresolved|other"}]}.
Include potentially durable business actions, agreed decisions, explicitly consequential risks, and unresolved business uncertainties (even when phrased as statements). Exclude examples, hypothetical demonstrations, answered questions, vague intentions, and completed work. Do not invent a person, date, or obligation. If owner is unknown, use null. The exact evidence quote MUST occur in the supplied segment. No markdown. No explanation.'''

def windows(text: str, *, size: int, overlap: int):
    if size < 200 or overlap < 0 or overlap >= size:
        raise ValueError('size must be >=200 and 0 <= overlap < size')
    if not text.strip():
        return []
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind('\n', start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        out.append((start, end, text[start:end]))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return out

def parse_events(raw: str, passage: str):
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        found = re.search(r'\{.*\}', raw, flags=re.S)
        if not found:
            return [], ['invalid_json']
        try:
            payload = json.loads(found.group(0))
        except json.JSONDecodeError:
            return [], ['invalid_json']
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        return [], ['invalid_schema']
    good, errors = [], []
    for i, item in enumerate(payload['events']):
        if not isinstance(item, dict):
            errors.append(f'item_{i}:not_object'); continue
        category = str(item.get('category','')).strip()
        claim = str(item.get('claim','')).strip()
        evidence = str(item.get('evidence','')).strip()
        if category not in CATEGORIES or not claim or not evidence:
            errors.append(f'item_{i}:required_fields'); continue
        if evidence not in passage:
            errors.append(f'item_{i}:not_verbatim'); continue
        owner = item.get('owner')
        if owner is not None and not isinstance(owner, str):
            errors.append(f'item_{i}:invalid_owner'); continue
        good.append({'category':category,'claim':claim,'owner':owner,'evidence':evidence,'status':item.get('status')})
    return good, errors

def ollama_generate(base: str, model: str, prompt: str, *, timeout: int) -> str:
    # Strictly local; reject remote destinations for private transcripts.
    from urllib.parse import urlparse
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Private transcript inference requires local HTTP Ollama endpoint')
    req = urllib.request.Request(base.rstrip('/')+'/api/generate', data=json.dumps({
        'model':model, 'prompt':prompt, 'stream':False, 'format':'json',
        'options':{'temperature':0, 'num_predict':1400}
    }).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
    return str(body.get('response',''))

def candidate_review(events, gold_path: Path):
    """Heuristic review hints only; not precision/recall or automated truth."""
    if not gold_path.is_file():
        return {'gold_available': False, 'note': 'No human-reviewed gold loaded.'}
    gold = json.loads(gold_path.read_text(encoding='utf-8'))
    expected = gold.get('expected', {})
    mapping = {'commitment': 'commitments', 'decision': 'decisions',
               'risk': 'risks', 'open_question': 'open_questions'}
    suggestions = []
    for category, plural in mapping.items():
        for idx, target in enumerate(expected.get(plural, [])):
            terms = [str(x).casefold() for x in target.get('text_contains_any', []) if str(x).strip()]
            matches = [i for i,e in enumerate(events) if e['category'] == category and any(t in e['claim'].casefold() for t in terms)]
            suggestions.append({'category':category,'expected_index':idx,
                                'description':target.get('description',''),
                                'candidate_indices':matches, 'requires_human_review':True})
    return {'gold_available':True,'review_suggestions':suggestions,
            'note':'Keyword suggestions are NOT ground-truth matches, precision, or recall. Human adjudication required.'}

def run_case(case: str, model: str, *, case_root: Path, run_dir: Path, base: str,
             size: int, overlap: int, timeout: int, max_retries: int = 2):
    source = case_root/case/'meeting_transcript_cleaned.md'
    if not source.is_file():
        raise FileNotFoundError(f'Missing private transcript: {source}')
    text = source.read_text(encoding='utf-8')
    parts = windows(text,size=size,overlap=overlap)
    events, errors, records = [], [], []
    target = run_dir/case
    target.mkdir(parents=True,exist_ok=True)
    raw_dir = target/'raw_responses'
    raw_dir.mkdir(exist_ok=True)
    for index,(start,end,passage) in enumerate(parts):
        prompt = SYSTEM+'\n\nTRANSCRIPT SEGMENT:\n'+passage
        attempts = []
        accepted, rejected = [], []
        status = 'failed'
        for attempt in range(max_retries+1):
            t0 = time.monotonic()
            try:
                retry_note = ('\n\nIMPORTANT: Return a syntactically valid JSON object with an events array; '
                              'no markdown or commentary.' if attempt else '')
                raw = ollama_generate(base,model,prompt+retry_note,timeout=timeout)
                error_message = None
            except Exception as exc:
                raw = ''
                error_message = f'{type(exc).__name__}: {exc}'
            duration = round(time.monotonic()-t0,2)
            name = f'window_{index:04d}_attempt_{attempt:02d}.txt'
            (raw_dir/name).write_text(raw,encoding='utf-8')
            if error_message:
                accepted, rejected = [], ['inference_error']
            else:
                accepted, rejected = parse_events(raw,passage)
            attempts.append({'attempt':attempt,'duration_seconds':duration,
                             'raw_file':'raw_responses/'+name,
                             'error':error_message,'parse_rejections':rejected,
                             'accepted_count':len(accepted)})
            # Retry only if the entire response is unusable; never regenerate valid-but-disputed events.
            if not any(x in ('invalid_json','invalid_schema','inference_error') for x in rejected):
                status = 'parsed'
                break
        for item in accepted:
            offset = passage.find(item['evidence'])
            item.update({'window':index,'char_start':start+offset,
                         'char_end':start+offset+len(item['evidence'])})
        events.extend(accepted)
        errors.extend({'window':index,'reason':err} for err in rejected)
        records.append({'window':index,'char_start':start,'char_end':end,
                        'status':status,'attempts':attempts,
                        'accepted_count':len(accepted),'rejection_count':len(rejected)})
        print(f'  window {index+1}/{len(parts)}: {status}, {len(accepted)} grounded, '
              f'{len(rejected)} rejected, {len(attempts)} attempt(s)',flush=True)
    dedup = {(e['category'],e['claim'].casefold(),e['evidence']):e for e in events}
    final_events = list(dedup.values())
    total_time = round(sum(a['duration_seconds'] for r in records for a in r['attempts']),2)
    failures = [r['window'] for r in records if r['status'] != 'parsed']
    result = {'schema':'meeting-transcriber-model-eval-v13.1','case':case,'model':model,
              'window_count':len(parts),'windows_parsed':len(parts)-len(failures),
              'failed_window_indices':failures,'window_coverage_complete':not failures,
              'duration_seconds':total_time,'event_count':len(final_events),
              'rejected_count':len(errors),'events':final_events,'rejections':errors,
              'windows':records,
              'stage_counts':{'model_candidates_grounded':len(events),
                              'deduplicated_candidates':len(final_events),
                              'evidence_rejections':sum('not_verbatim' in x['reason'] for x in errors),
                              'owners_named':sum(bool(e.get('owner')) for e in final_events)},
              'gold_review':candidate_review(final_events,case_root/case/'expected_memory.json'),
              'note':'Extraction only. Grounded quotes are not proof of durable memory. Gold matches need human review.'}
    (target/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser(description='v13.1 shadow-only local model evaluation reliability')
    p.add_argument('--case',action='append',help='private benchmark case directory; repeatable')
    p.add_argument('--all',action='store_true',help='all private cases with cleaned transcripts')
    p.add_argument('--list',action='store_true',help='list eligible private cases only')
    p.add_argument('--model',help='installed Ollama model tag')
    p.add_argument('--base-url',default='http://127.0.0.1:11434')
    p.add_argument('--case-root',type=Path,default=ROOT/'private_benchmarks')
    p.add_argument('--output-root',type=Path,default=ROOT/'benchmark_runs'/'model_eval_v13')
    p.add_argument('--window-chars',type=int,default=10000)
    p.add_argument('--overlap-chars',type=int,default=1000)
    p.add_argument('--timeout',type=int,default=900)
    p.add_argument('--max-retries',type=int,default=2,help='additional attempts for unusable JSON or inference failures')
    args=p.parse_args()
    if args.max_retries < 0 or args.max_retries > 5:
        p.error('--max-retries must be 0..5')
    available=sorted(path.name for path in args.case_root.iterdir() if (path/'meeting_transcript_cleaned.md').is_file()) if args.case_root.is_dir() else []
    if args.list:
        for name in available: print(name)
        return
    if not args.model:
        p.error('--model is required for execution')
    selected=available if args.all else (args.case or [])
    if not selected:
        p.error('select --case NAME or --all; see --list')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    model_folder=re.sub(r'[^a-zA-Z0-9_.-]+','_',args.model)
    out=args.output_root/(stamp+'_'+model_folder)
    out.mkdir(parents=True,exist_ok=False)
    reports=[]
    for case in selected:
        print(f'Case {case} | model {args.model}',flush=True)
        reports.append(run_case(case,args.model,case_root=args.case_root,run_dir=out,base=args.base_url,size=args.window_chars,overlap=args.overlap_chars,timeout=args.timeout,max_retries=args.max_retries))
    summary={'model':args.model,'cases':[{k:r[k] for k in ('case','window_count','windows_parsed','window_coverage_complete','event_count','rejected_count','duration_seconds')} for r in reports], 'schema':'meeting-transcriber-model-eval-v13.1'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(f'Wrote {out}')
if __name__=='__main__':main()
