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

"""Workflow-context registry + PendingConfirmation (Spec 001 Phase C).

Two strictly separated typed concepts (owner decisions U-1/U-2, the
Phase C entry addendum D-1..D-6, 2026-10-01):

- ``WorkflowContext`` — ROUTING STATE ONLY: one ordinary resource
  reference per ``(tenant_id, session_id, kb_id)`` key, with optional
  provenance-labeled status hints.  It never authorizes a consequential
  operation; it assists explicit-verb follow-up resolution only.
- ``PendingConfirmation`` — ROUTING EVIDENCE ONLY, created EXCLUSIVELY
  by ``from_validated_outcome`` from an accepted, strictly validated
  ConfirmationReadyOutcome block (Gate C0 contract) plus trusted
  Gateway context.  The governing invariant: *a validated
  ConfirmationReadyOutcome is the only source from which a
  PendingConfirmation may be created* — never message content,
  operation verbs, opaque identifiers alone, routing decisions,
  conversation history, model prose, loose tool-result dictionaries,
  classifier output, KB selection, arbitrary metadata, custom request
  fields, or Gateway-generated domain assertions.

Claims are atomic PENDING -> CLAIMED under the registry lock, with a
server-minted ``claim_id`` and a deterministic
``execution_idempotency_key`` (addendum D-1: SHA-256 over canonical
trusted fields — claim correlation identifiers are audit fields only
and are never hashed into the key).  The immutable
``ClaimedConfirmationContext`` is server-only and scoped to one
agent-loop execution.  The final domain operation repeats every
authorization and authoritative-state validation; nothing here is
mutation authority.

Registry bounds (addendum D-5, process-global, startup-validated):
200 records, 30-minute context TTL, confirmation deadline capped at
900 seconds.  Expired-first purge; typed fail-closed capacity
rejection; no silent live eviction; no persistence — process restart
invalidates everything.  Statistics are content-free and process-local
only (Phase E owns publication).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .confirmation_ready import ConfirmationReadyBlock

# ---------------------------------------------------------------------------
# Closed constants
# ---------------------------------------------------------------------------

#: Domain-separation marker for the execution-idempotency derivation
#: (addendum D-1; closed literal — never user/model content).
_IDEMPOTENCY_DOMAIN_MARKER = "retriva-acp-activation-claim/v1"

#: Hard cap on the service-provided confirmation lifetime (D-5).
MAX_CONFIRMATION_LIFETIME_SECONDS = 900

#: Bounded retention for terminal CLAIMED records: removed at the next
#: expired-first purge sweep or when a new record replaces the key
#: (attach/observe-time cleanup), whichever comes first (D-6).


class ConfirmationState(str, Enum):
    """Closed lifecycle: PENDING -> CLAIMED.  No other state exists."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"


# ---------------------------------------------------------------------------
# Typed keys and records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowContextKey:
    """Trusted registry key: every field from trusted request context.

    tenant_id = the startup-validated DEFAULT_TENANT_ID (owner decision
    U-3, single-tenant deployment); session_id = the trusted request
    session or the server-synthesized ``sess_<correlation>``; kb_id =
    the resolved trusted request KB.  Never derived from message
    content, model output, tool arguments, custom metadata, classifier
    output, or untrusted headers.
    """

    tenant_id: str
    session_id: str
    kb_id: str


@dataclass
class PendingConfirmation:
    """Typed pending confirmation — routing evidence, never authority.

    Constructed ONLY via :func:`from_validated_outcome` (the single
    creation path).  Single-use (PENDING -> CLAIMED, terminal); no
    renewal function exists; never restored after claim or failure.
    """

    context_key: WorkflowContextKey
    principal_id: str
    family: str
    operation: str
    resource_type: str
    resource_id: str
    authoritative_version: int
    expected_authoritative_state: str
    allowed_next_transition: str
    preparation_transition_token: str
    created_at: datetime
    claim_deadline: datetime
    producing_correlation_id: str
    producing: str
    state: ConfirmationState = ConfirmationState.PENDING

    def equivalent(self, other: "PendingConfirmation") -> bool:
        """Exact-duplicate test (D-6): EVERY bound field matches."""
        return (
            self.context_key == other.context_key
            and self.principal_id == other.principal_id
            and self.family == other.family
            and self.operation == other.operation
            and self.resource_type == other.resource_type
            and self.resource_id == other.resource_id
            and self.authoritative_version == other.authoritative_version
            and self.expected_authoritative_state
            == other.expected_authoritative_state
            and self.allowed_next_transition
            == other.allowed_next_transition
            and self.preparation_transition_token
            == other.preparation_transition_token
            and self.producing == other.producing
        )

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.claim_deadline


def from_validated_outcome(
        block: ConfirmationReadyBlock,
        key: WorkflowContextKey,
        *,
        now: Optional[datetime] = None) -> PendingConfirmation:
    """The ONLY PendingConfirmation construction path.

    Input is the accepted, strictly validated ConfirmationReadyOutcome
    (Gate C0) plus the trusted Gateway key.  Every bound field is taken
    verbatim from the validated block — the deadline is
    ``created_at + confirmation_lifetime_seconds`` capped at 900 s.
    """
    produced_at = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(
        block.created_at.strip().replace("Z", "+00:00"))
    lifetime = min(
        int(block.confirmation_lifetime_seconds),
        MAX_CONFIRMATION_LIFETIME_SECONDS)
    deadline = min(created + timedelta(seconds=lifetime),
                   produced_at + timedelta(
                       seconds=MAX_CONFIRMATION_LIFETIME_SECONDS))
    return PendingConfirmation(
        context_key=key,
        principal_id=block.principal_id,
        family=block.workflow_family,
        operation=block.operation,
        resource_type=block.resource_type,
        resource_id=block.resource_id,
        authoritative_version=block.authoritative_version,
        expected_authoritative_state=block.expected_authoritative_state,
        allowed_next_transition=block.allowed_next_transition,
        preparation_transition_token=block.preparation_transition_token,
        created_at=created,
        claim_deadline=deadline,
        producing_correlation_id=block.correlation_id,
        producing=f"{block.producing_service}/{block.producing_operation}")


@dataclass(frozen=True)
class ClaimedConfirmationContext:
    """Server-only, immutable claimed execution context (addendum D-3).

    Created ONLY by a successful atomic claim; never accepted from
    request bodies, tool arguments, or the model; scoped to ONE
    agent-loop execution and cleared at loop completion; never
    serialized into tool results and never logged in full.  The
    model-visible trusted-context line may expose only operation,
    resource type, resource ID, authoritative version, and expected
    state (see :meth:`model_visible_line`).
    """

    claim_id: str
    tenant_id: str
    principal_id: str
    session_id: str
    kb_id: str
    operation: str
    resource_type: str
    resource_id: str
    authoritative_version: int
    expected_authoritative_state: str
    allowed_next_transition: str
    preparation_transition_token: str
    execution_idempotency_key: str
    producing_correlation_id: str

    def model_visible_line(self) -> str:
        """The ONLY model-visible projection (addendum D-3): the five
        permitted fields.  Never the claim ID, preparation token,
        idempotency key, tenant, principal, session, KB, or internal
        correlations."""
        return (
            f"- confirmed operation context (already prepared and "
            f"approved by you in this session): "
            f"operation={self.operation} "
            f"resource_type={self.resource_type} "
            f"resource_id={self.resource_id} "
            f"version={self.authoritative_version} "
            f"expected_state={self.expected_authoritative_state}. "
            f"Call the matching tool with exactly these arguments.")


def mint_claim_id() -> str:
    """Cryptographically strong server-side claim id (D-1)."""
    return f"cnfclm_{secrets.token_hex(16)}"


def derive_execution_idempotency_key(
        claimed: ClaimedConfirmationContext) -> str:
    """Deterministic execution idempotency key (addendum D-1).

    First 128 bits of SHA-256 over canonical sorted-key compact JSON of
    EXACTLY: domain-separation marker, tenant_id, principal_id,
    session_id, operation, resource_type, resource_id,
    authoritative_version, preparation_transition_token, claim_id.
    Excluded by construction: request correlation, producing
    correlation, timestamps, KB metadata, message content, model
    output, tool arguments, custom metadata, classifier output, and
    user-supplied idempotency data.  The same immutable claimed context
    always yields the same key; a new claim mints a new claim_id and
    therefore a different key; the preparation token is an INPUT and
    is never the key itself.
    """
    payload = json.dumps(
        {
            "marker": _IDEMPOTENCY_DOMAIN_MARKER,
            "tenant_id": claimed.tenant_id,
            "principal_id": claimed.principal_id,
            "session_id": claimed.session_id,
            "operation": claimed.operation,
            "resource_type": claimed.resource_type,
            "resource_id": claimed.resource_id,
            "authoritative_version": claimed.authoritative_version,
            "preparation_transition_token":
                claimed.preparation_transition_token,
            "claim_id": claimed.claim_id,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"idem_{digest}"


@dataclass
class WorkflowContext:
    """One ordinary resource reference per key (owner clarification).

    Routing state ONLY: never authorizes a consequential operation.
    Never contains evidence content, ACP payloads, provider responses,
    file contents, secrets, model prose, user metadata, arbitrary
    domain responses, or authorization decisions.
    """

    family: str
    resource_type: str
    resource_id: str
    last_operation: str
    observed_at: datetime
    # Provenance-labeled, closed-vocabulary routing hints only.
    status_class_hint: Optional[str] = None
    allowed_next_hints: Tuple[str, ...] = ()
    pending_confirmation: Optional[PendingConfirmation] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    record_version: int = 1


# ---------------------------------------------------------------------------
# Closed routing-hint projection (ordinary context only)
# ---------------------------------------------------------------------------

#: Deterministic allowed-next hints per observed operation (closed
#: table; routing hints only — the domain re-validates every
#: transition).  Families without an entry get no hints and therefore
#: no explicit follow-up resolution (fail closed as today).
_ALLOWED_NEXT: Dict[str, Tuple[str, ...]] = {
    "ACP_COHORT_PROPOSAL": ("ACP_COHORT_REVIEW",),
    "ACP_COHORT_REVIEW": ("ACP_COHORT_APPROVAL",),
    "ACP_REVIEW": ("ACP_APPROVAL",),
    "ACP_APPROVAL": ("ACP_ACTIVATION",),
    "ACP_ACTIVATION": ("ACP_ROLLBACK", "ACP_SUPERSESSION"),
    "ACP_EVIDENCE_ENRICHMENT": ("ACP_EVIDENCE_ENRICHMENT_STATUS",
                                "ACP_EVIDENCE_ACCEPTANCE"),
    "ACP_EVIDENCE_ENRICHMENT_STATUS": ("ACP_EVIDENCE_ACCEPTANCE",),
    "ACP_EVIDENCE_ACCEPTANCE": (),
}


@dataclass(frozen=True)
class ResolvedReference:
    """An ordinary-context resource resolution for an explicit
    follow-up.  Routing assistance only — never authorization; the
    consequential tool repeats its domain checks."""

    family: str
    operation: str
    resource_type: str
    resource_id: str


#: Closed resource-type mapping from the opaque identifier prefix
#: (routing hints only; mirrors the engine's family prefixes).
_RESOURCE_TYPE_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("acpver_", "acp_version"),
    ("cohver_", "cohort_version"),
    ("cohort_", "cohort"),
    ("ench_", "evidence_enrichment_job"),
    ("job_", "qualification_job"),
    ("batch_", "import_batch"),
    ("camp_", "campaign"),
)


def resource_type_for(resource_id: str) -> str:
    """Closed resource-type lookup by opaque prefix ('' when unknown —
    the record then simply carries the raw id as its hint)."""
    rid = resource_id or ""
    for prefix, resource_type in _RESOURCE_TYPE_PREFIXES:
        if rid.startswith(prefix):
            return resource_type
    return ""


# ---------------------------------------------------------------------------
# Typed outcomes (closed)
# ---------------------------------------------------------------------------

class AttachOutcome(str, Enum):
    """Closed confirmation-attachment outcomes (D-6)."""

    ATTACHED = "attached"
    DUPLICATE = "duplicate"          # exact duplicate: idempotent no-op
    CONFLICT = "conflict"            # live non-equivalent: typed conflict
    CAPACITY = "capacity"            # registry full after purge


class ClaimRejection(str, Enum):
    """Closed claim rejections (fail-closed clarify reasons)."""

    NO_CONFIRMATION = "no_confirmation"
    AMBIGUOUS = "ambiguous"           # more than one eligible
    EXPIRED = "expired"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    KEY_MISMATCH = "key_mismatch"
    STATE_MISMATCH = "state_mismatch"


@dataclass(frozen=True)
class ClaimResult:
    """Atomic claim outcome: exactly one of claimed/rejection."""

    claimed: Optional[ClaimedConfirmationContext] = None
    rejection: Optional[ClaimRejection] = None

    @property
    def succeeded(self) -> bool:
        return self.claimed is not None


@dataclass(frozen=True)
class RegistryStatsSnapshot:
    """Content-free, process-local statistics (TR81-TR83 proof only).

    Counts and timestamps only — no identifiers, no content, no metric
    names as a public contract, no endpoint, no exporter, no
    persistence (Phase E owns publication).
    """

    entries_total: int
    pending_total: int
    claimed_total: int
    expired_purged_total: int
    capacity_rejections_total: int
    attach_conflicts_total: int
    denied_ordinary_writes_total: int
    successful_claims_total: int
    last_purge_at: Optional[datetime]


# Closed clarification templates (content-free; no resource data).
BARE_AFFIRMATIVE_NO_CONFIRMATION = (
    "There is no pending confirmation for this session. To run a "
    "workflow operation, state it explicitly — for example, name the "
    "resource and the operation you want.")
BARE_AFFIRMATIVE_AMBIGUOUS = (
    "More than one operation is pending confirmation in this session. "
    "State explicitly which resource and operation you mean.")
CLAIM_EXPIRED = (
    "The pending confirmation has expired. The preparation must be "
    "repeated before the operation can be confirmed.")


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

class WorkflowContextRegistry:
    """In-process, thread-safe, bounded, non-persistent registry.

    Bounds (D-5): max contexts, context TTL, and the confirmation
    lifetime cap are process-global, startup-validated settings — they
    cannot vary by tenant, principal, session, KB, request, metadata,
    message, classifier, or model.
    """

    def __init__(self, *, max_contexts: int = 200,
                 context_ttl_seconds: int = 1800,
                 confirmation_max_lifetime_seconds:
                 int = MAX_CONFIRMATION_LIFETIME_SECONDS) -> None:
        if max_contexts <= 0 or context_ttl_seconds <= 0:
            raise ValueError("registry bounds must be positive")
        if not 1 <= confirmation_max_lifetime_seconds \
                <= MAX_CONFIRMATION_LIFETIME_SECONDS:
            raise ValueError(
                "confirmation lifetime cap must be within 1..900 seconds")
        self._max_contexts = int(max_contexts)
        self._ttl = timedelta(seconds=context_ttl_seconds)
        self._confirmation_cap = int(confirmation_max_lifetime_seconds)
        self._lock = threading.Lock()
        self._contexts: Dict[WorkflowContextKey, WorkflowContext] = {}
        self._expired_purged = 0
        self._capacity_rejections = 0
        self._attach_conflicts = 0
        self._denied_ordinary_writes = 0
        self._successful_claims = 0
        self._last_purge: Optional[datetime] = None

    # -- bounds helpers ---------------------------------------------------

    def _record_expired(self, record: WorkflowContext,
                        now: datetime) -> bool:
        """A record is expired when its own expiry passed.  A record
        carrying a PENDING confirmation is created with
        ``expires_at = max(record TTL, claim_deadline)``, so a live
        confirmation may extend its containing record only to its own
        bounded deadline — never beyond it."""
        return now >= record.expires_at

    def _purge_expired_locked(self, now: datetime) -> None:
        """Expired-first purge (TR81): deterministic order — oldest
        expiry first.  Live records are never silently evicted."""
        expired = sorted(
            ((r.expires_at, k, r) for k, r in self._contexts.items()
             if self._record_expired(r, now)),
            key=lambda item: (item[0], item[1].session_id,
                              item[1].kb_id))
        for _, key, _record in expired:
            del self._contexts[key]
            self._expired_purged += 1
        if expired:
            self._last_purge = now

    def peek_context(self, key: WorkflowContextKey,
                     ) -> Optional[WorkflowContext]:
        """Non-mutating record access for privacy-safe categorical
        summaries (Phase D classifier context hints).  Purge-free and
        lock-free read of the live record; callers extract presence
        booleans and the closed family hint ONLY (Spec 001 §Phase D
        privacy boundary)."""
        with self._lock:
            record = self._contexts.get(key)
            if record is None:
                return None
            # Shallow copy so the caller never mutates registry state.
            return WorkflowContext(
                family=record.family,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                last_operation=record.last_operation,
                observed_at=record.observed_at,
                status_class_hint=record.status_class_hint,
                allowed_next_hints=record.allowed_next_hints,
                pending_confirmation=record.pending_confirmation,
                created_at=record.created_at,
                expires_at=record.expires_at,
                record_version=record.record_version)

    # -- ordinary context (routing hints only) ----------------------------

    def observe_command(self, key: WorkflowContextKey, family: str,
                       resource_type: str, resource_id: str,
                       operation: str,
                       now: Optional[datetime] = None) -> bool:
        """Ordinary-context write (deterministic adapter; hints only).

        Last-observation-wins applies ONLY to non-authoritative routing
        hints, and ONLY while no live PENDING confirmation occupies the
        record: while a confirmation is PENDING the write is DENIED —
        replacing ordinary context can never overwrite, detach, or
        invalidate a live pending confirmation.  A CLAIMED (terminal)
        confirmation is removed by bounded cleanup first; cleanup never
        restores it to PENDING.
        """
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            existing = self._contexts.get(key)
            if existing is not None:
                pending = existing.pending_confirmation
                if pending is not None:
                    if pending.state is ConfirmationState.PENDING:
                        if not self._record_expired(existing, moment):
                            self._denied_ordinary_writes += 1
                            return False
                    else:
                        # Terminal CLAIMED: bounded cleanup (never
                        # restored to PENDING).
                        self._expired_purged += 1
            if len(self._contexts) >= self._max_contexts:
                self._capacity_rejections += 1
                return False
            self._contexts[key] = WorkflowContext(
                family=family,
                resource_type=resource_type,
                resource_id=resource_id,
                last_operation=operation,
                observed_at=moment,
                status_class_hint=None,
                allowed_next_hints=_ALLOWED_NEXT.get(operation, ()),
                pending_confirmation=None,
                created_at=moment,
                expires_at=moment + self._ttl,
                record_version=(existing.record_version + 1)
                if existing else 1)
            return True

    def resolve_follow_up(self, key: WorkflowContextKey,
                          family: Optional[str],
                          operation: str,
                          now: Optional[datetime] = None
                          ) -> Optional[ResolvedReference]:
        """Explicit-verb follow-up resolution (routing assistance only).

        Requires: a record exists under the key; when the message
        carries a family signal (``family`` not None) the record's
        family matches; the record's allowed-next hints permit the
        requested operation; no pending-confirmation conflict exists (a
        PENDING confirmation is claimed via the bare-affirmative claim
        path instead — an explicit follow-up never claims).  Zero or
        ambiguous -> None (the pipeline clarifies; never guess).  The
        record is the unique candidate under the key (one resource per
        key), so a family-less pronoun follow-up resolves against the
        record's own family.
        """
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            record = self._contexts.get(key)
            if record is None:
                return None
            if family is not None and record.family != family:
                return None
            if operation not in record.allowed_next_hints:
                return None
            if (record.pending_confirmation is not None
                    and record.pending_confirmation.state
                    is ConfirmationState.PENDING):
                return None
            return ResolvedReference(
                family=record.family,
                operation=operation,
                resource_type=record.resource_type,
                resource_id=record.resource_id)

    # -- confirmation attachment (observer only) ---------------------------

    def attach_confirmation(
            self, key: WorkflowContextKey,
            block: ConfirmationReadyBlock,
            now: Optional[datetime] = None) -> AttachOutcome:
        """Attach a PendingConfirmation built from a VALIDATED outcome.

        Insertion policy (D-6): purge expired first; no live pending ->
        attach; exact duplicate (every bound field including the
        preparation token) -> idempotent no-op (expiry never reset);
        live non-equivalent -> typed conflict, no write, content-free
        counter, affected routing degrades to clarification;
        latest-wins is PROHIBITED.  A terminal CLAIMED record is
        removed by bounded cleanup first.
        """
        moment = now or datetime.now(timezone.utc)
        confirmation = from_validated_outcome(block, key, now=moment)
        with self._lock:
            self._purge_expired_locked(moment)
            existing = self._contexts.get(key)
            if existing is not None:
                pending = existing.pending_confirmation
                if pending is not None:
                    if pending.state is ConfirmationState.PENDING:
                        if not self._record_expired(existing, moment):
                            if pending.equivalent(confirmation):
                                return AttachOutcome.DUPLICATE
                            self._attach_conflicts += 1
                            return AttachOutcome.CONFLICT
                    else:
                        # Terminal CLAIMED: bounded cleanup.
                        self._expired_purged += 1
                        existing = None
            if len(self._contexts) >= self._max_contexts:
                self._capacity_rejections += 1
                return AttachOutcome.CAPACITY
            ttl = self._ttl
            record_deadline = confirmation.claim_deadline
            expires = max(moment + ttl, record_deadline)
            if existing is not None:
                self._contexts[key] = WorkflowContext(
                    family=confirmation.family,
                    resource_type=confirmation.resource_type,
                    resource_id=confirmation.resource_id,
                    last_operation="ACP_APPROVAL",
                    observed_at=moment,
                    status_class_hint=confirmation
                    .expected_authoritative_state,
                    allowed_next_hints=_ALLOWED_NEXT.get(
                        "ACP_APPROVAL", ()),
                    pending_confirmation=confirmation,
                    created_at=existing.created_at,
                    expires_at=expires,
                    record_version=existing.record_version + 1)
            else:
                self._contexts[key] = WorkflowContext(
                    family=confirmation.family,
                    resource_type=confirmation.resource_type,
                    resource_id=confirmation.resource_id,
                    last_operation="ACP_APPROVAL",
                    observed_at=moment,
                    status_class_hint=confirmation
                    .expected_authoritative_state,
                    allowed_next_hints=_ALLOWED_NEXT.get(
                        "ACP_APPROVAL", ()),
                    pending_confirmation=confirmation,
                    created_at=moment,
                    expires_at=expires,
                    record_version=1)
            return AttachOutcome.ATTACHED

    # -- authoritative-change invalidation (TR70) --------------------------

    def invalidate_for_resource(self, key: WorkflowContextKey,
                                resource_type: str, resource_id: str,
                                now: Optional[datetime] = None) -> bool:
        """Invalidate a PENDING confirmation after an observed
        authoritative state change (typed tool-outcome observer only).
        Never restores CLAIMED to PENDING; never creates authority."""
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            record = self._contexts.get(key)
            if record is None:
                return False
            pending = record.pending_confirmation
            if (pending is None or pending.state
                    is not ConfirmationState.PENDING
                    or pending.resource_type != resource_type
                    or pending.resource_id != resource_id):
                return False
            record.pending_confirmation = None
            record.record_version += 1
            return True

    def note_destructive_transition(self, key: WorkflowContextKey,
                                    family: str, resource_type: str,
                                    resource_id: str, operation: str,
                                    status_hint: str,
                                    now: Optional[datetime] = None) -> None:
        """Ordinary-context update after a typed destructive outcome
        (e.g. activation).  Hints only; the pending confirmation for
        the same resource is invalidated (authoritative change)."""
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            record = self._contexts.get(key)
            if record is None:
                if len(self._contexts) >= self._max_contexts:
                    self._capacity_rejections += 1
                    return
                record = WorkflowContext(
                    family=family, resource_type=resource_type,
                    resource_id=resource_id, last_operation=operation,
                    observed_at=moment, status_class_hint=status_hint,
                    allowed_next_hints=_ALLOWED_NEXT.get(operation, ()),
                    pending_confirmation=None, created_at=moment,
                    expires_at=moment + self._ttl, record_version=1)
                self._contexts[key] = record
                return
            pending = record.pending_confirmation
            if (pending is not None and pending.state
                    is ConfirmationState.PENDING
                    and pending.resource_type == resource_type
                    and pending.resource_id == resource_id):
                record.pending_confirmation = None
            record.family = family
            record.resource_type = resource_type
            record.resource_id = resource_id
            record.last_operation = operation
            record.observed_at = moment
            record.status_class_hint = status_hint
            record.allowed_next_hints = _ALLOWED_NEXT.get(operation, ())
            record.record_version += 1

    # -- claims (atomic PENDING -> CLAIMED) --------------------------------

    def eligible_confirmations(self, key: WorkflowContextKey,
                               now: Optional[datetime] = None
                               ) -> List[PendingConfirmation]:
        """Eligible = PENDING and unexpired, under the exact key."""
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            record = self._contexts.get(key)
            if record is None:
                return []
            pending = record.pending_confirmation
            if (pending is None or pending.state
                    is not ConfirmationState.PENDING
                    or moment >= pending.claim_deadline):
                return []
            return [pending]

    def claim(self, key: WorkflowContextKey, principal_id: str,
              now: Optional[datetime] = None) -> ClaimResult:
        """Atomic claim (addendum D-1/D-6; one record per key).

        Eligibility: zero eligible -> clarification (NO_CONFIRMATION);
        exactly one -> may claim; more than one -> clarification and
        claim none (no selection by latest, confidence, model
        preference, or classifier output — with one record per key
        there is at most one candidate; the ambiguity case is kept
        explicit and closed).

        Validation order inside the registry lock: context key; trusted
        current principal; family; operation; resource type; resource
        ID; authoritative version; expected authoritative state;
        allowed transition; claim deadline; state == PENDING.  First
        mismatch fails closed, leaving the confirmation unchanged
        unless expired.  On success the claim_id is minted INSIDE the
        claim transaction, the state transitions to terminal CLAIMED,
        the execution idempotency key is derived, and the immutable
        ClaimedConfirmationContext is returned.  Exactly one
        concurrent claimant can succeed.
        """
        moment = now or datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(moment)
            record = self._contexts.get(key)
            pending_list: List[PendingConfirmation] = []
            if record is not None and record.pending_confirmation \
                    is not None:
                p = record.pending_confirmation
                if p.state is ConfirmationState.PENDING:
                    pending_list.append(p)
            eligible = [p for p in pending_list
                        if moment < p.claim_deadline]
            if not eligible:
                if pending_list:
                    # Present but expired: fail closed (expired
                    # confirmations never act; TR71).
                    return ClaimResult(rejection=ClaimRejection.EXPIRED)
                return ClaimResult(
                    rejection=ClaimRejection.NO_CONFIRMATION)
            if len(eligible) > 1:
                return ClaimResult(rejection=ClaimRejection.AMBIGUOUS)
            confirmation = eligible[0]
            # 1. context key: the record was found under the exact key.
            # 2. trusted current principal:
            if not (principal_id or "").strip():
                return ClaimResult(
                    rejection=ClaimRejection.PRINCIPAL_MISMATCH)
            if confirmation.principal_id != principal_id:
                return ClaimResult(
                    rejection=ClaimRejection.PRINCIPAL_MISMATCH)
            # 3.-9. bound-field self-consistency (the confirmation was
            # built from a validated domain outcome; the fields are
            # re-asserted here so the claim result carries exactly the
            # bound transition the domain will re-validate):
            if (not confirmation.family or not confirmation.operation
                    or not confirmation.resource_type
                    or not confirmation.resource_id
                    or confirmation.authoritative_version <= 0
                    or not confirmation.expected_authoritative_state
                    or not confirmation.allowed_next_transition):
                return ClaimResult(rejection=ClaimRejection.KEY_MISMATCH)
            # 10. claim deadline (re-checked under the lock):
            if moment >= confirmation.claim_deadline:
                return ClaimResult(rejection=ClaimRejection.EXPIRED)
            # 11. state == PENDING (atomic; a concurrent winner has
            # already transitioned it to CLAIMED -> fail closed):
            if confirmation.state is not ConfirmationState.PENDING:
                return ClaimResult(
                    rejection=ClaimRejection.STATE_MISMATCH)
            claim_id = mint_claim_id()  # minted inside the transaction
            claimed = replace(
                ClaimedConfirmationContext(
                    claim_id=claim_id,
                    tenant_id=key.tenant_id,
                    principal_id=confirmation.principal_id,
                    session_id=key.session_id,
                    kb_id=key.kb_id,
                    operation=confirmation.operation,
                    resource_type=confirmation.resource_type,
                    resource_id=confirmation.resource_id,
                    authoritative_version=(
                        confirmation.authoritative_version),
                    expected_authoritative_state=(
                        confirmation.expected_authoritative_state),
                    allowed_next_transition=(
                        confirmation.allowed_next_transition),
                    preparation_transition_token=(
                        confirmation.preparation_transition_token),
                    execution_idempotency_key="",
                    producing_correlation_id=(
                        confirmation.producing_correlation_id)),
                execution_idempotency_key=derive_execution_idempotency_key(
                    ClaimedConfirmationContext(
                        claim_id=claim_id,
                        tenant_id=key.tenant_id,
                        principal_id=confirmation.principal_id,
                        session_id=key.session_id,
                        kb_id=key.kb_id,
                        operation=confirmation.operation,
                        resource_type=confirmation.resource_type,
                        resource_id=confirmation.resource_id,
                        authoritative_version=(
                            confirmation.authoritative_version),
                        expected_authoritative_state=(
                            confirmation.expected_authoritative_state),
                        allowed_next_transition=(
                            confirmation.allowed_next_transition),
                        preparation_transition_token=(
                            confirmation.preparation_transition_token),
                        execution_idempotency_key="",
                        producing_correlation_id=(
                            confirmation.producing_correlation_id))))
            record.pending_confirmation = PendingConfirmation(
                context_key=confirmation.context_key,
                principal_id=confirmation.principal_id,
                family=confirmation.family,
                operation=confirmation.operation,
                resource_type=confirmation.resource_type,
                resource_id=confirmation.resource_id,
                authoritative_version=confirmation.authoritative_version,
                expected_authoritative_state=(
                    confirmation.expected_authoritative_state),
                allowed_next_transition=(
                    confirmation.allowed_next_transition),
                preparation_transition_token=(
                    confirmation.preparation_transition_token),
                created_at=confirmation.created_at,
                claim_deadline=confirmation.claim_deadline,
                producing_correlation_id=(
                    confirmation.producing_correlation_id),
                producing=confirmation.producing,
                state=ConfirmationState.CLAIMED)
            record.record_version += 1
            self._successful_claims += 1
            return ClaimResult(claimed=claimed)

    # -- statistics (content-free, process-local) ---------------------------

    def snapshot(self) -> RegistryStatsSnapshot:
        """Content-free stats snapshot (TR81-TR83 proof only)."""
        with self._lock:
            pending = sum(
                1 for r in self._contexts.values()
                if r.pending_confirmation is not None
                and r.pending_confirmation.state
                is ConfirmationState.PENDING)
            claimed = sum(
                1 for r in self._contexts.values()
                if r.pending_confirmation is not None
                and r.pending_confirmation.state
                is ConfirmationState.CLAIMED)
            return RegistryStatsSnapshot(
                entries_total=len(self._contexts),
                pending_total=pending,
                claimed_total=claimed,
                expired_purged_total=self._expired_purged,
                capacity_rejections_total=self._capacity_rejections,
                attach_conflicts_total=self._attach_conflicts,
                denied_ordinary_writes_total=(
                    self._denied_ordinary_writes),
                successful_claims_total=self._successful_claims,
                last_purge_at=self._last_purge)


# ---------------------------------------------------------------------------
# Tool-outcome observer (the ONLY PendingConfirmation creation call site)
# ---------------------------------------------------------------------------

class ObservationOutcome(str, Enum):
    """Closed observer outcomes (content-free; loop logs these only)."""

    ATTACHED = "attached"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    CAPACITY = "capacity"
    REJECTED = "rejected"       # the C0 block failed re-validation
    INVALIDATED = "invalidated"  # authoritative change (TR70)
    NONE = "none"


def observe_tool_result(
        registry: WorkflowContextRegistry,
        *,
        tenant_id: str,
        session_id: str,
        kb_id: str,
        correlation_id: str,
        principal_id: str,
        tool_name: str,
        result: object,
        now: Optional[datetime] = None) -> ObservationOutcome:
    """Typed tool-outcome observation (Spec 001 Phase C).

    Integrated immediately after the trusted tool execution result is
    returned and BEFORE it is appended to the model-visible
    transcript.  PendingConfirmation is created ONLY when the result
    carries the accepted C0 ``confirmation_ready`` field, which already
    passed the tool-layer strict ingress validation — and the observer
    VALIDATES IT AGAIN against the same trusted context before
    attaching.  It is never created from arbitrary dictionaries,
    dictionary-key patterns, model text, assistant/user messages, chat
    summaries, ``next`` prose, routing decisions, status strings, or
    classifier results.  The ordinary-context projection updates
    routing hints only and never creates authority.

    Returns a closed, content-free outcome; the caller logs the outcome
    only (never identifiers, tokens, or payloads).
    """
    if not isinstance(result, dict):
        return ObservationOutcome.NONE
    if isinstance(result.get("error"), dict):
        return ObservationOutcome.NONE
    key = WorkflowContextKey(
        tenant_id=tenant_id, session_id=session_id, kb_id=kb_id)
    if tool_name == "approve_acp":
        block = result.get("confirmation_ready")
        if block is None:
            return ObservationOutcome.NONE
        from .confirmation_ready import (
            ConfirmationReadyRejection,
            validate_confirmation_ready,
        )
        outcome = validate_confirmation_ready(
            block, correlation_id=correlation_id,
            tenant_id=tenant_id, principal_id=principal_id)
        if isinstance(outcome, ConfirmationReadyRejection):
            return ObservationOutcome.REJECTED
        attach = registry.attach_confirmation(
            key, outcome, now=now)
        return ObservationOutcome(attach.value)
    if tool_name == "activate_acp":
        # Typed destructive outcome: the authoritative state changed —
        # any PENDING confirmation for the same resource is invalidated
        # (never restored), and ordinary routing hints advance.
        resource_id = str(result.get("acp_id") or "")
        if not resource_id:
            return ObservationOutcome.NONE
        registry.note_destructive_transition(
            key, family="ACP", resource_type="acp_version",
            resource_id=resource_id, operation="ACP_ACTIVATION",
            status_hint="ACTIVE", now=now)
        return ObservationOutcome.INVALIDATED
    return ObservationOutcome.NONE


# ---------------------------------------------------------------------------
# Process-global registry (mode off never touches it)
# ---------------------------------------------------------------------------

_REGISTRY: Optional[WorkflowContextRegistry] = None
_REGISTRY_INIT_LOCK = threading.Lock()


def get_workflow_context_registry() -> WorkflowContextRegistry:
    """The process-global registry, built from startup-validated
    settings (D-5).  Constructed lazily; mode ``off`` never calls this."""
    global _REGISTRY
    with _REGISTRY_INIT_LOCK:
        if _REGISTRY is None:
            from retriva_gateway.config import settings
            _REGISTRY = WorkflowContextRegistry(
                max_contexts=settings.AGENT_WORKFLOW_CONTEXT_MAX_ENTRIES,
                context_ttl_seconds=(
                    settings.AGENT_WORKFLOW_CONTEXT_TTL_SECONDS),
                confirmation_max_lifetime_seconds=(
                    settings.AGENT_CONFIRMATION_MAX_LIFETIME_SECONDS))
        return _REGISTRY


def reset_workflow_context_registry_for_tests(
        **overrides) -> WorkflowContextRegistry:
    """Test-only: a fresh registry (restart-empty behavior proof)."""
    global _REGISTRY
    with _REGISTRY_INIT_LOCK:
        _REGISTRY = WorkflowContextRegistry(**overrides) \
            if overrides else WorkflowContextRegistry()
        return _REGISTRY
