#!/usr/bin/env python3
"""v13.2 offline, human-adjudicated review of v13.1 extraction results.

Never invokes a model. All outputs stay beside the supplied private runs.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

CATEGORIES = ('commitment', 'decision', 'risk', 'open_question')
LABELS = ('correct', 'wrong_category', 'not_durable', 'unsupported', 'duplicate')
CHECKS = ('supported', 'unsupported', 'unknown')
GOLD_KEYS = {'commitment':'commitments', 'decision':'decisions', 'risk':'risks', 'open_question':'open_questions'}
FIELDS = ['event_id','category','claim','owner','evidence','window','char_start',
          'label','correct_category','evidence_check','owner_check','status_check',
          'gold_id','notes']
GOLD_FIELDS = ['gold_id','category','description','disposition','notes']


def expected_gold(path: Path):
    if not path or not path.is_file():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    expected = data.get('expected', {})
    out = []
    for category, key in GOLD_KEYS.items():
        for i, target in enumerate(expected.get(key, [])):
            out.append({'gold_id':f'{category}:{i+1:03}', 'category':category,
                        'description':str(target.get('description') or target.get('text') or target),
                        'disposition':'', 'notes':''})
    return out


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def initialize(result_path: Path, output_dir: Path, gold_path: Path|None = None):
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if 'events' not in result or not isinstance(result['events'], list):
        raise ValueError('Input must be a v13 model evaluation result.json')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir/'candidates.csv'
    gold_target = output_dir/'gold_coverage.csv'
    if target.exists() or gold_target.exists():
        raise FileExistsError('Review files already exist; refusing to overwrite human annotations')
    rows = []
    for i, e in enumerate(result['events'], 1):
        rows.append({'event_id':f'E{i:04}','category':e.get('category',''),
                     'claim':e.get('claim',''),'owner':e.get('owner') or '',
                     'evidence':e.get('evidence',''),'window':e.get('window',''),
                     'char_start':e.get('char_start',''), 'label':'',
                     'correct_category':'','evidence_check':'','owner_check':'',
                     'status_check':'','gold_id':'','notes':''})
    write_csv(target,FIELDS,rows)
    gold = expected_gold(gold_path) if gold_path else []
    write_csv(gold_target,GOLD_FIELDS,gold)
    meta = {'schema':'meeting-transcriber-model-review-v13.2', 'source_result':str(result_path.resolve()),
            'model':result.get('model'), 'case':result.get('case'),
            'window_coverage_complete':result.get('window_coverage_complete'),
            'source_event_count':len(rows), 'gold_source':str(gold_path.resolve()) if gold_path else None,
            'note':'Gold entries are review prompts, not necessarily human-validated truth. Mark every gold disposition reviewed_present, reviewed_missed, or exclude.'}
    (output_dir/'review_manifest.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    return len(rows),len(gold)


def score(review_dir: Path):
    manifest=json.loads((review_dir/'review_manifest.json').read_text(encoding='utf-8'))
    events=read_csv(review_dir/'candidates.csv')
    gold=read_csv(review_dir/'gold_coverage.csv')
    failures=[]
    event_ids = [e['event_id'] for e in events]
    if len(set(event_ids)) != len(event_ids): failures.append('Duplicate candidate event IDs')
    gold_ids = {g['gold_id'] for g in gold}
    matches=[]
    for e in events:
        eid=e['event_id']; label=e['label'].strip()
        if not label: failures.append(f'{eid}: missing label'); continue
        if label not in LABELS: failures.append(f'{eid}: invalid label {label!r}')
        for field in ('evidence_check','owner_check','status_check'):
            if e[field] not in CHECKS: failures.append(f'{eid}: {field} must be supported/unsupported/unknown')
        if label=='wrong_category' and e['correct_category'] not in CATEGORIES:
            failures.append(f'{eid}: wrong_category requires correct_category')
        if e['gold_id']:
            if e['gold_id'] not in gold_ids: failures.append(f'{eid}: gold_id not in gold sheet')
            elif label in ('correct','wrong_category'):
                matches.append((eid,e['gold_id']))
            else: failures.append(f'{eid}: invalid gold match for {label}')
    for g in gold:
        if g['disposition'] not in ('reviewed_present','reviewed_missed','exclude'):
            failures.append(f"{g['gold_id']}: mark disposition reviewed_present/reviewed_missed/exclude")
        linked=[eid for eid,gid in matches if gid==g['gold_id']]
        if g['disposition']=='reviewed_present' and not linked:
            failures.append(f"{g['gold_id']}: marked present but no linked correct candidate")
        if g['disposition']=='reviewed_missed' and linked:
            failures.append(f"{g['gold_id']}: marked missed but has linked candidate")
        if len(linked)>1:
            failures.append(f"{g['gold_id']}: multiple candidate matches; mark extras duplicate")
    counts=Counter(e['label'] for e in events)
    accepted=sum(e['label'] in ('correct','wrong_category') for e in events)
    correct=counts['correct']
    relevant_gold=[g for g in gold if g['disposition']!='exclude']
    matched_gold={gid for _,gid in matches}
    true_covered=len({g['gold_id'] for g in relevant_gold if g['gold_id'] in matched_gold})
    ready=not failures and bool(relevant_gold) and bool(manifest.get('window_coverage_complete'))
    output={'schema':'meeting-transcriber-model-review-v13.2','model':manifest.get('model'),
            'case':manifest.get('case'),'complete':ready,'blocking_issues':failures,
            'full_window_coverage':bool(manifest.get('window_coverage_complete')),
            'candidate_labels':dict(counts), 'reviewed_candidates':len(events),
            'gold_reviewed':len(relevant_gold), 'missed_gold':sum(g['disposition']=='reviewed_missed' for g in relevant_gold),
            'owner_checks':dict(Counter(e['owner_check'] for e in events)),
            'evidence_checks':dict(Counter(e['evidence_check'] for e in events)),
            'status_checks':dict(Counter(e['status_check'] for e in events)),
            'note':'All metrics based on human adjudication; only complete results include rates.'}
    if ready:
        output['strict_category_precision']=correct/len(events) if events else None
        output['event_relevance_precision']=accepted/len(events) if events else None
        output['gold_event_recall']=true_covered/len(relevant_gold)
        output['strict_category_gold_recall']=len({e['gold_id'] for e in events if e['label']=='correct' and e['gold_id']})/len(relevant_gold)
    (review_dir/'review_score.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    return output


def main():
    p=argparse.ArgumentParser(description='v13.2 offline human event review; no model calls')
    sub=p.add_subparsers(dest='cmd',required=True)
    init=sub.add_parser('init');init.add_argument('--result',type=Path,required=True)
    init.add_argument('--output',type=Path);init.add_argument('--gold',type=Path)
    sc=sub.add_parser('score');sc.add_argument('--review',type=Path,required=True)
    args=p.parse_args()
    if args.cmd=='init':
        out=args.output or args.result.parent/'v132_review'
        n,g=initialize(args.result,out,args.gold)
        print(f'Created {out}: {n} candidates, {g} gold prompts (human review required)')
    else:
        result=score(args.review)
        print(json.dumps(result,indent=2))
        if not result['complete']: raise SystemExit(2)
if __name__=='__main__': main()
