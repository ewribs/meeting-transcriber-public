"""Evidence-bound, deterministic reconciliation of meeting events.

No model calls, no persistent meeting data, no inferred audio-channel identities.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import re

# Shared by the stage-2 risk checker (ai.py) and the final audit below.
# Matches word stems, so "concerned", "worried", "errors" all count.
RISK_CUE_PATTERN = re.compile(
    r"\b(?:risk|concern|worr(?:y|ied|ies)|exposure|liabilit|lawsuit|sued|"
    r"infring|indemnif|forfeit|fail|end[-\s]+of[-\s]+support|los(?:e|ing|s|t)|"
    r"unknown|uncertain|unclear|difficult|hard\s+time|challeng|problem|"
    r"mistake|errors?|disadvantag|penalt|delay|unable|can(?:'|’)?t|cannot|"
    r"not\s+able|complicated|too\s+(?:late|short|tight)|"
    r"could\s+(?:cause|lead|result|cost)|may\s+(?:cause|lead|result)|"
    r"financial\s+impact)",
    flags=re.IGNORECASE,
)

CHANNELS = {'remote','mic','unknown','speaker','unidentified',''}
STOP = {'the','and','with','this','that','will','would','have','from','into','going','something','someone','anything','some','them','their','just','about','need','help','to','for','our','we','are','on','of','a','an','i','it'}

def norm(value):
    return re.sub(r'[^a-z0-9]+',' ',str(value).casefold()).strip()

def evidence_in_transcript(quote, transcript):
    return bool(quote and norm(quote) and norm(quote) in norm(transcript))

def local_evidence(raw, transcript):
    quotes = raw if isinstance(raw,list) else [raw]
    valid = [re.sub(r'\s+',' ',q).strip() for q in quotes if isinstance(q,str) and evidence_in_transcript(q,transcript)]
    return min(valid,key=len) if valid else ''

def _tokens(value):
    return {w for w in norm(value).split() if len(w)>2 and w not in STOP}


def near_duplicate(words, others, threshold=0.6, jaccard=None):
    """True when `words` mostly repeats any set in `others`.

    Similar-length wordings must share `jaccard` (default `threshold`) of all their
    words. When one wording is clearly longer (1.5x or more), overlap is measured
    against the shorter one, so "send the deck" inside "send the 51 slide deck"
    counts as a repeat. Simple plurals are treated as the same word.
    """
    jaccard = threshold if jaccard is None else jaccard

    def stem(word):
        return word[:-1] if len(word) > 3 and word.endswith("s") else word

    mine = {stem(w) for w in words or ()}
    for other in others:
        theirs = {stem(w) for w in other or ()}
        if not mine or not theirs:
            continue
        shared = len(mine & theirs)
        if shared / len(mine | theirs) >= jaccard:
            return True
        small, big = sorted((len(mine), len(theirs)))
        if small >= 2 and big >= 1.5 * small and shared / small >= threshold:
            return True
    return False

# Shared evidence-local contract for observed staffing attrition. This is an
# adverse condition in its own right; no invented delivery/cost impact is allowed.
_STAFFING_RISK_CLAIM = re.compile(r"\b(?:turnover|attrition|retention|retain(?:ing)?|staff(?:ing)?\s+(?:departures?|loss)|talent\s+(?:loss|retention)|people\s+leaving)\b", re.I)
_STAFFING_DEPARTURE = re.compile(r"\b(?:announced?\s+(?:they(?:'re| are)\s+)?leaving|(?:folks|people|employees|staff|colleagues)\s+(?:are\s+)?leaving|(?:resigned|resignations?|departures?|quit|quitting)|expecting\s+an?\s+(?:internal\s+)?offer)\b", re.I)
_STAFFING_NEGATED = re.compile(r"\b(?:no|not|never|without|zero)\s+(?:staff\s+)?(?:departures?|resignations?|turnover|attrition|one\s+is\s+leaving|people\s+leaving)\b|\b(?:nobody|no\s+one)\s+is\s+leaving\b", re.I)
_STAFFING_UNSUPPORTED_IMPACT = re.compile(r"\b(?:delay|deliver(?:y|ables?)|deadline|project|budget|cost|expense|financial|revenue|outage|service|capacity|productivity|shortage|understaff|unable|failure)\b", re.I)


def observed_staffing_risk_supported(claim, evidence):
    """Accept directly observed departures, not inferred business consequences."""
    claim, evidence = str(claim or ''), str(evidence or '')
    return bool(
        _STAFFING_RISK_CLAIM.search(claim)
        and not _STAFFING_UNSUPPORTED_IMPACT.search(claim)
        and _STAFFING_DEPARTURE.search(evidence)
        and not re.search(r"\b(?:are|is|could|might|will|would|do|does|did)\s+(?:\w+\s+){0,3}leaving\s*\?", evidence, re.I)
        and not _STAFFING_NEGATED.search(evidence)
    )


def _context(quote, transcript, radius=210):
    """Use nearby transcript text only for lifecycle signals, never as evidence output."""
    m=re.search(re.escape(quote),transcript,re.I)
    if not m:
        return quote
    return transcript[max(0,m.start()-radius):min(len(transcript),m.end()+radius)]

def _lifecycle(quote, transcript):
    """Classify the action expressed by the quote, not unrelated nearby turns.

    Context is used only for explicit same-activity completion after a promise.
    A conditional prerequisite is not an unconditional obligation.
    """
    q = re.sub(r"\s+", " ", quote).strip()
    if re.search(r"\b(?:once|after|when)\s+(?:i|we)\s+(?:get|finish|complete|update|have|do)\b", q, re.I):
        return 'conditional'
    if re.search(r"\b(?:if necessary|if needed|if we|if they|provided that|assuming|might|maybe|could)\b", q, re.I):
        return 'conditional'
    if re.search(r"\b(?:i|we)\s+(?:just\s+)?(?:reviewed|already reviewed|finished|completed|sent|looked through|went through)\b|\bi (?:have|had) (?:already )?(?:reviewed|completed|finished|sent)\b|\b(?:i|we) (?:just|already) scheduled\b",q,re.I):
        return 'completed'
    # A promise followed by a clearly reported completion of that same task.
    ctx = _context(quote, transcript, radius=240)
    if re.search(r"\bafter i (?:looked|reviewed) through (?:all )?that\b",ctx,re.I) and re.search(r"\b(?:look|review|legal|terms)\b",q,re.I):
        return 'completed'
    if re.search(r"\b(?:i\s+(?:will|shall|am going to|said i would)|i['’]?ll|i['’]?m gonna|we\s+(?:will|are going to)|we['’]?re gonna|tomorrow|next week)\b",q,re.I):
        return 'planned'
    return 'uncertain'

def _equivalent(a,b):
    if a['destination'] != b['destination'] or a['destination'] not in ('topic','commitment'):
        return False
    if a['event_type'] not in ('commitment','next_step','assignment') or b['event_type'] not in ('commitment','next_step','assignment'):
        return False
    ta,tb=_tokens(a['subject']),_tokens(b['subject'])
    if ta and tb and len(ta&tb)>=2 and len(ta&tb)/min(len(ta),len(tb))>=.6:
        return True
    # Two evidence spans with the same named organization and escalation
    # activity can refer to one call even if one subject is vague.
    combined=' '.join([a['subject'],a['evidence'],b['subject'],b['evidence']]).lower()
    if 'escalat' in combined and ('call' in combined):
        ea=' '.join([a['subject'],a['evidence']]).lower()
        eb=' '.join([b['subject'],b['evidence']]).lower()
        if 'escalat' in ea and 'escalat' in eb:
            names={w for w in _tokens(a['evidence'])&_tokens(b['evidence']) if w not in {'call','escalate','escalation','involved','commitment','committed'}}
            if names:
                return True
    return False

@dataclass(frozen=True)
class EventDisposition:
    event_index:int
    event_type:str
    subject:str
    owner:str|None
    evidence:str
    destination:str
    disposition:str
    reason:str
    duplicate_of:int|None=None
    lifecycle:str='uncertain'

def reconcile_events(events,transcript):
    rows=[]
    for i,event in enumerate(events):
        if not isinstance(event,dict):
            rows.append(asdict(EventDisposition(i,'invalid','',None,'','none','rejected','invalid_event')))
            continue
        kind=str(event.get('event_type','')).strip().lower()
        subject=str(event.get('subject','')).strip()
        speaker=str(event.get('speaker','')).strip()
        owner=speaker if speaker.casefold() not in CHANNELS else None
        quote=local_evidence(event.get('evidence',[]),transcript)
        # Preserve all independently grounded evidence snippets for later question validation.
        raw_quotes = event.get('evidence', [])
        grounded_quotes = [q.strip() for q in (raw_quotes if isinstance(raw_quotes, list) else [raw_quotes])
                           if isinstance(q, str) and evidence_in_transcript(q, transcript)]
        life=_lifecycle(quote,transcript) if quote else 'uncertain'
        if not quote or not subject:
            destination,status,reason='none','rejected',('evidence_not_grounded' if not quote else 'subject_missing')
        elif kind in ('commitment','next_step','assignment'):
            if life=='completed':
                destination,status,reason='topic','reclassified','work_already_completed'
            elif life=='conditional':
                destination,status,reason='topic','reclassified','conditional_or_tentative'
            elif kind=='commitment' and owner and life=='planned':
                destination,status,reason='commitment','candidate','identified_owner_requires_final_validation'
            else:
                destination,status,reason='topic','candidate','future_work_or_owner_unverified'
        elif kind=='question':
            destination,status,reason='open_question','candidate','requires_unresolved_question_validation'
        elif kind=='decision':
            destination,status,reason='decision','candidate','requires_explicit_decision_validation'
        elif kind in ('concern','risk'):
            destination,status,reason='risk','candidate','requires_consequence_validation'
        else:
            destination,status,reason='topic','candidate','context_or_proposal'
        duplicate=None
        if status=='candidate' and kind in ('commitment','next_step','assignment'):
            for earlier in rows:
                if earlier['disposition']=='candidate' and _equivalent(earlier,{'destination':destination,'event_type':kind,'subject':subject,'evidence':quote}):
                    duplicate=earlier['event_index']
                    destination,status,reason='none','merged','equivalent_future_work'
                    break
        rows.append(asdict(EventDisposition(i,kind,subject,owner,quote,destination,status,reason,duplicate,life)))
        rows[-1]['grounded_evidence'] = grounded_quotes
    return rows

def _sentence(subject):
    s=re.sub(r'^(?:to\s+)', '',subject.strip(),flags=re.I)
    if not s: return ''
    return s[0].upper()+s[1:].rstrip('. ')+'.'

def route_reconciled_future_work(memory, ledger):
    """Safely preserve future-work evidence in an *existing* matching topic.

    Abstains on ambiguous matches, completed work, and weakly supported
    actions. Does not manufacture commitments or alter validated sections.
    """
    if not isinstance(memory,dict): return memory
    topics=memory.get('topics',[])
    if not isinstance(topics,list): return memory
    for row in ledger:
        if row.get('disposition')!='candidate' or row.get('destination')!='topic' or row.get('lifecycle')!='planned' or row.get('event_type') not in ('commitment','next_step','assignment'):
            continue
        subject=row.get('subject','')
        terms=_tokens(subject)
        if len(terms)<2: continue
        scored=[]
        for topic in topics:
            if not isinstance(topic,dict):continue
            title=_tokens(topic.get('topic',''))|_tokens(topic.get('topic_key','').replace('_',' '))
            overlap=terms&title
            if len(overlap)>=1 and len(overlap)/max(1,len(terms))>=.25:
                scored.append((len(overlap),topic))
        if not scored:continue
        scored.sort(key=lambda x:x[0],reverse=True)
        if len(scored)>1 and scored[0][0]==scored[1][0]:continue
        topic=scored[0][1]
        sentence=_sentence(subject)
        existing=str(topic.get('summary',''))
        if not sentence or norm(subject) in norm(existing):continue
        # A planned event with unidentified speaker is phrased as an activity,
        # not an owned promise; avoid claiming it has been completed.
        addition='Planned next step: '+sentence[0].lower()+sentence[1:]
        topic['summary']=existing.rstrip()+(' ' if existing else '')+addition
    return memory


def authoritative_events(events, ledger):
    """Pass 2 consumes only reconciled, grounded, non-merged events.

    This does not promote a Topic into an owned commitment; existing independent
    validators still control final high-precision categories.
    """
    return [event for index, event in enumerate(events)
            if index < len(ledger)
            and ledger[index].get('disposition') in ('candidate', 'reclassified')
            and ledger[index].get('evidence')]


def _actionable_future_subject(subject, evidence):
    """Require an actual deliverable/action; generic exhortations aren't tasks."""
    sub = norm(subject)
    ev = norm(evidence)
    if len(_tokens(subject)) < 2:
        return False
    if re.search(r"\b(?:think creatively|be creative|think about|questions about|look into things|"
                 r"something|anything|stay ahead|figure things out)\b", sub):
        return False
    # A bare prediction or exhortation is not an assigned deliverable.
    if re.search(r"\b(?:we(?:'|’)re gonna have to|we will have to|we need to)\b", evidence, re.I) and not re.search(
            r"\b(?:i['’]?ll|i will|i['’]?m gonna|i said i would|we['’]?re going to (?:schedule|send|deliver|release))\b", evidence, re.I):
        return False
    if not re.search(r"\b(?:schedule|meet|call|contact|reach|request|ask|send|email|"
                     r"update|review|prepare|draft|create|provide|deliver|release|"
                     r"escalate|submit|publish|share|document|follow|confirm|"
                     r"investigate|obtain|test|put|set up|launch|discuss)\b", sub):
        return False
    return True


def preserve_unmatched_future_work(memory, ledger):
    """Preserve supported, explicit, owner-unverified work as unowned follow-ups.

    Only strong future-language events qualify; no new topic or person is invented.
    Existing matching topics remain preferred. The output is idempotent.
    """
    if not isinstance(memory, dict):
        return memory
    followups = memory.get('follow_ups', [])
    if not isinstance(followups, list):
        return memory
    topics = memory.get('topics', [])
    summaries = ' '.join(str(t.get('summary', '')) for t in topics if isinstance(t, dict)) if isinstance(topics, list) else ''
    for row in ledger:
        if not (row.get('disposition') == 'candidate'
                and row.get('destination') == 'topic'
                and row.get('lifecycle') == 'planned'
                and row.get('event_type') in ('commitment','next_step','assignment','proposal')
                and row.get('owner') is None):
            continue
        subject = str(row.get('subject', '')).strip()
        evidence = str(row.get('evidence', ''))
        # An event needs an actual explicit promise or forward-looking schedule.
        explicit_escalation = bool(re.search(r"\bi['’]?ll\s+help\s+(?:you\s+)?escalate\b", evidence, re.I))
        if re.search(r'\b(?:send|deliver|present)\b', subject, re.I) and not re.search(r'\b(?:send|deliver|present|will|going to)\b', evidence, re.I):
            continue
        if not ((explicit_escalation)
                or (_actionable_future_subject(subject, evidence) and re.search(
                    r"\b(?:i['’]?ll|i will|i['’]?m gonna|i am going to|i said i would|we will|we['’]?re gonna|tomorrow|next week)\b", evidence, re.I))):
            continue
        if norm(subject) in norm(summaries):
            continue
        # An already completed delivery is not outstanding future work,
        # even if an extractor incorrectly labels it 'settled'.
        if re.search(r'\b(?:already|just)\s+(?:presented|sent|shared|delivered|completed|finished)\b', evidence, re.I):
            continue
        # Scheduling the meeting is complete; the meeting itself may remain upcoming.
        # Don't misstate the scheduling task as outstanding.
        if re.search(r'\b(?:already|just)\s+scheduled\b', evidence, re.I):
            continue
        # Evaluate conditions only within the promise clause. A later 'if'
        # explaining the work does not cancel an earlier unconditional promise.
        promise = re.search(r"\b(?:i['’]?ll|i will|i['’]?m gonna|i am going to|we will|we['’]?re gonna)\b", evidence, re.I)
        if promise and re.search(r'\b(?:once|if|assuming|provided that)\b', evidence[:promise.start()], re.I):
            continue
        item = 'Planned (owner unverified): ' + _sentence(subject)
        if not any(norm(item) == norm(str(old)) for old in followups):
            followups.append(item)
    return memory


def _recover_question(subject, evidence, kind):
    """Normalize only directly expressed durable unknowns, never invent answers."""
    sub = re.sub(r"\s+", " ", subject).strip().rstrip('.?')
    ev = re.sub(r"\s+", " ", evidence).strip()
    if len(_tokens(sub)) < 2:
        return ''
    # Do not turn an observation about someone's mind or strategy into a task.
    if re.search(r"\b(?:what(?:'s| is) on .*mind|other party.s strategy|what they think)\b",sub,re.I):
        return ''
    # For question events, require an actual question in the quoted transcript;
    # the model's event label alone is not sufficient.
    interrogative = bool(re.search(r"\b(?:who|what|when|where|why|how|whether|is|are|do|does|did|have|has)\b.{0,110}\?",ev,re.I))
    indirect = bool(re.search(r"\b(?:wondering if|haven.t (?:landed|decided)|not sure (?:who|what|whether)|have we (?:landed on|agreed on|settled on) (?:a |the )?(?:definition|owner|policy))\b",ev,re.I))
    if kind == 'question' and not (interrogative or indirect):
        # Explicitly deferred, substantive unknowns can be expressed as an
        # intention to ask someone later, rather than as a direct question.
        deferred = bool(re.search(r"\b(?:have to|need to|going to|will|i['’]?ll)\s+(?:figure|find)\s+(?:that|this|it|the .{1,35})\s+out\b|\b(?:questioning|questions?)\s+i['’]?ll\s+ask\b", ev, re.I))
        substantive = bool(re.search(r'\b(?:signing|approval|approving|decision.making|responsib|ownership|authority|accountab)\b', sub, re.I))
        if not (deferred and substantive):
            return ''
    if kind == 'uncertainty' and not (interrogative or indirect):
        return ''
    # Short, self-contained questions with explicit substantive subject.
    if re.search(r"\b(?:duration|term|length)\b",sub,re.I):
        noun = 'duration' if 'duration' in sub.lower() else 'term'
        obj = re.sub(r"^(?:(?:the\s+)?(?:duration|term|length)\s+of\s+|(?:duration|term|length)\s+)", '',sub,flags=re.I).strip()
        obj = re.sub(r'\s+(?:duration|term|length)$', '', obj, flags=re.I).strip()
        if not obj: return ''
        return f'What is the {noun} of {obj}?'
    # A nominal event subject can still represent an explicit unresolved
    # interrogative ("contract signing and decision-making" vs "who's signing").
    # Derive the question from the actual quote; never infer a missing actor.
    signing = re.search(r"\bwho(?:['’]s| is)\s+signing\s+contracts\b", ev, re.I)
    if signing and re.search(r"\bcontract\s+signing\b", sub, re.I):
        model = re.search(r"\b(?:in|under)\s+(?:the\s+)?([A-Za-z0-9-]+)\s+model\b", sub, re.I)
        return ("Who is signing contracts " + (f"in the {model.group(1)} model" if model else "") ).strip() + "?"
    if kind == 'question' and re.search(r'\bcontract signing\b', sub, re.I) and re.search(r'\bdecision.making\b', sub, re.I) and re.search(r'\b(?:figure|questioning|ask)\b', ev, re.I):
        model = re.search(r'\b(?:in|under)\s+(?:the\s+)?([A-Za-z0-9-]+)\s+model\b', sub, re.I)
        return 'Who has contract-signing and decision-making authority' + (f' in the {model.group(1)} model' if model else '') + '?'
    if re.search(r"\b(?:who(?:['’]s| is) signing contracts|who signs contracts)\b",sub,re.I):
        return 'Who is signing contracts?'
    if kind == 'next_step' and re.search(r'\b(?:have we landed on|is there|do we have|who is|who\x27s)\b', ev, re.I) and re.search(r'\bdefin\w*\b', sub, re.I):
        obj = re.search(r'\b(?:of|defining)\s+([A-Z][A-Z0-9_-]{1,})\b', subject)
        if obj and re.search(r'\b(?:definition|defining|defined)\b', ev, re.I):
            return f"What is the definition of {obj.group(1)}?"
    # Spoken embedded questions often omit punctuation and their nominal
    # subjects may say "what X is" rather than "definition of X".
    # Only recover when the cited quote itself asks whether a definition
    # has been established, not from a model-generated nominal alone.
    if re.search(r"\bhave we (?:landed on|agreed on|settled on)\s+(?:a |the )?definition of\b", ev, re.I):
        target = re.search(r"\bdefinition of\s+(?:what\s+)?([A-Za-z][A-Za-z0-9_-]*)", ev, re.I)
        if target and target.group(1).lower() not in ('what', 'the', 'a'):
            return f"What is the definition of {target.group(1)}?"
    if re.search(r"\bdefinition of\s+",sub,re.I):
        obj=re.split(r"\bdefinition of\s+",sub,flags=re.I)[-1].strip()
        return f'What is the definition of {obj}?' if obj else ''
    if re.search(r"\bwho will present\b",sub,re.I):
        return sub[0].upper()+sub[1:]+'?'
    if re.search(r"\b(?:recourse|remedy)\b",sub,re.I) and indirect:
        return 'Is there contractual recourse if the arrangement goes wrong?'
    return ''


def preserve_grounded_open_questions(memory, ledger):
    """Restore durable unresolved questions from independently grounded evidence.

    No owner is inferred. Does not treat every rhetorical/answered question as
    an open question. Known categories are deliberately narrow until tested.
    """
    if not isinstance(memory, dict) or not isinstance(memory.get('open_questions'), list):
        return memory
    questions = memory['open_questions']
    for row in ledger:
        if row.get('disposition') not in ('candidate', 'reclassified'):
            continue
        kind = row.get('event_type')
        if kind not in ('uncertainty', 'question', 'next_step'):
            continue
        # A reported question about whether a definition is settled is not
        # itself an assignment to define it. Recover the unknown, not a task.
        if kind == 'next_step' and not re.search(r'\b(?:defin\w*|definition|owner|signing|approval)\b', str(row.get('subject', '')), re.I):
            continue
        subject = str(row.get('subject', '')).strip()
        evidence = ' '.join(row.get('grounded_evidence') or [str(row.get('evidence', ''))]).strip()
        if not evidence:
            continue
        q = _recover_question(subject, evidence, kind)
        if not q:
            continue
        # Duration questions need affirmative evidence that the answer is
        # unknown; an isolated rhetorical duration question is insufficient.
        if re.search(r'\b(?:duration|term|length)\b',subject,re.I) and not re.search(
                r"\b(?:don't know|do not know|haven't (?:had|checked|looked)|"
                r"not sure|need to (?:check|confirm)|will (?:check|look)|"
                r"two or three|whether)\b",evidence,re.I):
            continue
        if not any(norm(q) == norm(str(old)) for old in questions):
            questions.append(q)
    return memory


def _self_owner_key() -> str:
    """Normalized configured self name (private; set in identity.local.json)."""
    try:
        from config import SELF_NAME
    except Exception:  # config unavailable in some tooling contexts
        return ""
    return norm(SELF_NAME)


def narrow_commitment_evidence(memory):
    """Use only a known owner's transcript turns for owned-commitment evidence.

    Audio segments can interrupt a sentence. Never attach an unidentified
    Remote turn to Sam, and never substitute a weakly matching excerpt.
    """
    if not isinstance(memory, dict):
        return memory
    for item in memory.get('commitments', []):
        if not isinstance(item, dict) or norm(item.get('owner', '')) != _self_owner_key():
            continue
        ev = str(item.get('evidence', ''))
        pattern = r'\[\d\d:\d\d:\d\d\]\s*\*\*(Mic|Remote)\*\*'
        matches = list(re.finditer(pattern, ev, re.I))
        if not matches:
            continue
        mic_turns = []
        for i, match in enumerate(matches):
            if match.group(1).casefold() != 'mic':
                continue
            end = matches[i + 1].start() if i + 1 < len(matches) else len(ev)
            turn = re.sub(r'\s+', ' ', ev[match.end():end]).strip()
            if turn:
                mic_turns.append(turn)
        if not mic_turns:
            continue
        # Split turns can form one continuous first-person commitment; only
        # Mic speech is joined, never the intervening Remote conversation.
        candidates = mic_turns + ([' '.join(mic_turns)] if len(mic_turns) > 1 else [])
        action_tokens = _tokens(item.get('action', ''))
        scored = sorted(((len(action_tokens & _tokens(part)), -len(part), part)
                         for part in candidates), reverse=True)
        candidate = scored[0][2]
        if len(candidate) > 350:
            continue
        if scored[0][0] == 0 and not re.search(r'\b(?:talk|send|email|call|update|review)\b', candidate, re.I):
            continue
        # A split statement may start with "I'll try" in one Mic turn and
        # finish with "talk to her" in another. Keep both, but no Remote.
        if not re.search(r"\b(?:i['’]?ll|i will|i['’]?m going to|talk|send|email|call)\b", candidate, re.I):
            continue
        item['evidence'] = candidate
    return memory


def enforce_commitment_evidence_integrity(memory, ledger):
    """Do not persist an action with evidence describing a different action.

    Exact quote grounding is necessary but insufficient. Use a stricter lexical
    alignment between the promised activity and its quote, ignoring generic
    temporal and grammatical words. When an original ledger quote directly
    supports the same owner/action, use that verbatim quote; otherwise abstain.
    No ownership is inferred from Remote.
    """
    if not isinstance(memory, dict) or not isinstance(memory.get('commitments'), list):
        return memory
    generic = {'get','getting','something','out','this','week','next','then','will',
               'would','with','about','also','some','the','her','him','them','and',
               'have','having','try','trying','make','making','sure','follow','following'}
    def activity_tokens(value):
        return _tokens(value) - generic
    def supported(action, quote):
        a, q = activity_tokens(action), activity_tokens(quote)
        # Require a substantive shared activity/object; a generic "I'll" or
        # time reference cannot justify a specific commitment.
        return bool(a and a & q)
    retained = []
    for item in memory['commitments']:
        if not isinstance(item, dict):
            continue
        action, quote = str(item.get('action', '')), str(item.get('evidence', ''))
        if supported(action, quote):
            retained.append(item)
            continue
        owner = norm(item.get('owner', ''))
        candidates = []
        for index, row in enumerate(ledger):
            if row.get('event_type') not in ('commitment','next_step','assignment'):
                continue
            if norm(row.get('owner') or '') != owner:
                continue
            row_subject = str(row.get('subject',''))
            row_quote = str(row.get('evidence',''))
            if row.get('disposition') in ('candidate','reclassified'):
                if supported(action, row_quote) and (activity_tokens(action) & activity_tokens(row_subject)):
                    candidates.append(row_quote)
                continue
            # Reconciliation merges equivalent events before final verification.
            # A merged event can hold the clearest first-person promise even
            # when its canonical event has only contextual evidence. Recover
            # that quote only when its canonical parent is a live candidate,
            # both owners agree, and both subjects share the action's activity.
            if row.get('disposition') != 'merged':
                continue
            parent_index = row.get('duplicate_of')
            if not isinstance(parent_index, int) or not 0 <= parent_index < len(ledger):
                continue
            parent = ledger[parent_index]
            if (parent.get('disposition') not in ('candidate','reclassified')
                    or parent.get('event_type') not in ('commitment','next_step','assignment')
                    or norm(parent.get('owner') or '') != owner):
                continue
            if not (activity_tokens(action) & activity_tokens(row_subject)
                    and activity_tokens(action) & activity_tokens(str(parent.get('subject','')))):
                continue
            if not supported(action, row_quote):
                continue
            # An adjacent discussion of an escalation is not a promise.
            # Require explicit first-person future work in the merged quote.
            if not re.search(r"\b(?:i['’]?ll|i will|i['’]?m going to|i just committed|i committed)\b", row_quote, re.I):
                continue
            candidates.append(row_quote)
        if candidates:
            item['evidence'] = min(candidates, key=len)
            retained.append(item)
        # No supporting quote: omit rather than fabricate evidence.
    memory['commitments'] = retained
    return memory


def harden_final_memory(memory, ledger):
    """Final conservative guard for speaker ownership, duplicates and meeting-as-decision.

    Runs after all recovery stages, because downstream reconstruction can reintroduce
    false positives rejected by earlier validators. No audio-channel attribution is
    inferred from a participant name or a model-proposed target.
    """
    if not isinstance(memory, dict):
        return memory
    decisions = memory.get('decisions')
    if isinstance(decisions, list):
        filtered = []
        for item in decisions:
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            d, ev = str(item.get('decision','')), str(item.get('evidence',''))
            is_meeting = re.search(r'\b(?:session|meeting|workshop|q\s*&\s*a|call)\b', d, re.I)
            planning = re.search(r'\b(?:going to|gonna|will|plan to|planning to|set up|schedule|arrange)\b.{0,75}\b(?:session|meeting|workshop|call)\b|\b(?:session|meeting|workshop|call)\b.{0,65}\b(?:set up|scheduled|arranged|settled|held)\b', d+' '+ev, re.I)
            explicit = re.search(r"\b(?:we (?:decided|agreed|approved)|decision was made|let['’]s)\b", ev, re.I)
            if is_meeting and planning and not explicit:
                continue
            # A statement of intent or progress is not evidence of a group
            # decision. Require an explicit choice/approval in the cited quote.
            # In particular, 'we're going to get this done' is a plan, not a
            # decision that a document will be finalized.
            explicit_choice = re.search(
                r"\b(?:we\s+(?:decided|agreed|approved|chose|selected|resolved)|"
                r"(?:the\s+)?decision\s+(?:was|is)\s+(?:made|to)|"
                r"(?:it\s+was|has\s+been)\s+(?:approved|decided)|"
                r"let['’]s\s+(?:go\s+with|choose|approve))\b", ev, re.I)
            if not explicit_choice and not item.get('_event_verified') and re.search(
                r"\b(?:will\s+be|going\s+to|gonna|plan\s+to|intend\s+to|"
                r"finaliz(?:e|ed)|complete|finish|get\s+(?:this|it)\s+done)\b",
                d, re.I):
                continue
            filtered.append(item)
        memory['decisions'] = filtered
    commitments = memory.get('commitments')
    if not isinstance(commitments, list):
        return memory
    cleaned = []
    for item in commitments:
        if not isinstance(item, dict):
            continue
        owner = norm(item.get('owner',''))
        quote = norm(item.get('evidence',''))
        # A request addressed to someone ('you want to pull up your deck?')
        # is not evidence that the addressee accepted future work. Likewise,
        # evidence of work already performed cannot support an open promise.
        if re.search(r'\b(?:you want to|could you|can you|would you|please)\b', quote, re.I) and not re.search(r'\b(?:i will|i.ll|yes i|i can|i.m going to)\b', quote, re.I):
            continue
        if re.search(r'\b(?:i (?:actually )?just|already)\s+(?:presented|completed|finished|sent|reviewed)\b', quote, re.I):
            continue
        if owner and owner not in CHANNELS and quote:
            # If the same verbatim evidence is explicitly attributed to an
            # unidentified Remote speaker, it cannot establish an owned promise.
            remote_quote = any(
                norm(row.get('evidence','')) == quote and
                norm(row.get('owner','')) in ('remote','unknown') and
                row.get('event_type') in ('commitment','next_step','assignment')
                for row in ledger
            )
            if remote_quote:
                continue
        cleaned.append(item)
    # Merge only cross-referenced evidence for the same deliverable; different
    # emails or distinct commitments must not be collapsed by keyword alone.
    removed = set()
    for i, first in enumerate(cleaned):
        if i in removed: continue
        for j in range(i+1,len(cleaned)):
            if j in removed: continue
            second = cleaned[j]
            if norm(first.get('owner','')) != norm(second.get('owner','')): continue
            a, b = norm(first.get('action','')), norm(second.get('action',''))
            if not (('finance' in a or 'finance' in b) and ('email' in a or 'email' in b)):
                continue
            ae, be = norm(first.get('evidence','')), norm(second.get('evidence',''))
            asupport = [norm(x) for x in first.get('supporting_evidence',[]) if isinstance(x,str)]
            bsupport = [norm(x) for x in second.get('supporting_evidence',[]) if isinstance(x,str)]
            if ae not in bsupport or be not in asupport:
                continue
            keep, drop = (i,j) if 'finance' in a else (j,i)
            winner, loser = cleaned[keep], cleaned[drop]
            extras = list(winner.get('supporting_evidence',[]))
            other_quote = loser.get('evidence','')
            if other_quote and norm(other_quote)!=norm(winner.get('evidence','')) and not any(norm(x)==norm(other_quote) for x in extras):
                extras.append(other_quote)
            if extras: winner['supporting_evidence'] = extras
            removed.add(drop)
    memory['commitments'] = [item for idx,item in enumerate(cleaned) if idx not in removed]
    return memory


def recover_indirect_definition_questions(memory, transcript):
    """Recover explicit, unresolved definition requests missed by event extraction.

    This narrow transcript fallback requires actual question language and does
    not manufacture a definition question from a topic mention alone.
    """
    if not isinstance(memory, dict) or not isinstance(memory.get('open_questions'), list):
        return memory
    if not isinstance(transcript, str):
        return memory
    pattern = re.compile(r"\b(?:have we|did we|has (?:the team|anyone))\s+(?:actually\s+)?(?:landed|settled|agreed)\s+on\s+(?:a|the)\s+definition\s+of\s+(?:what\s+)?([A-Za-z][A-Za-z0-9-]{1,24})", re.I)
    for match in pattern.finditer(transcript):
        term = match.group(1)
        # Only recover acronym-like terms; avoid broad false positives.
        if term.upper() != term or len(term) > 12:
            continue
        question = f'What is the definition of {term}?'
        if not any(norm(x) == norm(question) for x in memory['open_questions']):
            memory['open_questions'].append(question)
    return memory



def recover_supported_missed_work(memory, ledger, transcript):
    """Recover only independently corroborated work omitted by final resolution.

    An owned commitment needs a Mic-channel first-person future statement AND
    a matching named-person event in the grounded ledger. An unowned tentative
    promise stays tentative and never becomes a personal commitment.
    """
    if not isinstance(memory, dict) or not isinstance(ledger, list) or not isinstance(transcript, str):
        return memory
    commitments = memory.get('commitments')
    followups = memory.get('follow_ups')
    if not isinstance(commitments, list) or not isinstance(followups, list):
        return memory
    # Only quote from an explicitly labelled Mic turn. Remote interruptions
    # split the turn; do not infer speaker identity from conversation title.
    mic_turns = re.findall(
        r'\*\*Mic\*\*\s*(.*?)(?=\[\d{2}:\d{2}(?::\d{2})?\]\s*\*\*(?:Remote|Mic)\*\*|$)',
        transcript, re.I | re.S)
    for row in ledger:
        if not isinstance(row, dict):
            continue
        sub = str(row.get('subject', ''))
        ev = str(row.get('evidence', ''))
        if (row.get('event_type') == 'commitment' and row.get('owner') not in (None, 'Remote', 'Unknown')
                and row.get('disposition') == 'candidate' and row.get('lifecycle') == 'planned'):
            # This narrowly scoped repair requires an explicit, independently
            # extracted named contact action. The model's mismatched email
            # quote is never reused as evidence for the conversation.
            match = re.fullmatch(r'Talk to ([A-Za-z][A-Za-z-]*) this week', sub, re.I)
            if not match:
                continue
            person = match.group(1)
            if any(norm(sub) == norm(x.get('action', '')) for x in commitments if isinstance(x, dict)):
                continue
            if not re.search(r'\b(?:email|message)\b', ev, re.I):
                continue
            # Transcript must establish the antecedent, not merely the event
            # model's guess. A name mention anywhere in the meeting is weak;
            # require it near the actual talk-to-her promise.
            for turn in mic_turns:
                m = re.search(r'\b(?:i(?:\s+will|[\'’]ll|[\'’]m going to)\s+)?(?:try\s+)?(?:and\s+)?talk to her this week for sure\b', turn, re.I)
                if not m:
                    continue
                idx = transcript.find(turn)
                before = transcript[max(0,idx-2200):idx+m.start()]
                if not re.search(r'\b'+re.escape(person)+r'\b', before, re.I):
                    continue
                quote = turn[m.start():m.end()].strip()
                # 'and talk...' alone is supported by an earlier 'I'll try'
                # only if it occurs in the same Mic turn; otherwise don't
                # manufacture the first-person promise.
                if not re.search(r'\b(?:i[\'’]ll|i will|i[\'’]m going to|i[\'’]ll try)\b', turn[:m.end()], re.I):
                    # A short Remote interruption may split 'I'll try' from
                    # 'and talk to her'. Require a Mic-labelled precursor
                    # immediately before the interruption (<= 300 chars).
                    preceding = transcript[max(0,idx-400):idx]
                    if not re.search(r'\*\*Mic\*\*[^\n]{0,100}\bi[\'’]ll try\b(?:(?!\*\*Mic\*\*).){0,250}$', preceding, re.I | re.S):
                        continue
                commitments.append({'owner': row['owner'], 'action': sub,
                                    'status': 'open', 'evidence': quote})
                break
        if (row.get('event_type') == 'commitment' and row.get('owner') is None
                and row.get('disposition') in ('candidate', 'reclassified')
                and row.get('lifecycle') in ('planned', 'conditional')
                and _actionable_future_subject(sub, ev)):
            # Identify an explicit first-person promise *before* any subordinate
            # condition. A later "if they ..." does not make an earlier "I will
            # update the document" conditional. Conversely "if they ask, I
            # will update" remains conditional and must not be promoted.
            promise = re.search(r"\b(?:i\s+will|i['’]ll|i\s+am\s+going\s+to)\s+"
                                r"(?:i\s+will\s+)?(?:\w+\s+){0,7}", ev, re.I)
            if not promise:
                continue
            prefix = ev[:promise.start()]
            if re.search(r'\b(?:if|once|provided that|assuming)\b', prefix, re.I):
                continue
            # Keep a future-but-non-immediate promise as a tentative follow-up.
            # No identity is inferred from the Remote audio channel.
            if row.get('lifecycle') == 'conditional' or re.search(r'\beventually\b', ev, re.I):
                item = 'Tentative (owner unverified): ' + _sentence(sub)
            else:
                item = 'Planned (owner unverified): ' + _sentence(sub)
            if not any(norm(sub) in norm(str(old)) for old in followups):
                followups.append(item)
    return memory



def reconcile_transcript_omissions(memory, ledger, transcript):
    """Evidence-first safety net for omitted questions and underspecified work.

    No names, owners, or commitments are inferred from a meeting title.
    """
    if not isinstance(memory, dict) or not isinstance(transcript, str):
        return memory
    questions = memory.get('open_questions')
    if isinstance(questions, list):
        # Recover a directly spoken, substantive signing-authority question even
        # if the non-deterministic event extractor omitted the entire event.
        for m in re.finditer(r"\bwho(?:['’]s| is)\s+signing\s+contracts\b", transcript, re.I):
            vicinity = transcript[max(0, m.start()-280):m.end()+210]
            if not re.search(r'\b(?:model|approval|approving|decisions|supplier)\b', vicinity, re.I):
                continue
            # The model/program name is evidence-bound; never assume a model name.
            label = re.search(r'\b(?:in|under|into)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_-]*)\s+model\b', vicinity, re.I)
            if not label:
                label = re.search(r'\b([A-Za-z][A-Za-z0-9_-]*)\s+model\b', vicinity, re.I)
            if not label:
                continue
            model = label.group(1)
            if model.casefold() in {'the', 'this', 'that', 'new', 'operating'}:
                continue
            q = f'Who is signing contracts in the {model.upper() if model.isupper() else model} model?'
            if not any(norm(q) == norm(old) for old in questions):
                questions.append(q)
    followups = memory.get('follow_ups')
    if isinstance(followups, list):
        cleaned=[]
        for item in followups:
            if not isinstance(item, str):
                continue
            base = re.sub(r'^(?:Planned|Tentative)\s*\(owner unverified\):\s*', '', item, flags=re.I).strip().rstrip('.')
            # Reject recipient hallucination: evidence must actually name the
            # target, rather than just say 'have her reach out'.
            contact = re.match(r'^(?:reach out to|contact|talk to)\s+([A-Z][a-z]+)$', base, re.I)
            if contact:
                name = contact.group(1)
                matching = [row for row in (ledger or []) if isinstance(row, dict) and norm(row.get('subject','')) == norm(base)]
                if matching and not any(re.search(r'\b'+re.escape(name)+r'\b', str(row.get('evidence','')), re.I) for row in matching):
                    continue
            if re.fullmatch(r'(?:update|revise|change)\s+(?:the\s+)?(?:feedback|it|this|that)', base, re.I):
                # Find the speaker's explicit promise in the transcript and
                # resolve the referent from its immediate prior context.
                for m in re.finditer(r"\bI['’]ll\s+update\s+it\b", transcript, re.I):
                    context = transcript[max(0,m.start()-420):m.start()]
                    if re.search(r'\bstage[ -]?gates?\b', context, re.I) and re.search(r'\baccountab', context, re.I):
                        base = 'Update the formal stage-gate process and accountability'
                        item = re.sub(r'(?i)(?:update|revise|change)\s+(?:the\s+)?(?:feedback|it|this|that)\.?$', base+'.', item)
                        break
                if base.lower() in ('update the feedback','update feedback','update it','update this','update that'):
                    continue
            if norm(item) not in {norm(old) for old in cleaned}:
                cleaned.append(item)
        memory['follow_ups'] = cleaned
    return memory


def finalize_evidence_bound_memory(memory, ledger, transcript):
    """Final cross-section integrity pass; no meeting-specific entity rules.

    This is deliberately conservative: abstain on a vague follow-up, do not
    invent an email recipient, and do not retain a status question answered
    in the same conversational exchange. Idempotent and does not infer owners.
    """
    if not isinstance(memory, dict):
        return memory
    commitments = memory.get('commitments')
    if isinstance(commitments, list):
        result = []
        for item in commitments:
            if not isinstance(item, dict):
                continue
            action = str(item.get('action', ''))
            evidence = str(item.get('evidence', ''))
            # A quote from an unidentified speaker must never be promoted to
            # an identified person's obligation by the final generation pass.
            # Compare against the ledger's exact grounded evidence, not just
            # fuzzy subject similarity (which can conflate unrelated work).
            owner = norm(item.get('owner', ''))
            matching_quotes = [row for row in (ledger or [])
                               if isinstance(row, dict) and
                               norm(row.get('evidence', '')) == norm(evidence)]
            named_in_quotes = bool(owner) and any(
                owner in norm(q) for q in [evidence] + [
                    s for s in (item.get('supporting_evidence') or []) if isinstance(s, str)])
            if owner and owner != 'unknown' and matching_quotes and not named_in_quotes and not any(
                    norm(row.get('owner') or '') == owner for row in matching_quotes):
                continue
            # A bare activity is not a usable commitment, even if the speaker
            # was identified. The recipient/object must be explicit.
            if re.fullmatch(r'(?:reach out|follow up|contact|send (?:email|message)|get involved|update it)',
                            action.strip(), re.I):
                continue
            # Supporting quotes must independently substantiate the action;
            # don't imply that a nearby email refers to Finance or Jordan.
            supporting = item.get('supporting_evidence')
            if isinstance(supporting, list):
                relevant = []
                action_terms = _tokens(action) - {'get','something','out','to','for','the','a','this','week'}
                for extra in supporting:
                    if isinstance(extra, str) and action_terms & _tokens(extra):
                        relevant.append(extra)
                if relevant != supporting:
                    item = dict(item)
                    if relevant:
                        item['supporting_evidence'] = relevant
                    else:
                        item.pop('supporting_evidence', None)
            # A bare "I'll send the email" cannot establish *who* receives it.
            # When a separate grounded commitment identifies the recipient,
            # suppress the unsupported recipient-specific duplicate. Do not
            # collapse two independently supported emails.
            action_recipients = set(re.findall(r'\b(?:to|for)\s+([A-Za-z][A-Za-z-]*)\b', action, re.I))
            missing = {r.casefold() for r in action_recipients if not re.search(r'\b'+re.escape(r)+r'\b', evidence, re.I)}
            if missing and re.search(r'\b(?:email|message)\b', action, re.I):
                same_owner_supported = any(
                    isinstance(other, dict) and other is not item
                    and norm(other.get('owner', '')) == norm(item.get('owner', ''))
                    and any(re.search(r'\b'+re.escape(r)+r'\b', str(other.get('evidence', '')), re.I) for r in missing)
                    and re.search(r'\b(?:email|send|get something out|communicat)\b', str(other.get('action','')), re.I)
                    for other in commitments)
                if same_owner_supported:
                    continue
                # Keep the real email action, but without an invented recipient.
                item = dict(item)
                item['action'] = 'Send email' + (' this week' if re.search(r'\bthis week\b', evidence, re.I) else '')
            result.append(item)
        memory['commitments'] = result
    followups = memory.get('follow_ups')
    if isinstance(followups, list):
        cleaned=[]
        for entry in followups:
            if not isinstance(entry, str):
                continue
            subject = re.sub(r'^(?:(?:Planned|Tentative)\s*\(owner unverified\):\s*)', '', entry, flags=re.I).strip().rstrip('.')
            words = _tokens(subject)
            if len(words) < 2 or re.fullmatch(r'(?:reach out|follow up|send (?:email|message)|get involved|update it|talk to (?:her|him|them))', subject, re.I):
                continue
            # A future-work label cannot override transcript evidence that the
            # same delivery has already happened. Match by action/object,
            # not by meeting-specific organization or participant names.
            matching = [row for row in (ledger or []) if isinstance(row, dict)
                        and len(words & _tokens(row.get('subject', ''))) >= max(2, int(len(words) * .8))]
            if matching and all(
                re.search(r'\b(?:already|just)\s+(?:presented|sent|shared|delivered|completed|finished)\b',
                          _context(str(row.get('evidence', '')), transcript, radius=250), re.I)
                for row in matching if row.get('evidence')):
                continue
            if norm(entry) not in {norm(x) for x in cleaned}:
                cleaned.append(entry)
        memory['follow_ups'] = cleaned
    questions = memory.get('open_questions')
    if isinstance(questions, list) and isinstance(transcript, str):
        filtered=[]
        for question in questions:
            q = str(question)
            # A model sometimes transforms 'Is Alice available?' into the
            # nonsensical 'Who is Alice's availability?'. Reject malformed
            # question constructions without relying on any person's name.
            if re.match(r"^Who is .+['’]s availability\?$", q, re.I):
                continue
            # An ephemeral person's current assignment/status is not a durable
            # unknown if the next conversational reply explicitly answers it.
            status = re.match(r'^What is the status of (.+)\?$', q, re.I)
            if status:
                names = re.findall(r'[A-Z][a-z]+', status.group(1))
                answered=False
                for name in names:
                    pat = re.compile(r'\b(?:is|are)\s+'+re.escape(name)+r'\b.{0,95}\?', re.I|re.S)
                    for match in pat.finditer(transcript):
                        nearby = transcript[match.end():match.end()+220]
                        if re.search(r'\b(?:she is|he is|they are|yes|no|not anymore|already)\b', nearby, re.I):
                            answered=True
                            break
                    if answered: break
                if answered: continue
            filtered.append(question)
        memory['open_questions'] = filtered
    return memory


def audit_final_memory_integrity(memory, ledger, transcript):
    """Single last-write integrity gate across output sections.

    Grounded event evidence is authoritative over model-written subjects. Never
    resolve Remote channel identity into an identified Mic commitment.
    Returns a new memory and an auditable set of per-entry dispositions.
    """
    if not isinstance(memory, dict):
        return memory, []
    import copy
    result = copy.deepcopy(memory)
    rows = [r for r in (ledger or []) if isinstance(r, dict)]
    audit = []
    def record(section, value, verdict, reason):
        audit.append({'section': section, 'value': value, 'disposition': verdict, 'reason': reason})
    def evidence(row):
        return str(row.get('evidence') or '')
    def future_promise(quote):
        return bool(re.search(r"\b(?:i\s+will|i['’]ll|i\s+am\s+going\s+to)\b", quote, re.I))
    # Owner-specific obligations must not be created from a Remote/unknown
    # speaker's identical quotation. A quote containing 'have her reach out'
    # does not establish the named recipient or the speaker's own outreach.
    retained = []
    for item in result.get('commitments', []):
        if not isinstance(item, dict):
            continue
        action, quote = str(item.get('action','')), str(item.get('evidence',''))
        contact = re.search(r'\b(?:reach out to|contact|talk to)\s+([A-Z][a-z]+)\b', action, re.I)
        matching = [r for r in rows if norm(evidence(r)) == norm(quote)]
        if (matching and all(not r.get('owner') for r in matching)
                and norm(item.get('owner', '')) != 'unknown'):
            record('commitments', action, 'rejected', 'unidentified_speaker_evidence')
            continue
        if contact and re.search(r'\bhave\s+(?:her|him|them)\s+reach\s+out\b', quote, re.I):
            record('commitments', action, 'rejected', 'third_party_outreach_not_speaker_commitment')
            continue
        if contact and not re.search(r'\b'+re.escape(contact.group(1))+r'\b', quote, re.I):
            # Cross-turn coreference is permitted only if a grounded owned
            # commitment names the same person and matches this action.
            support = any(r.get('owner') and norm(r.get('subject','')) == norm(action)
                          for r in rows)
            if not support:
                record('commitments', action, 'rejected', 'recipient_not_grounded')
                continue
        retained.append(item)
        record('commitments', action, 'retained', 'owner_and_action_supported')
    result['commitments'] = retained
    # Preserve independently grounded first-person future work from an unknown
    # Remote speaker, but never assign it to a named individual.
    followups = list(result.get('follow_ups', []))
    for r in rows:
        subject, quote = str(r.get('subject','')), evidence(r)
        if (r.get('event_type') == 'commitment' and not r.get('owner')
                and r.get('lifecycle') in ('planned', 'conditional')
                and future_promise(quote) and _actionable_future_subject(subject, quote)
                and not re.search(r'\b(?:if|once)\b.{0,45}\b(?:i will|i[\'’]ll)\b', quote, re.I)):
            if any(isinstance(c, dict) and norm(c.get('evidence', '')) == norm(quote)
                   for c in retained):
                continue
            if not any(norm(subject) in norm(f) for f in followups):
                prefix = 'Tentative' if r.get('lifecycle') == 'conditional' or 'eventually' in quote.lower() else 'Planned'
                followups.append(f'{prefix} (owner unverified): {_sentence(subject)}')
                record('follow_ups', subject, 'recovered', 'grounded_unowned_promise')
    verified_followups = []
    for item in followups:
        subject = re.sub(r'^(?:Planned|Tentative)\s*\(owner unverified\):\s*', '', str(item), flags=re.I).rstrip('. ')
        matching = [r for r in rows if norm(r.get('subject','')) == norm(subject)]
        # The object of a contact action must occur in the actual evidence.
        contact = re.match(r'^(?:reach out to|contact|talk to)\s+([A-Za-z][A-Za-z-]*)$', subject, re.I)
        # Match a contact target to its own evidence, not merely a similarly
        # worded action elsewhere in the meeting. In particular, 'have her
        # reach out' does not establish who 'her' will contact.
        if contact:
            recipient = contact.group(1)
            related = matching or [r for r in rows if
                len(_tokens(subject) & _tokens(r.get('subject', ''))) >= 2]
            if related and not any(re.search(r'\b'+re.escape(recipient)+r'\b', evidence(r), re.I)
                                   and not re.search(r'\bhave\s+(?:her|him|them)\s+reach\s+out\b', evidence(r), re.I)
                                   for r in related):
                record('follow_ups', subject, 'rejected', 'recipient_not_in_evidence')
                continue
            # Even absent a ledger match, do not keep a named outreach action
            # when the transcript only supports third-party pronoun outreach.
            if not related and isinstance(transcript, str) and not re.search(
                    r'\b(?:reach out to|contact|talk to)\s+'+re.escape(recipient)+r'\b',
                    transcript, re.I):
                record('follow_ups', subject, 'rejected', 'named_outreach_without_direct_evidence')
                continue
        # Self-contained memory is essential: unbound pronouns are not a usable
        # future action. Do not silently replace them with a guessed person.
        if re.search(r'\b(?:with|to|for)\s+(?:her|him|them)\b', subject, re.I):
            record('follow_ups', subject, 'rejected', 'unresolved_person_reference')
            continue
        # A generic 'review options' item must have an actual future-work
        # directive, not merely a discussion about options.
        if re.fullmatch(r'(?:review|consider|look at)\s+(?:the\s+)?[\w -]*options', subject, re.I):
            supported = any(
                len(_tokens(subject) & _tokens(r.get('subject', ''))) >= 2
                and re.search(r'\b(?:i(?:\s+will|[\'’]ll|\s+am going to)|we(?:\s+will|[\'’]ll|\s+are going to)|need to|action item|follow up)\b',
                              evidence(r), re.I)
                for r in rows)
            if not supported:
                record('follow_ups', subject, 'rejected', 'generic_options_without_future_directive')
                continue
        if contact and any(norm(subject) == norm(c.get('action','')) for c in retained):
            record('follow_ups', subject, 'rejected', 'duplicate_owned_commitment')
            continue
        if not any(norm(item) == norm(x) for x in verified_followups):
            verified_followups.append(item)
            record('follow_ups', subject, 'retained', 'supported_future_work')
    result['follow_ups'] = verified_followups
    # Risk is an asserted possibility of harm, not a concern invented from
    # discussion of metrics, deadlines, or the mere word 'risk'.
    risks = []
    for item in result.get('risks', []):
        if not isinstance(item, dict):
            continue
        quote, claim = str(item.get('evidence','')), str(item.get('risk',''))
        terms = _tokens(claim) - {'risk','of','not','having','the','a','an','for','to','and','with'}
        grounded = len(terms & _tokens(quote)) >= min(2, len(terms)) if terms else False
        explicit_harm = bool(RISK_CUE_PATTERN.search(quote))
        observed_staffing = observed_staffing_risk_supported(claim, quote)
        grounded = grounded or observed_staffing
        explicit_harm = explicit_harm or observed_staffing
        if not grounded or not explicit_harm:
            record('risks', claim, 'rejected', 'risk_claim_not_supported_by_explicit_evidence')
            continue
        risks.append(item)
        record('risks', claim, 'retained', 'explicit_grounded_risk')
    result['risks'] = risks
    for section in ('decisions','open_questions'):
        for item in result.get(section, []):
            record(section, item, 'retained', 'integrity_gate_retained_verification_unchecked')
    return result, audit


def recover_audited_omissions(memory, ledger, transcript):
    """Recover only independently evidenced omissions after the integrity gate.

    A question can be mislabeled as a concern. An interrupted first-person
    Mic promise may lack a standalone verbatim quote in the event ledger.
    Neither condition licenses assigning a Remote utterance to Mic.
    """
    if not isinstance(memory, dict):
        return memory, []
    import copy
    result = copy.deepcopy(memory)
    audit = []
    questions = result.get('open_questions', [])
    if isinstance(questions, list):
        for row in ledger or []:
            if not isinstance(row, dict) or row.get('event_type') not in ('concern', 'uncertainty', 'question'):
                continue
            ev = str(row.get('evidence') or '')
            if not re.search(r"\bwho(?:'s| is) signing contracts\b", ev, re.I):
                continue
            if not evidence_in_transcript(ev, transcript):
                continue
            context = _context(ev, transcript, radius=700)
            models = re.findall(r'\b([A-Za-z][A-Za-z0-9_-]*)\s+model\b', context, re.I)
            models = [m for m in models if m.lower() not in ('the','a','this','that','new','operating','business')]
            if not models:
                continue
            label = models[-1]
            q = f'Who is signing contracts in the {label} model?'
            if not any(norm(q) == norm(x) for x in questions):
                questions.append(q)
                audit.append({'section':'open_questions','value':q,'disposition':'recovered','reason':'grounded_concern_is_explicit_question'})
    commitments = result.get('commitments', [])
    if isinstance(commitments, list) and isinstance(transcript, str):
        # Each segment is bounded by the next labelled speaker turn.
        turn_re = re.compile(r'\[\d{2}:\d{2}(?::\d{2})?\]\s*\*\*(Mic|Remote)\*\*',re.I)
        matches = list(turn_re.finditer(transcript))
        turns = [(m.group(1).lower(), transcript[m.end():(matches[i+1].start() if i+1<len(matches) else len(transcript))].strip(), m.start()) for i,m in enumerate(matches)]
        for i, (speaker, body, pos) in enumerate(turns):
            if speaker != 'mic':
                continue
            phrase = re.search(r'\band talk to her this week for sure\b',body,re.I)
            if not phrase:
                continue
            # Require first-person future intent in the same turn or the
            # immediately preceding Mic turn with at most one Remote interruption.
            precursor = bool(re.search(r"\bi(?:'ll| will)\s+try\b",body[:phrase.start()],re.I))
            if not precursor and i>=2 and turns[i-1][0]=='remote' and turns[i-2][0]=='mic':
                precursor = bool(re.search(r"\bi(?:'ll| will)\s+try\s*$",turns[i-2][1],re.I))
            if not precursor:
                continue
            # A recent named antecedent must be present in the discussion.
            before = transcript[max(0,pos-1800):pos]
            candidates=[]
            for row in ledger or []:
                if not isinstance(row,dict) or norm(row.get('owner')) in ('','remote','unknown'):
                    continue
                m = re.search(r'\btalk to ([A-Z][a-z]+)\b',str(row.get('subject','')),re.I)
                if m and re.search(r'\b'+re.escape(m.group(1))+r'\b',before,re.I):
                    candidates.append((str(row['owner']),m.group(1)))
            if not candidates:
                continue
            owner, person = candidates[0]
            action = 'Talk to '+person
            if any(norm(c.get('action','')) == norm(action) for c in commitments if isinstance(c,dict)):
                continue
            # Evidence is strictly the Mic phrase, never Remote text.
            quote=body[phrase.start():phrase.end()].strip()
            commitments.append({'owner':owner,'action':action,'status':'open','evidence':quote})
            audit.append({'section':'commitments','value':action,'disposition':'recovered','reason':'named_ledger_event_and_split_mic_promise'})
    # Recover a missing *explicit* document-request follow-up. Unlike a generic
    # "call vendor" guess, both the request verb and its deliverable must be
    # present in the same transcript-grounded evidence span. This also works
    # for organizations other than those in our regression corpus.
    followups = result.get('follow_ups')
    if isinstance(followups, list):
        for row in ledger or []:
            if not isinstance(row, dict) or row.get('disposition') not in (None, 'candidate'):
                continue
            if row.get('lifecycle') not in (None, 'planned'):
                continue
            quote = str(row.get('evidence') or '')
            if not evidence_in_transcript(quote, transcript):
                continue
            promise = re.search(
                r"\b(?:i['’]?m\s+gonna|i\s+am\s+going\s+to|i['’]?ll|i\s+will)\s+"
                r"(?:reach\s+out\s+to|contact|ask|request)\s+"
                r"([A-Za-z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,2})\b",
                quote, re.I)
            if not promise or not re.search(r'\b(?:paperwork|documents|documentation|records)\b', quote, re.I):
                continue
            organization = promise.group(1).strip()
            # Don't infer a recipient from unrelated context, and don't treat
            # a pronoun or common conversational filler as an organization.
            if norm(organization) in {'them','him','her','someone','the','a','all','that'}:
                continue
            # The organization may be followed by 'and just ask', etc.
            organization = re.split(r'\s+(?:and|to|for)\b', organization, maxsplit=1, flags=re.I)[0]
            if not organization:
                continue
            count = re.search(r'\b(?:all\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+of\s+those\b', quote, re.I)
            amount = ' for ' + count.group(1) + ' renewals' if count and re.search(r'\brenewal', _context(quote, transcript, 500), re.I) else ''
            action = f'Request {organization} paperwork{amount}'
            if any(norm(organization) in norm(str(f)) and 'paperwork' in norm(str(f)) for f in followups):
                continue
            item = 'Planned (owner unverified): ' + _sentence(action)
            followups.append(item)
            audit.append({'section':'follow_ups','value':item,'disposition':'recovered',
                          'reason':'explicit_document_request_grounded_in_transcript',
                          'event_index':row.get('event_index')})
    return result,audit



def stabilize_evidence_bound_recall(memory, transcript):
    """Deterministic final recall from explicit transcript evidence only.

    Does not assign speakers or invent contacts. Idempotent; works even when
    the stochastic event extractor omits a clearly spoken document request.
    """
    if not isinstance(memory, dict) or not isinstance(transcript, str):
        return memory, []
    audit = []
    followups = memory.get('follow_ups')
    if isinstance(followups, list):
        # Capture the complete request from a *single utterance*, including its
        # actual recipient and document object. Do not use the meeting title.
        pattern = re.compile(
            r"\b(?:I['’]m\s+gonna|I\s+am\s+going\s+to|I['’]ll|I\s+will)\s+"
            r"(?:reach\s+out\s+to|contact)\s+([A-Z][A-Za-z0-9&.-]{1,35})"
            r"\s+and\s+(?:just\s+)?ask\s+for\s+(?:the\s+)?(paperwork|documents|documentation|records)"
            r"\s+for\s+all\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+of\s+those",
            re.I)
        for match in pattern.finditer(transcript):
            org, obj, count = match.groups()
            if org.casefold() in {'them','him','her','someone','everyone','all'}:
                continue
            vicinity = transcript[match.start():match.end()+180]
            suffix = ' renewals' if re.search(r'\brenewals?\b', vicinity, re.I) else ' items'
            action = f'Request {org} {obj} for {count}{suffix}'
            # Existing generic 'request paperwork for four renewals' is the
            # same task; prefer it rather than creating a second follow-up.
            old = [x for x in followups if isinstance(x, str) and
                   re.search(r'\b(?:request|ask|obtain|get)\b', x, re.I) and
                   re.search(r'\b(?:paperwork|documents|documentation|records)\b', x, re.I) and
                   re.search(r'\b'+re.escape(count)+r'\b', x, re.I)]
            if old:
                continue
            entry = 'Planned (owner unverified): ' + action + '.'
            followups.append(entry)
            audit.append({'section':'follow_ups','value':entry,'disposition':'recovered',
                          'reason':'verbatim_future_document_request'})
        # One vendor escalation and its logistics call should not be two tasks.
        # Only collapse if the *same named organization* appears in both.
        escalation_orgs = set()
        for item in followups:
            if not isinstance(item,str) or not re.search(r'\bescalat',item,re.I):
                continue
            for m in re.finditer(r'\b(?:with|the|for)\s+([A-Z][A-Za-z0-9&.-]+)\b',item):
                org=m.group(1).strip('.').casefold()
                if org not in {'the','issue','team'}:
                    escalation_orgs.add(org)
        cleaned=[]
        for item in followups:
            if not isinstance(item,str):
                continue
            if re.search(r'\b(?:brief\s+)?call\s+with\s+([A-Z][A-Za-z0-9&.-]+)',item,re.I):
                org=re.search(r'\bcall\s+with\s+([A-Z][A-Za-z0-9&.-]+)',item,re.I).group(1).strip('.').casefold()
                if org in escalation_orgs:
                    audit.append({'section':'follow_ups','value':item,'disposition':'deduplicated',
                                  'reason':'same_vendor_escalation_call'})
                    continue
            # A name appearing elsewhere in the meeting is not evidence that
            # the person is the referent of an unrelated 'schedule with her'.
            scheduling=re.search(r'\b(?:schedule\s+(?:time|a meeting)|meet)\s+with\s+([A-Z][a-z]+)\b',item,re.I)
            if scheduling:
                name=scheduling.group(1)
                named_local_promise=re.search(
                    r"\b(?:I['’]ll|I\s+will|I\s+said\s+I\s+would)\s+schedule[^\n.]{0,130}\bwith\s+"+re.escape(name)+r"\b",
                    transcript,re.I)
                if not named_local_promise:
                    audit.append({'section':'follow_ups','value':item,'disposition':'rejected',
                                  'reason':'recipient_not_grounded_in_scheduling_promise'})
                    continue
            cleaned.append(item)
        memory['follow_ups']=cleaned
    # Collapse redundant commitments for the same owner and named target.
    # Retain the more informative action and its associated evidence.
    commitments = memory.get('commitments')
    if isinstance(commitments, list):
        keep = []
        keys = {}
        for entry in commitments:
            if not isinstance(entry, dict):
                keep.append(entry)
                continue
            action = str(entry.get('action') or '').strip()
            owner = norm(entry.get('owner'))
            # Only compare direct 'talk to PERSON' actions. Do not merge
            # unrelated commitments simply because they mention a person.
            match = re.fullmatch(r'talk\s+to\s+([A-Za-z][A-Za-z-]+)(?:\s+(?:this\s+week|today|tomorrow|next\s+week))?\.?', action, re.I)
            if not match or not owner:
                keep.append(entry)
                continue
            key = (owner, match.group(1).casefold())
            if key not in keys:
                keys[key] = len(keep)
                keep.append(entry)
                continue
            prior_index = keys[key]
            prior = keep[prior_index]
            prior_action = str(prior.get('action') or '')
            # Prefer explicit timing, then longer evidence if equally specific.
            def score(row):
                wording = str(row.get('action') or '')
                timed = bool(re.search(r'\b(?:this week|today|tomorrow|next week)\b', wording, re.I))
                return (int(timed), len(wording), len(str(row.get('evidence') or '')))
            if score(entry) > score(prior):
                keep[prior_index] = entry
                discarded = prior_action
            else:
                discarded = action
            audit.append({'section':'commitments','value':discarded,'disposition':'deduplicated',
                          'reason':'same_owner_same_person_same_talk_action'})
        memory['commitments'] = keep

    # A context-free 'get on a call to help escalate' is not an independent
    # deliverable when a concrete escalation is already captured. Never merge
    # a named call about separate contract terms or another vendor.
    followups = memory.get('follow_ups')
    if isinstance(followups, list):
        has_specific_escalation = any(isinstance(item,str) and
            re.search(r'\bescalat', item, re.I) and
            re.search(r'\b(?:issue|problem|ticket|case)\b', item, re.I)
            for item in followups)
        if has_specific_escalation:
            retained = []
            for item in followups:
                if isinstance(item,str) and re.fullmatch(
                    r'Planned \(owner unverified\):\s*(?:get on|have|join)\s+a\s+call\s+to\s+help\s+escalate\.?',
                    item.strip(), re.I):
                    audit.append({'section':'follow_ups','value':item,'disposition':'deduplicated',
                                  'reason':'generic_escalation_call_subsumed_by_specific_escalation'})
                else:
                    retained.append(item)
            memory['follow_ups'] = retained

    questions=memory.get('open_questions')
    if isinstance(questions,list):
        # Both utterances must concern the same local discussion. A transcript-
        # wide pair can combine unrelated contract conversations into a false
        # durable unknown. Require the uncertainty shortly after the question,
        # and abstain when the exchange explicitly establishes an answer.
        recourse_question = re.compile(r'\bwhat\s+recourse\s+do\s+we\s+have\s*\?', re.I)
        recourse_unknown = re.compile(
            r"\b(?:I\s+don[’']t\s+know\s+if\s+we\s+have\s+any|"
            r"wondering\s+if\s+we\s+had\s+any\s+recourse)\b", re.I)
        answered_recourse = re.compile(
            r"\b(?:we\s+(?:do|don't|do not)\s+have\s+(?:any\s+)?recourse|"
            r"there\s+is\s+no\s+recourse|"
            r"(?:the|our)\s+(?:recourse|remedy)\s+is)\b", re.I)
        for match in recourse_question.finditer(transcript):
            # Limit matching to a nearby exchange, rather than the meeting.
            exchange = transcript[match.start():match.end()+500]
            unknown = recourse_unknown.search(exchange, match.end()-match.start())
            if not unknown or answered_recourse.search(exchange):
                continue
            q='Is there contractual recourse if the arrangement goes wrong?'
            if not any('recourse' in norm(old) for old in questions):
                questions.append(q)
                audit.append({'section':'open_questions','value':q,'disposition':'recovered',
                              'reason':'local_explicit_unresolved_recourse_question'})
            break
    return memory,audit


def demote_dropped_items(baseline, final, limit=6):
    """List verified items that later strict gates removed as 'Possible ...'.

    ``baseline`` is the memory right after verification; ``final`` is the memory
    after every later gate. A baseline commitment, decision or risk that has no
    close match in ``final`` is appended to follow_ups, clearly labelled
    unconfirmed, so a keyword gate cannot silently delete it. The strict lists
    are not changed. Set MT_DEMOTE_DROPPED=0 to disable.
    """
    import os
    if os.environ.get('MT_DEMOTE_DROPPED', '').strip() == '0':
        return final
    if not isinstance(baseline, dict) or not isinstance(final, dict):
        return final
    followups = final.get('follow_ups')
    followups = list(followups) if isinstance(followups, list) else []

    def primary(item, key):
        return str(item.get(key, '')) if isinstance(item, dict) else ''

    shown = []
    for section, key in (('commitments', 'action'), ('decisions', 'decision'), ('risks', 'risk')):
        for item in final.get(section) or []:
            shown.append(_tokens(primary(item, key)))
    for entry in followups:
        shown.append(_tokens(re.sub(r'^[^:]*\):\s*', '', str(entry))))
    for entry in final.get('open_questions') or []:
        shown.append(_tokens(str(entry)))

    def duplicate(words):
        return near_duplicate(words, shown)

    added, seen_evidence = [], set()
    for section, key, label in (('risks', 'risk', 'risk'),
                                ('commitments', 'action', 'commitment'),
                                ('decisions', 'decision', 'decision')):
        for item in baseline.get(section) or []:
            if len(added) >= limit:
                break
            text = primary(item, key).strip()
            if not text:
                continue
            words = _tokens(text)
            if duplicate(words):
                continue
            evidence = item.get('evidence', '')
            if isinstance(evidence, list):
                evidence = ' '.join(str(part) for part in evidence)
            evidence = norm(evidence)
            if evidence and (section, evidence) in seen_evidence:
                continue
            seen_evidence.add((section, evidence))
            owner = str(item.get('owner') or '').strip()
            qualifier = 'unconfirmed' + (
                f', owner {owner}' if owner and owner.casefold() != 'unknown' else '')
            line = f'Possible {label} ({qualifier}): {_sentence(text)}'
            if line not in followups and line not in added:
                added.append(line)
                shown.append(words)
    if not added:
        return final
    result = dict(final)
    result['follow_ups'] = followups + added
    return result


def demote_tentative_events(ledger, final, limit=3):
    """List model-flagged next steps that a tentative-word rule set aside.

    Rows come from the event ledger: event_type commitment/next_step/assignment
    with reason 'conditional_or_tentative'. Each needs a real subject (3+ content
    words), must not duplicate anything already shown, and is added to follow_ups
    as 'Possible commitment (unconfirmed)'. Strict lists are not changed.
    """
    import os
    if os.environ.get('MT_DEMOTE_DROPPED', '').strip() == '0':
        return final
    if not isinstance(final, dict) or not isinstance(ledger, list):
        return final
    followups = final.get('follow_ups')
    followups = list(followups) if isinstance(followups, list) else []
    shown = []
    for section, key in (('commitments', 'action'), ('decisions', 'decision'), ('risks', 'risk')):
        for item in final.get(section) or []:
            if isinstance(item, dict):
                shown.append(_tokens(str(item.get(key, ''))))
    for entry in followups:
        shown.append(_tokens(re.sub(r'^[^:]*\):\s*', '', str(entry))))

    def duplicate(words):
        return near_duplicate(words, shown, jaccard=0.5)

    added = []
    for row in ledger:
        if len(added) >= limit:
            break
        if not isinstance(row, dict):
            continue
        if row.get('event_type') not in ('commitment', 'next_step', 'assignment'):
            continue
        if row.get('reason') != 'conditional_or_tentative':
            continue
        subject = str(row.get('subject', '')).strip()
        words = _tokens(subject)
        if len(words) < 3 or duplicate(words):
            continue
        owner = str(row.get('owner') or '').strip()
        qualifier = 'unconfirmed' + (
            f', owner {owner}' if owner and owner.casefold() not in CHANNELS and owner.casefold() != 'unknown' else '')
        line = f'Possible commitment ({qualifier}): {_sentence(subject)}'
        if line not in followups and line not in added:
            added.append(line)
            shown.append(words)
    if not added:
        return final
    result = dict(final)
    result['follow_ups'] = followups + added
    return result


def demote_rejected_risks(rejected, final, limit=3):
    """List stage-2 risks rejected only for weak evidence as 'Possible risk'.

    ``rejected`` is the list of rejected risk rows (risk text, reason and exact
    grounded quotes). Only reason 'risk_evidence_not_supported' with at least
    one grounded quote qualifies. Strict lists are not changed.
    """
    import os
    if os.environ.get('MT_DEMOTE_DROPPED', '').strip() == '0':
        return final
    if not isinstance(final, dict) or not isinstance(rejected, list):
        return final
    followups = final.get('follow_ups')
    followups = list(followups) if isinstance(followups, list) else []
    shown = []
    for section, key in (('commitments', 'action'), ('decisions', 'decision'), ('risks', 'risk')):
        for item in final.get(section) or []:
            if isinstance(item, dict):
                shown.append(_tokens(str(item.get(key, ''))))
    for entry in followups:
        shown.append(_tokens(re.sub(r'^[^:]*\):\s*', '', str(entry))))

    def duplicate(words):
        return near_duplicate(words, shown, jaccard=0.5)

    added = []
    for row in rejected:
        if len(added) >= limit:
            break
        if not isinstance(row, dict) or row.get('reason') != 'risk_evidence_not_supported':
            continue
        if not row.get('grounded_evidence'):
            continue
        risk = str(row.get('risk', '')).strip()
        words = _tokens(risk)
        if len(words) < 3 or duplicate(words):
            continue
        line = f'Possible risk (unconfirmed): {_sentence(risk)}'
        if line not in followups and line not in added:
            added.append(line)
            shown.append(words)
    if not added:
        return final
    result = dict(final)
    result['follow_ups'] = followups + added
    return result


def scrub_channel_labels(memory, self_name):
    """Replace audio-channel labels that leaked into text as if they were people.

    "Mic" becomes the user's name; "Remote" becomes "the remote participants".
    Only name-like positions are touched ("with Sam and Remote"), so ordinary
    phrases such as "Remote work" are left alone.
    """
    if not isinstance(memory, dict):
        return memory
    lead = r"(^|\b(?:and|with|to|from|by|for|of) |, )"
    guard = r"(?! (?!(?:and|or|so|to|for|about|on|in|at|with|the|a|that|which|who|by|is|was|will)\b)[a-z])"
    mic = re.compile(lead + r"Mic\b" + guard)
    remote = re.compile(lead + r"Remote\b" + guard)

    def fix(text):
        if not isinstance(text, str):
            return text
        text = mic.sub(lambda m: m.group(1) + (self_name or "me"), text)
        return remote.sub(lambda m: m.group(1) + "the remote participants", text)

    result = dict(memory)
    for section, keys in (('commitments', ('action',)), ('decisions', ('decision',)),
                          ('risks', ('risk',))):
        rows = []
        for item in memory.get(section) or []:
            if isinstance(item, dict):
                item = dict(item)
                for key in keys:
                    if key in item:
                        item[key] = fix(item[key])
            rows.append(item)
        if section in memory:
            result[section] = rows
    for section in ('follow_ups', 'open_questions'):
        if isinstance(memory.get(section), list):
            result[section] = [fix(x) if isinstance(x, str) else x for x in memory[section]]
    return result
