# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deterministic intent-classification engine (Spec 001 Phase B, arch §2).

Pure, synchronous classification of ONE chat message into the closed C1
taxonomy.  The engine never calls a model, provider, client, or tool: it
receives exactly one string and returns a typed result — message content
may influence workflow dispatch only (Spec 001 §Constitution §11
compatibility; TR1 and the TR5/TR6 dispatch components hold structurally —
the engine has no KB, metadata, tenant, or user input surface at all).

Rules are evaluated in the accepted EXPLICIT priority order (never
incidental source order — see ``DeterministicEngine._ordered_rules`` and
``RULE_PRIORITIES``); each rule fires at most one outcome and the first
rule that fires wins.

Documented interpretation decisions (conservative; flagged in the Phase B
closure report, not silent reinterpretation):

1. MULTI-INTENT precedence.  When the scan detects a multi-intent message
   (Spec 001 §Multi-intent policy: an informational/analysis intent plus a
   consequential intent, or two or more consequential operations, across
   distinct clauses), the workflow rules R-DOC-FRAMING..R-QUESTION (10-50)
   ABSTAIN so first-match-wins falls through to R-MULTI-INTENT (55) and the
   message clarifies, executing nothing.  This is the only reading
   consistent with acceptance criteria TR59-TR66, whose examples combine a
   documentation/analysis clause with a consequential clause.
2. Clause claiming (the D2 fix).  A clause anchored by knowledge framing
   ("how do I" / "explain" / "come funziona" ...) or by hypothetical /
   prompt-writing framing claims its own command verbs: those verbs are
   questions, not instructions, and never count as command matches.  A
   command in a DIFFERENT clause of the same message still counts (and, if
   consequential, makes the message multi-intent).
3. R-NEGATION scope.  The rule fires for ANY negated workflow operation
   verb — including safe, analytical, and proposal verbs ("Do not
   propose a cohort" must not enter a workflow either) — Gate B
   correction, owner decision D-1 (the interpretation flagged at the
   Phase B evidence reconciliation was ratified by the owner).  The
   outcome class is unchanged: never routed to a workflow, falls to RAG.
4. Vocabulary without a C1 intent.  Import rejection and ACP
   deactivation are recognized workflow vocabulary (they feed adjacency
   and multi-intent detection and the guard's consequential set) but
   have NO intent in the closed C1 vocabulary; they fail closed to
   CLARIFICATION_REQUIRED.  (Gate B correction, owner decision D-3: the
   ACP evidence-enrichment operations now map to the three new C1
   intents, so they no longer belong to this class; SQ-1 is resolved.)
5. Gate B correction interpretations (owner decisions D-1..D-3,
   2026-10-01).  Multi-intent informational clauses count without a
   family noun when another clause's recognized operation and opaque
   resource identifier identify the family, and the analysis considers
   the complete normalized message before any earlier informational
   rule can terminate evaluation (D-2a); the R-DOC-FRAMING command veto
   fires only for genuinely imperative/requestive forms — closed marker
   set: please, kindly, go ahead, do it, per favore, procedi, fallo
   (D-2c); enrichment request and evidence acceptance are consequential
   and take DESTRUCTIVE_MUTATION mode per the accepted
   agent/tools.py ToolDefinitions (destructive=True) and ADR-024 (D-3).

Phase C gap (documented, fail-closed): R-FOLLOWUP can only resolve against
the typed workflow-context registry, which does not exist until Phase C;
follow-up-shaped turns therefore abstain to AMBIGUOUS carrying
``FOLLOWUP_CONTEXT`` and clarify when workflow-adjacent, or fall to RAG
when they carry no workflow signal at all (bare "yes" — legacy parity).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .taxonomy import (
    Explicitness,
    Intent,
    InteractionMode,
    ReasonCode,
    Topic,
)

# ---------------------------------------------------------------------------
# Accepted rule priorities (architecture §2; tested exactly).
# ---------------------------------------------------------------------------

RULE_PRIORITIES: Dict[str, int] = {
    "R-DOC-FRAMING": 10,
    "R-NEGATION": 20,
    "R-HYPOTHETIC": 25,
    "R-QUOTED": 30,
    "R-QUOTE-FRAMING": 32,
    "R-COMMAND": 40,
    "R-QUESTION": 50,
    "R-MULTI-INTENT": 55,
    "R-FOLLOWUP": 60,
    "R-UNSUPPORTED": 70,
}

# ---------------------------------------------------------------------------
# Normalization (NFKC + casefold + accent folding, for matching only).
# ---------------------------------------------------------------------------

_COMBINING = dict.fromkeys(
    c for c in range(0x11000) if unicodedata.category(chr(c)) == "Mn")


def _accent_fold(text: str) -> str:
    """Strip combining marks (à -> a) for matching only."""
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", decomposed.translate(_COMBINING))


def normalize_message(message: str) -> str:
    """Deterministic matching form: NFKC -> casefold -> accent fold."""
    text = unicodedata.normalize("NFKC", message or "")
    text = text.casefold()
    text = _accent_fold(text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Bare affirmatives (Spec 001 Phase C; TR67).  Closed EN/IT set matched
# against the FULL normalized message (punctuation-stripped, anchored):
# a bare affirmative carries NO operation verb and NO resource, so it can
# act only through an atomic claim of exactly one eligible typed
# pending confirmation (core/routing/context.py).  Everything else
# keeps its existing route.
# ---------------------------------------------------------------------------

_BARE_AFFIRMATIVE_FORMS = frozenset({
    # English
    "yes", "yeah", "yep", "yes please", "ok", "okay", "sure",
    "alright", "confirm", "confirm it", "confirmed", "do it",
    "do that", "do it please", "please do", "go ahead", "proceed",
    "please proceed",
    # Italian
    "si", "si grazie", "ok", "certo", "certamente", "conferma",
    "confermalo", "conferma pure", "fallo", "fallo pure", "fai pure",
    "procedi", "vai avanti", "avanti",
})


def is_bare_affirmative_message(message: str) -> bool:
    """True when the whole message is exactly one closed affirmative
    form (deterministic; no partial or embedded matches)."""
    normalized = normalize_message(message)
    stripped = normalized.strip().rstrip(".!?")
    return stripped in _BARE_AFFIRMATIVE_FORMS


# ---------------------------------------------------------------------------
# Quoted-content masking (R-QUOTED; A10/A12).
# ---------------------------------------------------------------------------

_QUOTED_PATTERNS = [
    re.compile(r"```.*?```", re.DOTALL),          # fenced code blocks
    re.compile(r"~~~.*?~~~", re.DOTALL),
    re.compile(r"`[^`\n]{1,400}`"),               # inline code spans
    re.compile(r"“[^“”\n]{1,400}”"),              # smart double quotes
    re.compile(r"\"[^\"\n]{1,400}\""),            # straight double quotes
    # Straight single quotes: only as genuine delimiters (not elision
    # apostrophes such as Italian "l'ACP" / "l'ultima", which are flanked by
    # word characters). Lookarounds require the quote to be bounded by a
    # non-word character on each side so two unrelated apostrophes are never
    # joined into one quoted span.
    re.compile(r"(?<!\w)'[^'\n]{1,400}'(?!\w)"),  # straight single quotes (delimited)
    re.compile(r"«[^»\n]{1,400}»"),
    re.compile(r"‘[^‘’\n]{1,400}’"),              # smart single quotes
]

_MASK_TOKEN = " \uE000 "


def mask_quoted(text: str) -> Tuple[str, str]:
    """Mask quoted spans / code fences before command matching.

    Content inside quotes and code never triggers workflow rules (A10,
    A12).  Returns ``(masked_text, removed_content)``.
    """
    masked = text
    removed: List[str] = []
    for pattern in _QUOTED_PATTERNS:
        def _sub(m: "re.Match[str]") -> str:
            removed.append(m.group(0))
            return _MASK_TOKEN
        masked = pattern.sub(_sub, masked)
    return masked, " ".join(removed)


# ---------------------------------------------------------------------------
# Clause segmentation (multi-intent detection + clause claiming).
# ---------------------------------------------------------------------------

_CLAUSE_SPLIT = re.compile(
    r"[.;!?\n]+"
    r"|\s(?:and\s+then|then|also|after\s+that|afterwards|e\s+poi|poi|"
    r"quindi|dopo\s+di\s+che|dopo)\s"
    r"|\s(?:and|or|but|e|o|ma|però|oppure)\s"
    r"|,"
)

# Italian question-verb forms ("qual è", "cos'è", "cosa è") accent-fold
# to "... e", which the conjunction split would tear apart; protect them
# by restoring the accented form before splitting (the accented form
# never matches the standalone conjunction "e").
_QUESTION_E = re.compile(r"\b(qual|cosa|cos'?|che\s*cos'?)\s+e\b")


def split_clauses(masked_text: str) -> List[str]:
    """Split the masked matching text into clauses.

    Sentence punctuation, sequencing markers, coordinating conjunctions,
    and commas separate clauses.  Classification re-aggregates per clause,
    so over-splitting is safe: splitting is what lets one message carry
    more than one intent (TR59-TR66) while a single knowledge-framed
    question keeps claiming its own verbs (A3/A55/A56).
    """
    protected = _QUESTION_E.sub(r"\1 è", masked_text)
    parts = [p.strip(" ,;") for p in _CLAUSE_SPLIT.split(protected)]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Closed workflow vocabulary (EN + IT), narrowed per D3.
# ---------------------------------------------------------------------------

# Words that mark a following operation word as a NOUN, not a verb
# ("a cohort for review" vs "review the cohort").
_NOUN_POSITION_PRECEDERS = {
    "for", "of", "in", "during", "after", "the", "a", "an",
    "per", "di", "del", "della", "dei", "delle", "degli", "il", "lo",
    "la", "le", "gli", "un", "uno", "una", "durante", "dopo",
}

# Noun suffixes: a consequential operation verb extended by one of these is
# a noun form (e.g. "activation"/"enrichment"/"attivazione"), not the
# command verb.  Used to keep consequential-operation recognition from
# mistaking a noun for a command (E-D1 relaxation guard).
_NOUN_SUFFIX = re.compile(r"(?:ion|ment|tion|zioni|mento|zione|zioni)$")

# Operation nouns that may be recognized as consequential commands even in
# noun position (E-D1): the Italian phrasing "esegui il rollback" /
# "esegui il ripristino" places the operation noun after an article, yet it
# is the command.  Kept to a minimal closed set so a genuinely polysemous
# noun like "import" is never mistaken for a command.
_ARTICLE_TOLERANT_VERBS = frozenset({"rollback", "ripristino", "ripristina"})


def _token_at(text: str, index: int) -> str:
    """The whitespace-delimited token containing ``index`` (used to test
    whether a consequential verb match is the whole verb or a noun form)."""
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = index
    n = len(text)
    while end < n and not text[end].isspace():
        end += 1
    return text[start:end]

# Opaque resource identifiers (architecture §2 R-COMMAND explicit-resource
# patterns; mirrors the accepted tool-boundary ID shape
# ^[A-Za-z0-9]{2,20}_[A-Za-z0-9\-]{1,64}$ in agent/tools.py).
_OPAQUE_ID = re.compile(r"\b[a-z]{2,20}_[0-9a-z][0-9a-z\-]{0,63}\b")

# Identifier prefixes resolve the resource's workflow family (the
# accepted explicit-resource patterns: acpver_*, cohort_*, job_*,
# camp_*; import batches).  A generic opaque id with an unknown prefix
# provides an explicit resource for the guard but no family strength.
_ID_FAMILY_PREFIXES: Tuple[Tuple["re.Pattern[str]", Topic], ...] = (
    (re.compile(r"^(?:acpver|acpcv|cohver|cohort)"), Topic.ACP),
    (re.compile(r"^ench"), Topic.ACP),   # enrichment job ids (ench_...)
    (re.compile(r"^job"), Topic.QUALIFICATION),
    (re.compile(r"^(?:batch|imp|importb|import_)"), Topic.COMPANY_IMPORT),
    (re.compile(r"^camp"), Topic.CAMPAIGN),
)

_PRONOUNS = {
    "it", "them", "that", "those", "all", "one", "lo", "la", "li", "le",
    "ne", "quello", "quella", "quelli", "quelle", "tutti", "tutte",
}

# Phase F-Q (owner decision F-Q2-E): Italian articles "lo/la/li/le" are
# homographs of detached object pronouns, but in correct Italian a standalone
# " la " between words is the definite article, never a pronoun (grammatical
# pronouns elide — "l'attiva" — or encliticize — "attivala").  Treating the
# article as a pronoun in the *command-match* path made non-consequential
# Italian verbs (e.g. "revisiona la proposta") spuriously match as weak
# command matches, flipping an accepted safe-workflow ambiguity from the
# English-mirroring RAG (NON_ADJACENT_AMBIGUITY) to a CLARIFY
# (WORKFLOW_ADJACENT).  The article tokens stay in _PRONOUNS for the
# workflow-adjacency signal (used by unrelated cases), but are excluded from
# the command-match pronoun trigger so Italian articles no longer fabricate a
# weak operation match.  Genuine pronouns ("it", "ne", "quello",
# enclitic/elided forms) are unaffected.
_COMMAND_PRONOUNS = _PRONOUNS - {"lo", "la", "li", "le"}

# Generic resource words (NOT family nouns and NOT identifier prefixes):
# they let weak references like "activate the newest approved version"
# register an intent for detection while remaining unroutable without a
# typed context (Phase C) or an explicit identifier.
_GENERIC_RESOURCE = re.compile(
    r"\b(?:versions?|versione|versioni|audience|audiences?|results?|"
    r"risultati|esit\w*|outcome|outcomes?)\b"
)

_FAMILY_NOUNS: Dict[Topic, List[str]] = {
    Topic.ACP: [
        r"acp\b", r"acps\b", r"average\s+customer\s+profiles?",
        r"reference\s+cohorts?", r"cohorts?", r"coorte", r"coorti",
        r"profilo\s+medio",
    ],
    Topic.QUALIFICATION: [
        r"qualifications?", r"candidates?", r"candidat\w*",
        r"workbooks?", r"jobs?", r"qualifica", r"qualifiche",
    ],
    Topic.COMPANY_IMPORT: [
        r"imports?", r"batches?\b", r"importazione", r"importazioni",
    ],
    Topic.CAMPAIGN: [
        r"campaigns?", r"audiences?", r"pubblico", r"campagna", r"campagne",
    ],
}


@dataclass(frozen=True)
class OperationSpec:
    """One workflow operation of the closed command vocabulary.

    ``intent is None`` marks recognized workflow vocabulary that has no
    intent in the closed C1 vocabulary (fail closed; module note 4).
    """

    family: Topic
    intent: Optional[Intent]
    verbs: Tuple[str, ...]
    consequential: bool
    family_override_nouns: Optional[Tuple[str, ...]] = None
    reason: ReasonCode = ReasonCode.EXPLICIT_ACTION_VERB


# Operations with no C1 intent (import rejection, ACP deactivation: no
# chat tools exist; legacy routing never provided deactivation) fail
# closed (module note 4, owner decision D-3).

OPERATIONS: Tuple[OperationSpec, ...] = (
    # --- ACP family ---
    OperationSpec(
        Topic.ACP, Intent.ACP_COHORT_PROPOSAL,
        (r"propos\w*", r"propo(?:n|r)\w*", r"extrapolat\w*", r"deriv\w*",
         r"rebuild", r"ricostituisc\w*", r"ricrea\w*"), False),
    OperationSpec(
        Topic.ACP, Intent.ACP_GENERATION,
        (r"generat\w*", r"genera\b", r"crea\w*", r"creat\w*"), False),
    OperationSpec(
        Topic.ACP, Intent.ACP_COHORT_REVIEW,
        (r"reviews?", r"reviewing", r"rived\w*", r"revisiona\w*"), False,
        family_override_nouns=(r"cohorts?", r"coorte",
                               r"reference\s+cohorts?")),
    OperationSpec(
        Topic.ACP, Intent.ACP_REVIEW,
        (r"reviews?", r"reviewing", r"rived\w*", r"revisiona\w*"), False),
    OperationSpec(
        Topic.ACP, Intent.ACP_COHORT_APPROVAL,
        (r"approv\w*",), True,
        family_override_nouns=(r"cohorts?", r"coorte",
                               r"reference\s+cohorts?")),
    OperationSpec(
        Topic.ACP, Intent.ACP_APPROVAL, (r"approv\w*",), True),
    OperationSpec(
        Topic.ACP, Intent.ACP_ACTIVATION,
        (r"activat\w*", r"attiva\w*"), True),
    OperationSpec(
        Topic.ACP, Intent.ACP_SUPERSESSION,
        (r"supersed\w*", r"sostituisc\w*", r"replace"), True),
    OperationSpec(
        Topic.ACP, Intent.ACP_ROLLBACK,
        (r"roll\s?back", r"rollback\w*", r"ripristin\w*"), True),
    OperationSpec(
        Topic.ACP, None, (r"deactivat\w*", r"disattiva\w*"), True,
        reason=ReasonCode.CONSEQUENTIAL_UNAVAILABLE),
    OperationSpec(
        Topic.ACP, Intent.ACP_LINEAGE,
        (r"lineage", r"provenance", r"storico", r"cronologia"), False,
        family_override_nouns=(r"acp", r"acps", r"versions?",
                               r"versione", r"versioni")),
    OperationSpec(
        Topic.ACP, Intent.ACP_STATUS,
        (r"statu\w*", r"stato", r"show", r"list", r"read",
         r"mostra\w*", r"visualizz\w*", r"vedi\b"), False),
    # --- ACP evidence enrichment (Gate B correction, owner decision D-3;
    # per the accepted agent/tools.py ToolDefinitions and ADR-024: the
    # request is destructive=True / explicit-approval-only (paid
    # web-research recording UNVERIFIED observations); the job read is
    # read-only; acceptance is destructive=True, audited supersession).
    # Placed at the end of the ACP block so the R-COMMAND noun-based
    # tie-break prefers the enrichment-job status read over the generic
    # qualification status ("Show me the enrichment job ench_5"). ---
    OperationSpec(
        Topic.ACP, Intent.ACP_EVIDENCE_ENRICHMENT,
        (r"enrich\w*", r"arricchisc\w*"), True,
        family_override_nouns=(
            r"cohorts?", r"coorte", r"versions?", r"versione", r"acp",
            r"evidence", r"evidenze", r"customers?", r"companies",
            r"observations?", r"osservazioni?", r"aziende", r"clienti",
            r"enrichment\w*", r"arricchiment\w*")),
    OperationSpec(
        Topic.ACP, Intent.ACP_EVIDENCE_ENRICHMENT_STATUS,
        (r"statu\w*", r"stato", r"progress\w*", r"show", r"list",
         r"read", r"check\w*", r"get\w*", r"mostra\w*", r"vedi\b"), False,
        family_override_nouns=(r"enrichment\w*", r"arricchiment\w*",
                               r"evidence\s+jobs?", r"observation\w*")),
    OperationSpec(
        Topic.ACP, Intent.ACP_EVIDENCE_ACCEPTANCE,
        (r"accept\w*", r"accetta\w*"), True,
        family_override_nouns=(r"evidence", r"evidenze", r"observations?",
                              r"osservazioni?", r"results?", r"risultat\w*",
                              r"enrichment\w*", r"arricchiment\w*")),
    # --- QUALIFICATION family ---
    OperationSpec(
        Topic.QUALIFICATION, Intent.QUALIFICATION_REQUEST,
        (r"qualif\w*", r"qualifica\w*", r"valuta\w*"), False),
    OperationSpec(
        Topic.QUALIFICATION, Intent.QUALIFICATION_STATUS,
        (r"statu\w*", r"stato", r"progress\w*", r"show", r"list",
         r"check\w*", r"mostra\w*", r"vedi\b"), False),
    OperationSpec(
        Topic.QUALIFICATION, Intent.QUALIFICATION_REVIEW,
        (r"reviews?", r"reviewing", r"rived\w*", r"revisiona\w*"), False),
    OperationSpec(
        Topic.QUALIFICATION, Intent.QUALIFICATION_APPROVAL,
        (r"approv\w*",), True),
    # --- COMPANY_IMPORT family ---
    OperationSpec(
        Topic.COMPANY_IMPORT, Intent.COMPANY_IMPORT_ANALYSIS,
        (r"analyz\w*", r"analys\w*", r"analizza\w*", r"examin\w*",
         r"esamin\w*", r"check\w*", r"verifica\w*"), False),
    OperationSpec(
        Topic.COMPANY_IMPORT, Intent.COMPANY_IMPORT_REVIEW,
        (r"reviews?", r"reviewing", r"rived\w*", r"revisiona\w*"), False),
    OperationSpec(
        Topic.COMPANY_IMPORT, Intent.COMPANY_IMPORT_APPROVAL,
        (r"approv\w*",), True),
    OperationSpec(
        Topic.COMPANY_IMPORT, Intent.COMPANY_IMPORT_COMMIT,
        (r"commit\w*", r"conferm\w*", r"esegui\s+il\s+commit"), True),
    OperationSpec(
        Topic.COMPANY_IMPORT, None,
        (r"reject\w*", r"rifiuta\w*", r"discard\w*", r"scarta\w*"), True,
        reason=ReasonCode.CONSEQUENTIAL_UNAVAILABLE),
    OperationSpec(
        Topic.COMPANY_IMPORT, Intent.COMPANY_IMPORT_STATUS,
        (r"statu\w*", r"stato", r"show", r"list", r"mostra\w*",
         r"vedi\b"), False),
    # --- CAMPAIGN family ---
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_CREATE,
        (r"creat\w*", r"crea\b"), False),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_AUDIENCE_ANALYSIS,
        (r"analyz\w*", r"analys\w*", r"analizza\w*", r"show", r"list",
         r"calculat\w*", r"mostra\w*", r"vedi\b"), False,
        family_override_nouns=(r"audiences?", r"pubblico")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_AUDIENCE_REVIEW,
        (r"reviews?", r"reviewing", r"rived\w*", r"revisiona\w*"), False,
        family_override_nouns=(r"audiences?", r"pubblico")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_AUDIENCE_APPROVAL,
        (r"approv\w*",), True,
        family_override_nouns=(r"audiences?", r"pubblico")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_AUDIENCE_COMMIT,
        (r"commit\w*",), True,
        family_override_nouns=(r"audiences?", r"pubblico")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_HISTORY_IMPORT,
        (r"import\w*",), True,
        family_override_nouns=(r"history", r"histories", r"cronologia",
                               r"storico", r"company\s+history")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_MARK_ADDRESSED,
        (r"mark\w*", r"flag\w*", r"contrassegn\w*"), True,
        family_override_nouns=(r"addressed", r"trattat\w*", r"gestit\w*",
                               r"contattat\w*", r"gestiti")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_OUTCOME_UPDATE,
        (r"updat\w*", r"aggiorna\w*", r"record\w*", r"registra\w*"), True,
        family_override_nouns=(r"outcomes?", r"esit\w*", r"risultat\w*")),
    OperationSpec(
        Topic.CAMPAIGN, Intent.CAMPAIGN_STATUS,
        (r"statu\w*", r"stato", r"show", r"list", r"mostra\w*",
         r"vedi\b"), False),
)

# Noun pairs that are workflow matches even without a verb (legacy parity:
# "campaign audience", "cohort proposal").
_NOUN_PAIR_RULES: Tuple[Tuple[Topic, Intent, str, str, bool], ...] = (
    (Topic.CAMPAIGN, Intent.CAMPAIGN_AUDIENCE_ANALYSIS,
     r"campaigns?", r"audiences?", False),
    (Topic.ACP, Intent.ACP_COHORT_PROPOSAL,
     r"cohorts?|coorte",
     r"proposals?|proposta|approvals?|approvazione|versions?|versione",
     False),
)

# C1 modes for consequential intents (per the destructive flags of the
# accepted tool registry — ADR-023; Gate B correction, owner decision
# D-3: the enrichment request and the evidence acceptance are both
# destructive=True per the accepted agent/tools.py ToolDefinitions).
_DESTRUCTIVE_INTENTS = {
    Intent.ACP_SUPERSESSION, Intent.ACP_ROLLBACK,
    Intent.ACP_EVIDENCE_ENRICHMENT, Intent.ACP_EVIDENCE_ACCEPTANCE,
}

_DOC_FRAMING_ANCHORS = re.compile(
    r"^(?:how\s+(?:do|can|to|does|did|would|should)|"
    r"what(?:'s|’s|\s+is|\s+are|\s+was|\s+were|\s+does|\s+do)|"
    r"why\s+(?:is|do|does)|when\s+(?:is|do|does)|which|explain|"
    r"tell\s+me\s+about|give\s+me\s+an?\s+overview|describe|"
    r"overview\s+of|"
    r"(?:let'?s\s+|lets\s+)?(?:discuss|talk\s+about)|"
    r"come\s+(?:si|funziona)|cos'?\s*[eè]|che\s+cos'?\s*[eè]|"
    r"spiega|spiegami|dimmi|descrivi|qual\s*[eè]|"
    r"cosa\s*[eè])\b"
)

# Genuinely imperative/requestive markers (Gate B correction, owner
# decision D-2c): the R-DOC-FRAMING command veto fires only when one of
# these closed-set markers co-occurs with a consequential operation verb
# and an explicit opaque identifier in the SAME clause.  Interrogative
# frames ("How do I activate acpver_123?") carry no marker and remain
# informational.
_IMPERATIVE_MARKERS = re.compile(
    r"\b(?:please|kindly|go\s+ahead|do\s+it|per\s+favore|procedi|"
    r"fallo)\b"
)

# F-R3: Italian clitic imperatives that may refer to performing/completing a
# preceding workflow operation ("fallo" = "do it").  NOT global operation
# verbs; recognized only as a second-operation signal inside a multi-clause
# message (see _add_clitic_multi_intent).  A standalone bare affirmative
# ("Fallo.") stays under the Phase C confirmation path.
_CLITIC_IMPERATIVE = re.compile(r"\b(?:fallo|falla|falli|falle)(?:\s+pure)?\b")

_HYPOTHETICAL_ANCHORS = re.compile(
    r"(?:what\s+if|suppos\w+|assuming|if\s+we\s+were\s+to|hypothetic\w+|"
    r"would\s+it\s+be\s+possible|write\s+(?:me\s+)?an?\s+(?:prompt|"
    r"example)|show\s+(?:me\s+)?an?\s+example|draft\s+(?:me\s+)?an?\s+"
    r"request|give\s+(?:me\s+)?an?\s+example|"
    r"e\s+se|se\s+potess\w+|se\s+riusciss\w+|se\s+fossimo|ipotizz\w+|"
    r"suppon\w+|immagin\w+|"
    r"scrivi\s+un\s+prompt|scrivimi\s+un\s+prompt|fammi\s+un\s+esempio|"
    r"mostra\s+un\s+esempio|bozza\s+(?:di\s+)?una?\s+richiesta)\b"
)

_QUESTION_ANCHORS = re.compile(
    r"(?:can\s+(?:retriva|you|we)|could\s+(?:retriva|you|we)|"
    r"does\s+(?:retriva|the\s+gateway)|is\s+it\s+possible|"
    r"are\s+you\s+able|puoi|potete|e\s+possibile)\b"
)

_STATUS_QUESTION_ANCHORS = re.compile(
    r"(?:what(?:'s|’s|\s+is)\s+the\s+status|status\s+of|any\s+progress|"
    r"qual\s+[eè]\s+lo\s+stato|stato\s+(?:di|della|del))"
)

_PROMPT_WRITING_RE = re.compile(
    r"\b(?:prompt|example|esempio|richiesta|request)\b"
)

# Metalinguistic command-quoting framing (F-R2c): an explicit instruction to
# quote / cite / repeat / transcribe / write down "this command" makes the
# subsequent content a non-executable example.  This is the same accepted
# framing veto as R-QUOTED (architecture §2): the content can never become a
# consequential candidate, enter the agent loop, or acquire classifier
# authority.  The anchor requires the command word and does NOT fire on every
# colon or on genuine direct commands.
_QUOTE_FRAMING_ANCHORS = re.compile(
    r"(?:quote|cite|repeat|transcribe|write\s+down)\s+this\s+command"
    r"|(?:cita(?:ndo)?|ripeti|trascrivi|scrivi)\s+questo\s+comando"
)

# Follow-up shapes (Phase C registry absent; Phase B abstains -> AMBIGUOUS).
_BARE_AFFIRMATIVES = {
    "yes", "yeah", "yep", "ok", "okay", "sure", "done", "confirmed",
    "confirm", "agree", "approved", "go", "go ahead", "do it", "proceed",
    "si", "certo", "va bene", "confermo", "procedi", "fallo", "va",
}

_FOLLOWUP_VERBS = re.compile(
    r"\b(?:enrich\w*|arricchisc\w*|accept\w*|accetta\w*|approv\w*|"
    r"activat\w*|attiva\w*|commit\w*|reject\w*|confirm\w*|conferm\w*|"
    r"reviews?|rived\w*|updat\w*|aggiorna\w*|mark\w*|flag\w*|"
    r"contrassegn\w*|qualif\w*)\b"
)

# Explicitly unsupported workflow requests (R-UNSUPPORTED): real CRM-side
# concerns that are NOT exposed as chat tools (organization merge,
# paid-provider authorization).
_UNSUPPORTED_PATTERNS = re.compile(
    r"\b(?:merg\w+|fusion\w*|fonda\w*|unify\w*|unisc\w*)\b"
    r"[^\n]{0,60}\b(?:organizations?|companies|customers?|aziende|"
    r"clienti|organizzazioni|entities)\b"
    r"|\b(?:pay|purchase|buy\w*|spend)\b[^\n]{0,60}\b(?:credits?|"
    r"provider|providers|api\s+key|budget|subscription)\b"
)


def _word_regex(fragments: Sequence[str]) -> "re.Pattern[str]":
    return re.compile(r"\b(?:" + "|".join(fragments) + r")\b")


_ALL_OPERATION_VERBS = [f for spec in OPERATIONS for f in spec.verbs]
_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don't|dont|never|non|niente|mai)\b"
    r"[^.;!?\n]{0,40}?\b(?:" + "|".join(_ALL_OPERATION_VERBS) + r")\b"
)


# ---------------------------------------------------------------------------
# Typed scan structures.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandMatch:
    """One detected workflow operation in one clause."""

    family: Topic
    intent: Optional[Intent]
    operation_key: str
    verb: str                          # matched verb surface form
    consequential: bool
    strong: bool                       # family noun / family-prefixed ID
    noun_based: bool                   # strength from a family noun
    explicit_resource: Optional[str]
    clause_index: int
    reason: ReasonCode

    @property
    def expressed_operation(self) -> Tuple[int, str]:
        """Identity of one user-expressed operation (multi-intent unit).

        One verb in one clause is ONE expressed operation, however many
        closed-vocabulary specs it pattern-matches ("approve" matching
        both the cohort and the version approval specs of one family).
        """
        return (self.clause_index, self.verb)


@dataclass
class ClauseAnalysis:
    """Per-clause scan results."""

    text: str
    index: int
    doc_framed: bool = False
    hypothetical: bool = False
    negated: bool = False
    command_matches: List[CommandMatch] = field(default_factory=list)
    family_nouns: set = field(default_factory=set)
    # Any closed-vocabulary operation word in the clause (position
    # agnostic): informational clauses carrying it count toward
    # multi-intent detection without a family noun (Gate B correction,
    # owner decision D-2a).
    has_operation_word: bool = False

    @property
    def claimed(self) -> bool:
        """Doc-framed / hypothetical / negated clauses claim their verbs."""
        return self.doc_framed or self.hypothetical or self.negated


@dataclass(frozen=True)
class DeterministicResult:
    """Engine output: the winning rule's typed C1 classification."""

    rule: str
    topic: Topic
    intent: Intent
    mode: InteractionMode
    explicitness: Explicitness
    reason_codes: Tuple[ReasonCode, ...]
    families: Tuple[Topic, ...]
    consequential_operations: Tuple[str, ...]
    resource_reference: Optional[str] = None
    unavailable_vocabulary: bool = False
    # Phase C: the matched operations of a weak follow-up shape
    # (pronoun / generic-resource object), in closed deterministic
    # order.  Detection-only — the resource comes from the typed
    # workflow-context registry, never from the engine.
    followup_intents: Tuple["Intent", ...] = ()


class _MessageScan:
    """Aggregated scan over all clauses of one message."""

    def __init__(self, clauses: List[ClauseAnalysis], removed_quoted: str):
        self.clauses = clauses
        self.removed_quoted = removed_quoted
        # Whether the whole normalized message is a closed bare affirmative
        # (Phase C atomic-claim candidate).  Consequential-operation
        # recognition must never convert a bare affirmative into a
        # consequential candidate (E-D1).
        self.is_bare_affirmative: bool = False

    @property
    def effective_matches(self) -> List[CommandMatch]:
        """Command matches not claimed by framing rules.

        Weak matches (pronoun / generic-resource objects) count for
        detection only — cross-turn resolution needs the Phase C registry.
        """
        return [m for c in self.clauses for m in c.command_matches
                if not c.claimed]

    @property
    def is_multi_intent(self) -> bool:
        """Spec §Multi-intent policy detection (TR59-TR66, TR89).

        Informational/analysis intent + consequential intent across
        distinct clauses, or two or more distinct consequential expressed
        operations.  Doc-framed and hypothetical clauses count as
        informational intents when they carry workflow vocabulary (a
        family noun is NOT required — Gate B correction, owner decision
        D-2a: the consequential clause's recognized operation and opaque
        resource identifier identify the family); negated clauses never
        count.  Distinctness is per expressed operation (clause + verb),
        so one verb matching several closed-vocabulary specs of one
        message is still ONE operation.  The full normalized message and
        its clauses are considered before any earlier informational rule
        can terminate evaluation.
        """
        matches = self.effective_matches
        consequential = [m for m in matches if m.consequential]
        if not consequential:
            return False
        distinct_cons = {m.expressed_operation for m in consequential}
        if len(distinct_cons) >= 2:
            return True
        safe = [m for m in matches if not m.consequential and m.strong]
        informational_clauses = (
            {m.clause_index for m in safe}
            | {c.index for c in self.clauses
               if (c.doc_framed or c.hypothetical)
               and (c.family_nouns or c.has_operation_word)}
        )
        cons_clauses = {m.clause_index for m in consequential}
        return bool(informational_clauses - cons_clauses)

    @property
    def families_present(self) -> List[Topic]:
        return sorted(
            {t for c in self.clauses for t in c.family_nouns}
            | {m.family for m in self.effective_matches},
            key=lambda t: t.value)

    @property
    def consequential_keys(self) -> List[str]:
        return [m.operation_key for m in self.effective_matches
                if m.consequential]

    @property
    def workflow_adjacent(self) -> bool:
        """Any workflow-vocabulary signal that is actionable or referential."""
        if any(c.family_nouns or c.command_matches for c in self.clauses):
            return True
        text = " ".join(c.text for c in self.clauses)
        words = set(text.split())
        return bool(_FOLLOWUP_VERBS.search(text)
                    and (words & _PRONOUNS
                         or _GENERIC_RESOURCE.search(text)))

    @property
    def is_followup_shape(self) -> bool:
        words = " ".join(c.text for c in self.clauses).strip()
        if not words:
            return False
        if words in _BARE_AFFIRMATIVES:
            return True
        return len(words.split()) <= 6 and bool(_FOLLOWUP_VERBS.search(words))


# ---------------------------------------------------------------------------
# The engine.
# ---------------------------------------------------------------------------

class DeterministicEngine:
    """Pure deterministic classifier (no I/O, no state, no model calls)."""

    def __init__(self, operations: Sequence[OperationSpec] = OPERATIONS):
        self._operations = tuple(operations)
        self._op_patterns: List[Tuple[OperationSpec, "re.Pattern[str]"]] = [
            (spec, _word_regex(spec.verbs)) for spec in self._operations
        ]
        self._family_patterns: Dict[Topic, "re.Pattern[str]"] = {
            topic: _word_regex(nouns)
            for topic, nouns in _FAMILY_NOUNS.items()
        }
        self._op_family_patterns: Dict[int, "re.Pattern[str]"] = {
            id(spec): _word_regex(spec.family_override_nouns)
            for spec in self._operations if spec.family_override_nouns
        }

    # -- public API ---------------------------------------------------------

    def classify(self, message: str) -> DeterministicResult:
        """Classify one message; deterministic and repeatable."""
        match_text = normalize_message(message)
        if len(match_text.replace(" ", "").replace("\ue000", "")) < 2:
            return self._ambiguous(
                (Topic.GENERAL,), (), ReasonCode.NON_ADJACENT_AMBIGUITY)

        masked, removed_quoted = mask_quoted(match_text)
        clauses = [ClauseAnalysis(text=c, index=i)
                   for i, c in enumerate(split_clauses(masked))]
        self._scan_clauses(clauses, masked)
        scan = _MessageScan(clauses=clauses, removed_quoted=removed_quoted)
        scan.is_bare_affirmative = is_bare_affirmative_message(message)

        for name, rule in self._ordered_rules():
            outcome = rule(scan)
            if outcome is not None:
                return outcome
        return self._ambiguous_default(scan)

    def _ordered_rules(self):
        """Rules in explicit priority order (never incidental source order)."""
        by_name = {
            "R-DOC-FRAMING": self._rule_doc_framing,
            "R-NEGATION": self._rule_negation,
            "R-HYPOTHETIC": self._rule_hypothetical,
            "R-QUOTED": self._rule_quoted,
            "R-QUOTE-FRAMING": self._rule_quote_framing,
            "R-COMMAND": self._rule_command,
            "R-QUESTION": self._rule_question,
            "R-MULTI-INTENT": self._rule_multi_intent,
            "R-FOLLOWUP": self._rule_followup,
            "R-UNSUPPORTED": self._rule_unsupported,
        }
        ordered = sorted(RULE_PRIORITIES.items(), key=lambda kv: kv[1])
        return [(name, by_name[name]) for name, _ in ordered]

    # -- scanning -----------------------------------------------------------

    def _scan_clauses(self, clauses: List[ClauseAnalysis],
                      masked: str) -> None:
        all_family_nouns = {
            topic for topic, pattern in self._family_patterns.items()
            if pattern.search(masked)
        }
        for clause in clauses:
            if (_DOC_FRAMING_ANCHORS.search(clause.text)
                    and self._any_workflow_vocab(clause.text)):
                clause.doc_framed = True
            if _HYPOTHETICAL_ANCHORS.search(clause.text):
                clause.hypothetical = True
            if _NEGATION_RE.search(clause.text):
                clause.negated = True
            for topic, pattern in self._family_patterns.items():
                if pattern.search(clause.text):
                    clause.family_nouns.add(topic)
            if any(pattern.search(clause.text)
                   for _spec, pattern in self._op_patterns):
                clause.has_operation_word = True
            if clause.claimed:
                continue
            clause.command_matches = self._command_matches_in_clause(
                clause, all_family_nouns)
        self._add_clitic_multi_intent(clauses)

    def _add_clitic_multi_intent(self, clauses: List[ClauseAnalysis]) -> None:
        """F-R3: contextual Italian clitic multi-intent.

        A clitic imperative ('fallo'/'falla'/'falli'/'falle') in a clause that
        does NOT itself carry a consequential command match is treated as
        evidence of a second operation when another clause of the same message
        establishes a workflow operation or family.  This enables Policy B
        multi-intent clarification (TR59-TR66) without registering the clitic
        as a global operation verb.  A standalone clitic (no sibling workflow
        clause) is left to the Phase C bare-affirmative path.
        """
        for clause in clauses:
            if clause.claimed:
                continue
            if not _CLITIC_IMPERATIVE.search(clause.text):
                continue
            if any(m.consequential for m in clause.command_matches):
                continue
            other_families = set()
            for other in clauses:
                if other is clause:
                    continue
                other_families |= other.family_nouns
                other_families |= {m.family for m in other.command_matches}
            if not other_families:
                continue
            family = sorted(other_families, key=lambda t: t.value)[0]
            clause.command_matches.append(CommandMatch(
                family=family,
                intent=None,
                operation_key=f"{family.value}:CLITIC_EXECUTE",
                verb="fallo",
                consequential=True,
                strong=False,
                noun_based=False,
                explicit_resource=None,
                clause_index=clause.index,
                reason=ReasonCode.MULTI_INTENT,
            ))

    def _any_workflow_vocab(self, clause_text: str) -> bool:
        for pattern in self._family_patterns.values():
            if pattern.search(clause_text):
                return True
        for _spec, pattern in self._op_patterns:
            if pattern.search(clause_text):
                return True
        return False

    def _command_matches_in_clause(self, clause: ClauseAnalysis,
                                   all_family_nouns: set
                                   ) -> List[CommandMatch]:
        matches: List[CommandMatch] = []
        words = set(clause.text.split())
        opaque = _OPAQUE_ID.search(clause.text)
        id_family: Optional[Topic] = None
        if opaque:
            for prefix_pattern, family in _ID_FAMILY_PREFIXES:
                if prefix_pattern.match(opaque.group(0)):
                    id_family = family
                    break
        for spec, pattern in self._op_patterns:
            verb_match = self._find_verb(
                clause.text, pattern, spec.consequential)
            if verb_match is None:
                continue
            family_nouns = (
                self._op_family_patterns.get(id(spec))
                or self._family_patterns[spec.family]
            )
            noun_here = bool(family_nouns.search(clause.text))
            id_here = bool(id_family is not None and id_family == spec.family)
            family_established_elsewhere = (
                spec.family in all_family_nouns
                and spec.family not in clause.family_nouns
            )
            pronoun_here = bool(words & _COMMAND_PRONOUNS)
            generic_here = bool(_GENERIC_RESOURCE.search(clause.text))
            strong = bool(noun_here or id_here)
            # E-D1: a consequential operation verb is recognized even when
            # its resource is unresolved, so the deterministic engine can
            # produce a consequential candidate and fail closed to
            # clarification.  The hyper-polysemous "import" operation noun
            # is the one exception: as a noun it is overwhelmingly a
            # reference ("the import", "commit import batch", "import
            # companies"), so it is recognized only with a genuine family
            # noun or history identifier (strong) — never weakly as a
            # command.  Genuine import commands carry "history" /
            # "cronologia" / a campaign identifier, so they remain strongly
            # matched; every other consequential verb may be matched
            # weakly when its resource is absent.
            consequential_weak = (
                spec.consequential
                and spec.intent is not Intent.CAMPAIGN_HISTORY_IMPORT)
            if not (strong or pronoun_here or generic_here
                    or family_established_elsewhere or consequential_weak):
                continue
            intent_key = (spec.intent.value if spec.intent else "N/A")
            matches.append(CommandMatch(
                family=spec.family,
                intent=spec.intent,
                operation_key=f"{spec.family.value}:{intent_key}",
                verb=verb_match.group(0),
                consequential=spec.consequential,
                strong=strong,
                noun_based=noun_here,
                explicit_resource=opaque.group(0) if opaque else None,
                clause_index=clause.index,
                reason=spec.reason,
            ))
        # Noun-pair matches (legacy parity: "campaign audience").
        for family, intent, noun_a, noun_b, cons in _NOUN_PAIR_RULES:
            if (re.search(rf"\b(?:{noun_a})\b", clause.text)
                    and re.search(rf"\b(?:{noun_b})\b", clause.text)):
                key = f"{family.value}:{intent.value}"
                if not any(m.operation_key == key for m in matches):
                    matches.append(CommandMatch(
                        family=family, intent=intent, operation_key=key,
                        verb=noun_b, consequential=cons, strong=True,
                        noun_based=True, explicit_resource=None,
                        clause_index=clause.index,
                        reason=ReasonCode.EXPLICIT_ACTION_VERB))
        return matches

    @staticmethod
    def _find_verb(clause_text: str,
                  pattern: "re.Pattern[str]",
                  consequential: bool = False) -> Optional["re.Match[str]"]:
        """Operation word recognition.

        The strict VERB-position check holds for every operation
        ("a cohort for review" is a noun, not a command): a verb is only
        recognized when it is not preceded by a noun-position marker
        (article / preposition / possessive).  Consequential operations add
        exactly one narrow exception — a minimal closed set of operation
        nouns that may follow an article and still be the command (the
        Italian "il rollback" / "il ripristino"; E-D1).  A match that is
        merely a noun form of the verb (e.g. "activation"/"enrichment"/
        "attivazione" — the operation verb extended by a noun suffix) is
        rejected so the deterministic engine never mistakes a noun for a
        command.
        """
        for m in pattern.finditer(clause_text):
            if consequential:
                token = _token_at(clause_text, m.start())
                if _NOUN_SUFFIX.search(token):
                    continue
                # Closed-set operation noun after an article is still the
                # command (Italian "esegui il rollback").  Every other
                # consequential verb keeps the strict verb-position check
                # below so a polysemous noun ("the import", "the commit")
                # is never mistaken for a command.
                if token in _ARTICLE_TOLERANT_VERBS:
                    return m
            before = clause_text[:m.start()].rstrip().split()[-1:]
            preceding = before[0].strip(" ,;:’'") if before else ""
            if preceding not in _NOUN_POSITION_PRECEDERS:
                return m
        return None

    # -- rules (priority order enforced by _ordered_rules) ------------------

    def _rule_doc_framing(self, scan: _MessageScan
                          ) -> Optional[DeterministicResult]:
        # Multi-intent messages clarify instead (TR59; module note 1).
        if scan.is_multi_intent:
            return None
        doc_clauses = [c for c in scan.clauses if c.doc_framed]
        if not doc_clauses:
            return None
        # Vetoed only when the clause itself carries a genuinely
        # imperative/requestive form (closed marker set, D-2c) together
        # with a consequential operation verb and an explicit resource
        # reference (arch §2; Gate B correction, owner decision D-2c).
        for clause in doc_clauses:
            if _IMPERATIVE_MARKERS.search(clause.text) \
                    and _OPAQUE_ID.search(clause.text) \
                    and self._consequential_verb_in(clause.text):
                return None
        families = tuple(sorted(
            {t for c in doc_clauses for t in c.family_nouns},
            key=lambda t: t.value))
        return DeterministicResult(
            rule="R-DOC-FRAMING",
            topic=Topic.DOCUMENTATION,
            intent=Intent.WORKFLOW_DOCUMENTATION,
            mode=InteractionMode.INFORMATIONAL,
            explicitness=Explicitness.IMPLICIT,
            reason_codes=(ReasonCode.DOC_FRAMING,),
            families=families or (Topic.GENERAL,),
            consequential_operations=(),
        )

    def _consequential_verb_in(self, clause_text: str) -> bool:
        return any(
            spec.consequential and pattern.search(clause_text)
            for spec, pattern in self._op_patterns)

    def _rule_negation(self, scan: _MessageScan
                       ) -> Optional[DeterministicResult]:
        negated = [c for c in scan.clauses if c.negated]
        if not negated:
            return None
        families = tuple(sorted(
            {t for c in negated for t in c.family_nouns},
            key=lambda t: t.value))
        return DeterministicResult(
            rule="R-NEGATION",
            topic=families[0] if families else Topic.GENERAL,
            intent=Intent.RAG_QUESTION,
            mode=InteractionMode.UNKNOWN,
            explicitness=Explicitness.NEGATED,
            reason_codes=(ReasonCode.NEGATION,),
            families=families or (Topic.GENERAL,),
            consequential_operations=(),
        )

    def _rule_hypothetical(self, scan: _MessageScan
                           ) -> Optional[DeterministicResult]:
        if scan.is_multi_intent:
            return None
        hyp_clauses = [c for c in scan.clauses if c.hypothetical]
        if not hyp_clauses:
            return None
        prompt_writing = any(
            _PROMPT_WRITING_RE.search(c.text) for c in hyp_clauses)
        families = tuple(sorted(
            {t for c in hyp_clauses for t in c.family_nouns},
            key=lambda t: t.value))
        return DeterministicResult(
            rule="R-HYPOTHETIC",
            topic=Topic.DOCUMENTATION,
            intent=Intent.WORKFLOW_DOCUMENTATION if families
            else Intent.RAG_QUESTION,
            mode=InteractionMode.INFORMATIONAL,
            explicitness=(Explicitness.QUOTED_EXAMPLE if prompt_writing
                          else Explicitness.HYPOTHETICAL),
            reason_codes=(ReasonCode.HYPOTHETICAL,) + (
                (ReasonCode.QUOTED_EXAMPLE,) if prompt_writing else ()),
            families=families or (Topic.GENERAL,),
            consequential_operations=(),
        )

    def _rule_quoted(self, scan: _MessageScan
                     ) -> Optional[DeterministicResult]:
        if not scan.removed_quoted:
            return None
        # Fires only when the masked-out content carried the workflow
        # signal and nothing actionable remains in the visible text.
        if scan.effective_matches:
            return None
        if not self._any_workflow_vocab(scan.removed_quoted):
            return None
        families = tuple(sorted({
            t for t, pattern in self._family_patterns.items()
            if pattern.search(scan.removed_quoted)
        }, key=lambda t: t.value))
        return DeterministicResult(
            rule="R-QUOTED",
            topic=Topic.DOCUMENTATION,
            intent=Intent.WORKFLOW_DOCUMENTATION if families
            else Intent.RAG_QUESTION,
            mode=InteractionMode.INFORMATIONAL,
            explicitness=Explicitness.QUOTED_EXAMPLE,
            reason_codes=(ReasonCode.QUOTED_EXAMPLE, ReasonCode.CODE_BLOCK),
            families=families or (Topic.GENERAL,),
            consequential_operations=(),
        )

    def _rule_quote_framing(self, scan: _MessageScan
                            ) -> Optional[DeterministicResult]:
        # F-R2c: metalinguistic command-quoting framing (accepted R-QUOTED
        # veto, architecture §2).  "Quote this command: <cmd>" / "Citando
        # questo comando: <cmd>" presents <cmd> as an example to quote, never
        # an execution order.  Route informational; never the agent loop.
        text = " ".join(c.text for c in scan.clauses)
        if not _QUOTE_FRAMING_ANCHORS.search(text):
            return None
        families = tuple(sorted(
            {t for c in scan.clauses for t in c.family_nouns},
            key=lambda t: t.value))
        return DeterministicResult(
            rule="R-QUOTE-FRAMING",
            topic=Topic.DOCUMENTATION,
            intent=(Intent.WORKFLOW_DOCUMENTATION
                    if families else Intent.RAG_QUESTION),
            mode=InteractionMode.INFORMATIONAL,
            explicitness=Explicitness.QUOTED_EXAMPLE,
            reason_codes=(ReasonCode.QUOTED_EXAMPLE,),
            families=families or (Topic.GENERAL,),
            consequential_operations=(),
        )

    def _rule_command(self, scan: _MessageScan
                      ) -> Optional[DeterministicResult]:
        if scan.is_multi_intent:
            return None  # TR59-TR66: clarify, execute nothing.
        matches = [m for c in scan.clauses for m in c.command_matches]
        strong = [m for m in matches if m.strong and m.intent is not None]
        if strong:
            # Noun-based matches express the operation more precisely than
            # identifier-based ones ("approve the ACP version" is an ACP
            # version approval, not a cohort approval).
            ordered = sorted(
                strong, key=lambda m: (m.clause_index, not m.noun_based))
            first = ordered[0]
            if first.consequential:
                mode = (InteractionMode.DESTRUCTIVE_MUTATION
                        if first.intent in _DESTRUCTIVE_INTENTS
                        else InteractionMode.MUTATION)
                return DeterministicResult(
                    rule="R-COMMAND",
                    topic=first.family,
                    intent=first.intent,
                    mode=mode,
                    explicitness=Explicitness.EXPLICIT,
                    reason_codes=(ReasonCode.EXPLICIT_ACTION_VERB,),
                    families=(first.family,),
                    consequential_operations=(first.operation_key,),
                    resource_reference=first.explicit_resource,
                )
            return DeterministicResult(
                rule="R-COMMAND",
                topic=first.family,
                intent=first.intent,
                mode=InteractionMode.ANALYSIS,
                explicitness=Explicitness.EXPLICIT,
                reason_codes=(ReasonCode.EXPLICIT_ACTION_VERB,),
                families=(first.family,),
                consequential_operations=(),
                resource_reference=first.explicit_resource,
            )
        # Recognized workflow vocabulary with no C1 intent: fail closed
        # (module note 4 — import rejection, deactivation).
        unavailable = [m for m in matches if m.strong and m.intent is None]
        if unavailable:
            ordered = sorted(
                unavailable, key=lambda m: (m.clause_index,
                                            not m.noun_based))
            first = ordered[0]
            return DeterministicResult(
                rule="R-COMMAND",
                topic=first.family,
                intent=Intent.CLARIFICATION_REQUIRED,
                mode=InteractionMode.UNKNOWN,
                explicitness=Explicitness.EXPLICIT,
                reason_codes=(first.reason,),
                families=(first.family,),
                consequential_operations=((first.operation_key,)
                                          if first.consequential else ()),
                unavailable_vocabulary=True,
            )
        # E-D1 (owner decision E-D1): a recognized consequential operation
        # verb with a missing, generic, unresolved, or invalid resource
        # remains a consequential request.  It is NOT classifier-eligible
        # non-adjacent ambiguity — the deterministic engine produces an
        # equivalent typed consequential candidate and the pipeline's
        # guard then fails closed to clarification.  Bare affirmatives are
        # excluded (they are Phase C atomic-claim candidates, not
        # consequential commands).
        if (not scan.is_bare_affirmative
                and not scan.is_multi_intent):
            # An interrogative message (can Retriva / does the gateway / …)
            # with a consequential verb is an informational question, not a
            # command (owner decision D-2c): let the later R-QUESTION rule
            # classify it as RAG instead of a consequential candidate.
            question_text = " ".join(c.text for c in scan.clauses)
            if (_QUESTION_ANCHORS.search(question_text)
                    or _STATUS_QUESTION_ANCHORS.search(question_text)):
                return None
            cons_candidates = [m for m in matches if m.consequential]
            if cons_candidates:
                ordered = sorted(
                    cons_candidates,
                    key=lambda m: (m.clause_index, not m.noun_based))
                first = ordered[0]
                fams = tuple(sorted(
                    {t for c in scan.clauses for t in c.family_nouns},
                    key=lambda t: t.value)) or (Topic.GENERAL,)
                # Typed consequential candidate (E-D1): the deterministic
                # engine recognizes a consequential operation verb whose
                # resource is missing, generic, unresolved, or invalid and
                # fails closed to clarification — never classifier-eligible,
                # never a classifier call.  The actual consequential intent
                # is recorded in ``consequential_operations``; the route is
                # CLARIFICATION_REQUIRED carrying CONSEQUENTIAL_CANDIDATE so
                # the pipeline's defense-in-depth (eligible_for_classification
                # and is_consequential_candidate) and the classifier bypass
                # reason (classifier_bypass_reason) agree deterministically,
                # independent of whether the verb has a C1 intent of its own.
                return DeterministicResult(
                    rule="R-COMMAND",
                    topic=first.family,
                    intent=Intent.CLARIFICATION_REQUIRED,
                    mode=InteractionMode.UNKNOWN,
                    explicitness=Explicitness.EXPLICIT,
                    reason_codes=(ReasonCode.CONSEQUENTIAL_CANDIDATE,),
                    families=fams,
                    consequential_operations=(first.operation_key,),
                    resource_reference=None,
                    unavailable_vocabulary=(first.intent is None),
                )
        return None

    def _rule_question(self, scan: _MessageScan
                       ) -> Optional[DeterministicResult]:
        if scan.is_multi_intent:
            return None
        text = " ".join(c.text for c in scan.clauses)
        if not (_QUESTION_ANCHORS.search(text)
                or _STATUS_QUESTION_ANCHORS.search(text)):
            return None
        families = tuple(sorted({
            t for c in scan.clauses for t in c.family_nouns
        }, key=lambda t: t.value))
        if not families:
            return None
        status = bool(_STATUS_QUESTION_ANCHORS.search(text))
        return DeterministicResult(
            rule="R-QUESTION",
            topic=Topic.DOCUMENTATION,
            intent=(Intent.STATUS_EXPLANATION if status
                    else Intent.CAPABILITY_QUESTION),
            mode=InteractionMode.INFORMATIONAL,
            explicitness=Explicitness.IMPLICIT,
            reason_codes=(ReasonCode.STATUS_QUESTION if status
                          else ReasonCode.CAPABILITY_QUESTION,),
            families=families,
            consequential_operations=(),
        )

    def _rule_multi_intent(self, scan: _MessageScan
                           ) -> Optional[DeterministicResult]:
        if not scan.is_multi_intent:
            return None
        families = tuple(sorted(
            {m.family for m in scan.effective_matches}
            | {t for c in scan.clauses
               if (c.doc_framed or c.hypothetical) and c.family_nouns
               for t in c.family_nouns},
            key=lambda t: t.value))
        return DeterministicResult(
            rule="R-MULTI-INTENT",
            topic=Topic.GENERAL,
            intent=Intent.CLARIFICATION_REQUIRED,
            mode=InteractionMode.UNKNOWN,
            explicitness=Explicitness.AMBIGUOUS,
            reason_codes=(ReasonCode.MULTI_INTENT,),
            families=families or (Topic.GENERAL,),
            consequential_operations=tuple(
                m.operation_key for m in scan.effective_matches
                if m.consequential),
        )

    def _rule_followup(self, scan: _MessageScan
                       ) -> Optional[DeterministicResult]:
        """Abstains in Phase B (registry arrives in Phase C; fail closed).

        Follow-up-shaped turns fall through to the AMBIGUOUS default
        carrying ``FOLLOWUP_CONTEXT`` — clarifying when workflow-adjacent,
        RAG when they carry no workflow signal (bare "yes", legacy parity).
        """
        return None

    def _rule_unsupported(self, scan: _MessageScan
                          ) -> Optional[DeterministicResult]:
        text = " ".join(c.text for c in scan.clauses)
        if not _UNSUPPORTED_PATTERNS.search(text):
            return None
        return DeterministicResult(
            rule="R-UNSUPPORTED",
            topic=Topic.GENERAL,
            intent=Intent.UNSUPPORTED,
            mode=InteractionMode.UNKNOWN,
            explicitness=Explicitness.EXPLICIT,
            reason_codes=(ReasonCode.UNSUPPORTED_OPERATION,),
            families=(Topic.GENERAL,),
            consequential_operations=(),
        )

    # -- default ------------------------------------------------------------

    def _ambiguous_default(self, scan: _MessageScan) -> DeterministicResult:
        if scan.is_followup_shape and scan.workflow_adjacent:
            reason = ReasonCode.FOLLOWUP_CONTEXT
        elif scan.workflow_adjacent:
            reason = ReasonCode.WORKFLOW_ADJACENT
        else:
            reason = ReasonCode.NON_ADJACENT_AMBIGUITY
        result = self._ambiguous(scan.families_present,
                                scan.consequential_keys, reason)
        if reason is ReasonCode.FOLLOWUP_CONTEXT:
            # Phase C: expose the weak follow-up's matched operations
            # (pronoun / generic-resource object) so the typed
            # workflow-context registry can resolve the resource.  The
            # weak match is detection-only — the registry, never the
            # engine, supplies the resource; the registry's allowed-next
            # hints arbitrate among candidate operations (e.g.
            # "approve" matching both the cohort and the version
            # approval specs) in closed deterministic order.
            candidates: List[Intent] = []
            for match in scan.effective_matches:
                if (match.intent is not None
                        and match.intent not in candidates):
                    candidates.append(match.intent)
            if candidates:
                return DeterministicResult(
                    rule=result.rule, topic=result.topic,
                    intent=result.intent, mode=result.mode,
                    explicitness=result.explicitness,
                    reason_codes=result.reason_codes,
                    families=result.families,
                    consequential_operations=(
                        result.consequential_operations),
                    resource_reference=result.resource_reference,
                    unavailable_vocabulary=(
                        result.unavailable_vocabulary),
                    followup_intents=tuple(candidates))
        return result

    def _ambiguous(self, families: Sequence[Topic],
                   consequential: Sequence[str],
                   reason: ReasonCode) -> DeterministicResult:
        return DeterministicResult(
            rule="R-DEFAULT",
            topic=families[0] if families else Topic.GENERAL,
            intent=Intent.AMBIGUOUS,
            mode=InteractionMode.UNKNOWN,
            explicitness=Explicitness.AMBIGUOUS,
            reason_codes=(ReasonCode.NO_DETERMINISTIC_MATCH, reason),
            families=tuple(families) or (Topic.GENERAL,),
            consequential_operations=tuple(consequential),
        )
