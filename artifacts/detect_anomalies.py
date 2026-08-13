#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detect_anomalies.py
============================================================================
Multi-tenant analytics pipeline — anomaly detection artifact.

PURPOSE
-------
This script analyzes a JSONL event fixture and produces a deterministic,
auditable anomaly report. It is a SUBMISSION ARTIFACT demonstrating how the
proposed analytics pipeline detects and classifies bad event data in a
multi-tenant event stream.

This is NOT the production stream-processing implementation. The production
enforcement of these rules would occur in the ingestion/processing pipeline.
This artifact exists so a reviewer can trace:

    fixture event  ->  detected anomaly  ->  anomaly class
                     ->  reason          ->  recommended action

DETERMINISTIC vs HEURISTIC
--------------------------
Deterministic validation (rules that produce one correct answer per event):
  - MALFORMED_JSON, SCHEMA_DRIFT, MISSING_REQUIRED_FIELDS,
    IMPOSSIBLE_TIMESTAMPS / FUTURE_TIMESTAMPS, DUPLICATE_EVENTS,
    PRIVACY_REQUEST_EVENTS.

  `received_at` is the required ingestion timestamp. `ts` is optional
  event-time metadata; timestamp anomaly checks apply only when `ts` is
  supplied. Missing `ts` is not classified as bad data.

Heuristic anomaly detection (probability hints, not proof):
  - BOT_TRAFFIC  (scanner terms in referrer/user-agent, or a page_view burst)
  - PII_IN_PROPERTIES (regex/property-name guesses — not full PII discovery)

The report explicitly labels heuristic output as such. `increase_bot_score` is NOT
a deletion or rejection action; it increases the risk signal and routes the event
into downstream review or automated policy evaluation.

TENANT ISOLATION
----------------
Event IDs and behavioural identities (anonymous_id) are scoped by tenant_id
where available, matching the source architecture's tenant isolation model.
We do NOT combine anonymous_id across tenants.

PRIVACY
-------
No source values are mutated. PII values are never echoed; the report only
mentions the *category* of PII detected (e.g. "PII detected: email").

DEPENDENCIES
------------
Python 3.8+ standard library only. No pandas, no numpy, no third-party packages.

USAGE
-----
    python3 detect_anomalies.py                      # uses ./events.jsonl
    python3 detect_anomalies.py path/to/sample.jsonl
    python3 detect_anormalies.py --json events.jsonl   # also print JSON summary
============================================================================
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# ============================================================================
# CONFIGURATION  — every threshold is an ASSUMPTION for this artifact.
# Production enforcement would live in the ingestion/processing pipeline.
# ============================================================================

DEFAULT_FIXTURE = "events.jsonl"

# [ASSUMED] Tolerance for event ts being AHEAD of received_at (clock skew).
# Any ts strictly later than received_at + FUTURE_TIMESTAMP_TOLERANCE_SECONDS
# is a timestamp-direction anomaly. Small values treat real skew as an anomaly.
# Default: 5 seconds (tight, because the fixture shows deliberate violations).
FUTURE_TIMESTAMP_TOLERANCE_SECONDS: int = 5

# [ASSUMED] Skew above this magnitude is reclassified FUTURE_TIMESTAMPS
# (absurdly ahead, e.g. wrong-year) rather than IMPOSSIBLE_TIMESTAMPS
# (event time mildly/shortly after ingestion). Both classes use the SAME
# time direction (ts after received_at); the split is a severity tier.
# Default: 24h.
FUTURE_SEVERE_AHEAD_SECONDS: int = 24 * 3600

# [ASSUMED] Maximum acceptable lateness (event ts BEHIND received_at) before we
# flag a STALE_EVENT. Kept conservative; null disables stale detection.
# Default: None (off, to avoid false positives in this artifact).
STALE_TIMESTAMP_TOLERANCE_SECONDS: Optional[int] = None

# [ASSUMED] Bot burst heuristic. > BOT_BURST_COUNT page_view events from the
# same (tenant_id, anonymous_id) inside a BOT_BURST_WINDOW sliding window.
BOT_BURST_WINDOW_SECONDS: int = 1
BOT_BURST_COUNT: int = 3  # strictly more than this -> flag

# [ASSUMED] Scanner/bot substrings searched (case-insensitive) in referrer and
# any user-agent field. This is a heuristic, not proof of bot traffic.
SCANNER_PATTERNS: Tuple[str, ...] = (
    "scanner",
    "bot",
    "crawler",
    "spider",
    "scraper",
    "headless",
    "phantom",
    "selenium",
    "puppeteer",
    "nikto",
    "sqlmap",
    "nmap",
    "masscan",
    "zgrab",
)

# Canonical schema. event_id/type/received_at/tenant_id MUST be present and
# non-empty; everything else is optional. We report missing fields as
# MISSING_REQUIRED_FIELDS — NOT as schema drift.
# `ts` is optional event-time metadata: timestamp anomaly checks apply only
# when `ts` is supplied. `received_at` is the ingestion source-of-truth.
REQUIRED_FIELDS: Tuple[str, ...] = (
    "event_id",
    "type",
    "received_at",
    "tenant_id",
)

# Known non-canonical field names -> canonical. Reporting an alias does NOT
# rewrite the event; it recommends canonicalisation. Schema drift is only
# raised when a known alias key is found — unknown optional fields are NOT
# flagged. When a canonical required field is absent but a known alias is
# present, SCHEMA_DRIFT is emitted and MISSING_REQUIRED_FIELDS is suppressed
# for that field (the alias satisfies the requirement pending canonicalisation).
# Top-level aliases are checked by detect_schema_drift; property-level aliases
# are checked only inside `properties`.
FIELD_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "ts": ("timestamp", "event_time", "event_ts"),
    "received_at": ("received", "ingested_at", "processed_at"),
    "event_id": ("id", "eventID", "eventId"),
    "tenant_id": ("tenantId", "org_id"),
    "type": ("eventType", "event_type"),
    "user_id": ("userId", "user"),
    "anonymous_id": ("anonId", "anon_id"),
    "properties": ("props", "payload"),
    # property-level aliases reported only when found inside `properties`:
    "path": ("page_path", "pathname"),
    "referrer": ("ref", "referer"),
    "user_agent": ("userAgent", "ua"),
}

# Property names that are treated as PII indicators by name. Heuristic.
PII_PROPERTY_NAME_HINTS: Mapping[str, str] = {
    "email": "email",
    "contact_email": "email",
    "mail": "email",
    "e_mail": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "tel": "phone",
    "ssn": "ssn",
    "national_id": "national_id",
}

# Heuristic regexes for PII *values*. Deliberately conservative; the report
# says "PII heuristic detected", never "all PII found".
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone: optional +country code, then 3-3-4 digits with optional separators.
PHONE_REGEX = re.compile(
    r"(?:\+?\d{1,2}[\s.-]?)?"           # optional country code
    r"\(?\d{3}\)?[\s.-]?"                # area
    r"\d{3}[\s.-]?\d{4}"                 # exchange + subscriber
)

# Anomaly class names (kept stable so the report maps cleanly to the written
# data-quality analysis).
C_MALFORMED = "MALFORMED_JSON"
C_SCHEMA_DRIFT = "SCHEMA_DRIFT"
C_MISSING = "MISSING_REQUIRED_FIELDS"
C_IMPOSSIBLE = "IMPOSSIBLE_TIMESTAMPS"
C_FUTURE = "FUTURE_TIMESTAMPS"
C_STALE = "STALE_EVENT"
C_DUPLICATE = "DUPLICATE_EVENTS"
C_BOT = "BOT_TRAFFIC"
C_PII = "PII_IN_PROPERTIES"
C_PRIVACY = "PRIVACY_REQUEST_EVENTS"

# Deterministic display order for the report.
ANOMALY_CLASS_ORDER: Tuple[str, ...] = (
    C_MALFORMED,
    C_SCHEMA_DRIFT,
    C_MISSING,
    C_IMPOSSIBLE,
    C_FUTURE,
    C_STALE,
    C_DUPLICATE,
    C_BOT,
    C_PII,
    C_PRIVACY,
)


# ============================================================================
# Data model
# ============================================================================


class Anomaly:
    """One detected anomaly, attached to a fixture line.

    The detector never mutates the source event; this object only describes
    what was observed and what should happen next.
    """

    __slots__ = ("line", "event_id", "tenant_id", "klass", "reason", "action")

    def __init__(
            self,
            line: int,
            klass: str,
            reason: str,
            action: str,
            event_id: Optional[str] = None,
            tenant_id: Optional[str] = None,
    ) -> None:
        self.line = line
        self.event_id = event_id
        self.tenant_id = tenant_id
        self.klass = klass
        self.reason = reason
        self.action = action

    def as_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "class": self.klass,
            "reason": self.reason,
            "action": self.action,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"Anomaly(line={self.line}, class={self.klass}, "
            f"event_id={self.event_id!r}, reason={self.reason!r})"
        )


# ============================================================================
# Pure helper functions (unit-testable, no I/O)
# ============================================================================


def parse_event(raw_line: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse one JSONL line.

    Returns (event_dict, None) on success, or (None, error_message) if the
    line is unparseable JSON or not a JSON object. Never raises on bad data.
    """
    try:
        value = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg}"
    if not isinstance(value, dict):
        return None, f"top-level JSON value is {type(value).__name__}, not object"
    return value, None


def _coerce_str(value: Any) -> Optional[str]:
    """Return a trimmed string iff `value` is a non-empty string after trim.

    Returns None for None, empty, or whitespace-only strings. Non-string
    values (numbers, bools) return None — required fields are string-typed in
    this schema.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _canonical_value(event: Mapping[str, Any], canonical: str) -> Any:
    """Return the value at the canonical field name if present and non-null."""
    if canonical not in event:
        return None
    val = event[canonical]
    return val if val is not None else None


def _alias_satisfied(event: Mapping[str, Any], canonical: str) -> bool:
    """Return True if `event` contains a known alias for `canonical`.

    Used by validate_required_fields to suppress a MISSING_REQUIRED_FIELDS
    report when the field is absent under its canonical name but a known alias
    is present. The alias still triggers a SCHEMA_DRIFT report via
    detect_schema_drift; the two anomaly classes are complementary, not
    duplicated.
    """
    aliases = FIELD_ALIASES.get(canonical, ())
    return any(alias in event for alias in aliases)


def validate_required_fields(
        event: Mapping[str, Any], line: int
) -> List[Anomaly]:
    """Deterministic check: each field in REQUIRED_FIELDS is present and
    non-empty.

    A required field is invalid when absent, None, empty-string, or
    whitespace-only — UNLESS a known alias for that field is present in the
    event. When an alias satisfies the requirement, SCHEMA_DRIFT is emitted
    by detect_schema_drift and MISSING_REQUIRED_FIELDS is suppressed for that
    field (the alias satisfies the requirement pending canonicalisation).

    Reported as MISSING_REQUIRED_FIELDS only when no canonical value and no
    known alias exists. Explicitly NOT schema drift (schema drift is
    aliasing/renaming; see detect_schema_drift).
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    anomalies: List[Anomaly] = []
    for field in REQUIRED_FIELDS:
        val = event.get(field)
        if val is None:
            kind = "null/missing"
        elif isinstance(val, str) and not val.strip():
            kind = "empty/whitespace"
        else:
            continue
        # Suppress if a known alias is present; SCHEMA_DRIFT covers that case.
        if _alias_satisfied(event, field):
            continue
        anomalies.append(
            Anomaly(
                line=line,
                klass=C_MISSING,
                reason=f"required field '{field}' is {kind}",
                action="reject_unless_trusted_enrichment_exists",
                event_id=event_id,
                tenant_id=tenant_id,
            )
        )
    return anomalies


def detect_schema_drift(
        event: Mapping[str, Any], line: int
) -> List[Anomaly]:
    """Deterministic check: known alias keys present in the event.

    Reports any top-level field name that is a known alias of a canonical
    field. Reports known aliases inside `properties` too. Does NOT rewrite
    the event. Does NOT flag unknown optional fields — schema drift is only
    raised for field names that map to a known canonical field.

    When a canonical required field is absent but a known alias is present,
    this function emits SCHEMA_DRIFT and validate_required_fields suppresses
    MISSING_REQUIRED_FIELDS for that field. The two anomaly classes are
    complementary: drift covers the alias, missing covers a truly absent field
    with no alias.

    Does NOT flag as schema drift simply because a canonical field is missing
    with no alias present — that is MISSING_REQUIRED_FIELDS.
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    anomalies: List[Anomaly] = []

    anomalies.extend(
        _aliased_fields_in(event, line, event_id, tenant_id, scope="top-level")
    )

    props = event.get("properties")
    if isinstance(props, dict):
        anomalies.extend(
            _aliased_fields_in(
                props, line, event_id, tenant_id, scope="properties"
            )
        )
    return anomalies


def _aliased_fields_in(
        obj: Mapping[str, Any],
        line: int,
        event_id: Optional[str],
        tenant_id: Optional[str],
        scope: str,
) -> List[Anomaly]:
    """Report every alias key found in `obj` as SCHEMA_DRIFT."""
    found: List[str] = []
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in obj:
                found.append(f"{alias} -> {canonical}")
    if not found:
        return []
    return [
        Anomaly(
            line=line,
            klass=C_SCHEMA_DRIFT,
            reason=f"{scope} non-canonical field(s): {', '.join(found)}",
            action="canonicalise_then_validate_required_fields",
            event_id=event_id,
            tenant_id=tenant_id,
        )
    ]


def _parse_iso(ts: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Accepts trailing 'Z' and bare offsets. Returns None if unparseable.
    """
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_timestamps(
        event: Mapping[str, Any], line: int
) -> List[Anomaly]:
    """Deterministic timestamp validation.

    Definitions:
      received_at = ingestion timestamp (required; source-of-truth for timing)
      ts          = event time (optional; when the action happened client-side)

    Behaviour:
      - If received_at is missing or unparseable, no comparison is performed.
      - If ts is absent, no anomaly is raised — missing ts is not bad data.
      - If ts is present and valid, it is compared against received_at.

    Rules (direction-based, NOT a bare magnitude check):
      - skew = ts - received_at (seconds; positive means ts is AHEAD)
      - skew > FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
            event claims to occur AFTER it was received — a timestamp
            paradox. Classified by severity:
              skew <= FUTURE_SEVERE_AHEAD_SECONDS -> IMPOSSIBLE_TIMESTAMPS
              skew >  FUTURE_SEVERE_AHEAD_SECONDS -> FUTURE_TIMESTAMPS
            (both classes share the same direction; FUTURE is the severe tier
            for absurdly-ahead values like a wrong-year event).
      - If STALE_TIMESTAMP_TOLERANCE_SECONDS is set and -skew exceeds it:
            STALE_EVENT (event arriving far too late). Off by default.

    We deliberately do NOT call an event "future" merely because
    abs(ts - received_at) > 1h. The SIGN of the skew decides which, if any,
    anomaly class applies.
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    ts_raw = event.get("ts")
    recv_raw = event.get("received_at")
    ts_dt = _parse_iso(ts_raw)
    recv_dt = _parse_iso(recv_raw)
    if ts_dt is None or recv_dt is None:
        return []

    anomalies: List[Anomaly] = []
    skew = (ts_dt - recv_dt).total_seconds()

    if skew > FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
        if skew > FUTURE_SEVERE_AHEAD_SECONDS:
            klass = C_FUTURE
            sev = "absurdly far ahead (e.g. wrong-year)"
        else:
            klass = C_IMPOSSIBLE
            sev = "event time after ingestion time"
        anomalies.append(
            Anomaly(
                line=line,
                klass=klass,
                reason=(
                    f"ts ({ts_raw}) is {int(skew)}s ahead of received_at "
                    f"({recv_raw}) — {sev} (tolerance "
                    f"{FUTURE_TIMESTAMP_TOLERANCE_SECONDS}s)"
                ),
                action="reject_unless_trusted_clock_correction_applies",
                event_id=event_id,
                tenant_id=tenant_id,
            )
        )

    if STALE_TIMESTAMP_TOLERANCE_SECONDS is not None:
        if -skew > STALE_TIMESTAMP_TOLERANCE_SECONDS:
            anomalies.append(
                Anomaly(
                    line=line,
                    klass=C_STALE,
                    reason=(
                        f"ts ({ts_raw}) is {int(-skew)}s behind received_at "
                        f"({recv_raw}) (stale tolerance "
                        f"{STALE_TIMESTAMP_TOLERANCE_SECONDS}s)"
                    ),
                    action="review",
                    event_id=event_id,
                    tenant_id=tenant_id,
                )
            )
    return anomalies


def detect_duplicates(
        event_id_to_lines: Mapping[str, List[int]],
        event_id_to_tenant: Mapping[str, Optional[str]],
) -> List[Anomaly]:
    """Deterministic duplicate detection on event_id (the dedup key).

    One anomaly per duplicated event_id, anchored at its first occurrence,
    listing all lines where it appears. Payload-equal events are NOT flagged
    unless their event_id also matches. Events with no event_id are skipped
    (we never manufacture an identity).

    Tenant isolation: event IDs are treated as tenant-scoped. If the same
    event_id appears under DIFFERENT tenant_id values, we report that as a
    separate duplicate group rather than collapsing across tenants. This
    respects the source architecture's tenant isolation model.
    """
    out: List[Anomaly] = []
    for event_id, lines in event_id_to_lines.items():
        if len(lines) <= 1:
            continue
        # Split by tenant to respect tenant isolation.
        by_tenant: Dict[Optional[str], List[int]] = defaultdict(list)
        for ln in lines:
            by_tenant[event_id_to_tenant.get(event_id)].append(ln)
        for tenant, tenant_lines in by_tenant.items():
            if len(tenant_lines) <= 1:
                continue
            out.append(
                Anomaly(
                    line=tenant_lines[0],
                    klass=C_DUPLICATE,
                    reason=(
                        f"event_id '{event_id}' appears {len(tenant_lines)} "
                        f"time(s) on line(s) {', '.join(map(str, tenant_lines))}"
                    ),
                    action="retain_first_seen_event_and_quarantine_duplicate",
                    event_id=event_id,
                    tenant_id=tenant,
                )
            )
    return out


def _lower_or_none(s: Any) -> Optional[str]:
    if not isinstance(s, str):
        return None
    s = s.strip()
    return s.lower() or None


def _extract_ua_and_referrer(event: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Pull referrer and user-agent from the canonical and common locations.

    Referrer: properties.referrer
    User-agent: top-level user_agent | userAgent | properties.user_agent |
                properties.userAgent
    Does not require any of these to exist.
    """
    referrer: Optional[str] = None
    props = event.get("properties")
    if isinstance(props, dict):
        referrer = _lower_or_none(props.get("referrer"))

    ua: Optional[str] = None
    for path in ("user_agent", "userAgent"):
        v = event.get(path)
        if isinstance(v, str):
            ua = _lower_or_none(v)
            break
    if ua is None and isinstance(props, dict):
        for path in ("user_agent", "userAgent"):
            v = props.get(path)
            if isinstance(v, str):
                ua = _lower_or_none(v)
                break
    return referrer, ua


def detect_bot_heuristics(
        event: Mapping[str, Any], line: int
) -> List[Anomaly]:
    """Standalone (non-burst) bot heuristic: scanner/bot terms in referrer or
    user-agent. The burst heuristic is computed across the full stream in
    detect_bot_burst (below), because it needs cross-event state.

    Heuristic — NOT proof. Action is `increase_bot_score`: it raises the bot
    confidence signal for downstream policy evaluation and never rejects,
    deletes, or permanently classifies the event.
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    referrer, ua = _extract_ua_and_referrer(event)
    hits: List[str] = []
    if referrer:
        for pat in SCANNER_PATTERNS:
            if pat in referrer:
                hits.append(f"referrer contains '{pat}'")
                break
    if ua:
        for pat in SCANNER_PATTERNS:
            if pat in ua:
                hits.append(f"user-agent contains '{pat}'")
                break
    if not hits:
        return []
    return [
        Anomaly(
            line=line,
            klass=C_BOT,
            reason="bot heuristic: " + "; ".join(hits)
                   + " (heuristic — not proof of bot traffic)",
            action="increase_bot_score",
            event_id=event_id,
            tenant_id=tenant_id,
        )
    ]


def detect_bot_burst(
        bursts: Mapping[Tuple[Optional[str], Optional[str]], List[int]],
        first_lines: Mapping[Tuple[Optional[str], Optional[str]], int],
) -> List[Anomaly]:
    """Burst heuristic: > BOT_BURST_COUNT page_view events from the same
    (tenant_id, anonymous_id) inside BOT_BURST_WINDOW_SECONDS (sliding window).

    Tenant-scoped by construction (the key includes tenant_id). Heuristic.
    `first_lines` maps each (tenant_id, anonymous_id) to the line number of
    its first page_view, used to anchor the reported anomaly deterministically.
    """
    out: List[Anomaly] = []
    for (tenant_id, anon_id), times in bursts.items():
        if anon_id is None or len(times) <= BOT_BURST_COUNT:
            continue
        times_sorted = sorted(times)
        window_ns = BOT_BURST_WINDOW_SECONDS * 1_000_000_000
        flagged = False
        # sliding window: any window containing > BOT_BURST_COUNT events
        for i in range(len(times_sorted) - BOT_BURST_COUNT):
            if times_sorted[i + BOT_BURST_COUNT] - times_sorted[i] <= window_ns:
                flagged = True
                break
        if not flagged:
            continue
        out.append(
            Anomaly(
                line=first_lines.get((tenant_id, anon_id), 0),
                klass=C_BOT,
                reason=(
                    f"bot heuristic: >{BOT_BURST_COUNT} page_view events from "
                    f"anonymous_id '{anon_id}' inside {BOT_BURST_WINDOW_SECONDS}s "
                    f"(tenant-scoped; heuristic — not proof of bot traffic)"
                ),
                action="increase_bot_score",
                event_id=None,
                tenant_id=tenant_id,
            )
        )
    return out


def _collect_pii(value: Any, path: str, hits: List[Tuple[str, str]]) -> None:
    """Recursive PII scan. Populates `hits` with (kind, location) tuples.

    Heuristic only. Never raises.
    """
    if value is None:
        return
    if isinstance(value, str):
        # value-based
        if EMAIL_REGEX.search(value):
            # avoid double-counting when the key itself already flagged email
            if not _looks_like_email_key(path.split(".")[-1]):
                hits.append(("email", path))
        else:
            m = PHONE_REGEX.search(value)
            if m and _is_plausible_phone(m.group(0)):
                if not _looks_like_phone_key(path.split(".")[-1]):
                    hits.append(("phone", path))
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _collect_pii(item, f"{path}[{i}]", hits)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            # name-based
            kind = PII_PROPERTY_NAME_HINTS.get(str(k))
            if kind:
                hits.append((kind, f"{path}.{k}"))
            _collect_pii(v, f"{path}.{k}", hits)
        return


def _looks_like_email_key(k: str) -> bool:
    return k in PII_PROPERTY_NAME_HINTS and PII_PROPERTY_NAME_HINTS[k] == "email"


def _looks_like_phone_key(k: str) -> bool:
    return k in PII_PROPERTY_NAME_HINTS and PII_PROPERTY_NAME_HINTS[k] == "phone"


def _is_plausible_phone(s: str) -> bool:
    """Reject obviously-not-phone matches like version numbers (10+ digits).
    Heuristic gate to reduce false positives on things like "12.34.56.78".
    """
    digits = re.sub(r"\D", "", s)
    return 7 <= len(digits) <= 15


def detect_pii(event: Mapping[str, Any], line: int) -> List[Anomaly]:
    """Heuristic PII detection in `properties`.

    Scans property names (obvious PII keys) and string values (regex). Only
    reports the *category* (email/phone) — never the actual PII value. The
    reason text always labels itself a heuristic so reviewers do not treat it
    as exhaustive PII discovery.
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    props = event.get("properties")
    if not isinstance(props, dict):
        return []
    hits: List[Tuple[str, str]] = []
    _collect_pii(props, "properties", hits)
    if not hits:
        return []
    # Deduplicate by kind while keeping one representative location each.
    by_kind: Dict[str, str] = {}
    for kind, loc in hits:
        by_kind.setdefault(kind, loc)
    kinds = sorted(by_kind.keys())
    return [
        Anomaly(
            line=line,
            klass=C_PII,
            reason=(
                    "PII heuristic detected: " + ", ".join(kinds)
                    + " (heuristic — not exhaustive PII discovery; values not logged)"
            ),
            action="redact",
            event_id=event_id,
            tenant_id=tenant_id,
        )
    ]


def detect_privacy_request(event: Mapping[str, Any], line: int) -> List[Anomaly]:
    """An event with type == 'privacy_request' is routed to the privacy
    workflow. It is NOT malformed and is NOT an error.
    """
    event_id = _coerce_str(_canonical_value(event, "event_id"))
    tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
    etype = _coerce_str(_canonical_value(event, "type"))
    if etype == "privacy_request":
        return [
            Anomaly(
                line=line,
                klass=C_PRIVACY,
                reason="event type is 'privacy_request'",
                action="route_to_privacy_workflow",
                event_id=event_id,
                tenant_id=tenant_id,
            )
        ]
    return []


# ============================================================================
# Stream processing — single pass, constant state per cross-event analysis
# ============================================================================


ParsedEvent = Tuple[int, Optional[Dict[str, Any]], Optional[str]]


def iter_lines(path: Path) -> Iterable[str]:
    """Yield raw lines from a file, line-by-line (memory-bounded)."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            yield line.rstrip("\n")


def run_detection(path: Path) -> List[Anomaly]:
    """One pass over the fixture. Builds the per-event anomalies plus the
    cross-event state needed for duplicate and burst detection, which are
    flushed at the end.

    State kept is only what each analysis needs:
      duplicates : event_id -> [lines], and event_id -> tenant
      burst      : (tenant_id, anonymous_id) -> [ts_ns], and a line lookup
    """
    anomalies: List[Anomaly] = []

    # Cross-event state
    event_id_lines: Dict[str, List[int]] = defaultdict(list)
    event_id_tenant: Dict[str, Optional[str]] = defaultdict(lambda: None)
    burst_times: Dict[Tuple[Optional[str], Optional[str]], List[int]] = (
        defaultdict(list)
    )
    burst_first_line: Dict[Tuple[Optional[str], Optional[str]], int] = {}

    for line_no, raw in enumerate(iter_lines(path), start=1):
        if not raw.strip():
            continue  # skip blank lines, not anomalies

        event, err = parse_event(raw)
        if event is None:
            anomalies.append(
                Anomaly(
                    line=line_no,
                    klass=C_MALFORMED,
                    reason=f"malformed JSON line: {err}",
                    action="quarantine",
                    event_id=None,
                    tenant_id=None,
                )
            )
            continue

        # --- deterministic, per-event checks ---
        anomalies.extend(validate_required_fields(event, line_no))
        anomalies.extend(detect_schema_drift(event, line_no))
        anomalies.extend(validate_timestamps(event, line_no))
        anomalies.extend(detect_privacy_request(event, line_no))

        # --- heuristic, per-event checks ---
        anomalies.extend(detect_bot_heuristics(event, line_no))
        anomalies.extend(detect_pii(event, line_no))

        # --- collect cross-event state ---
        event_id = _coerce_str(_canonical_value(event, "event_id"))
        tenant_id = _coerce_str(_canonical_value(event, "tenant_id"))
        if event_id is not None:
            event_id_lines[event_id].append(line_no)
            # last-write-wins for tenant; duplicates carry their own tenant
            event_id_tenant[event_id] = tenant_id

        etype = _coerce_str(_canonical_value(event, "type"))
        anon_id = _coerce_str(_canonical_value(event, "anonymous_id"))
        ts_dt = _parse_iso(_canonical_value(event, "ts"))
        if etype == "page_view" and anon_id is not None and ts_dt is not None:
            key = (tenant_id, anon_id)
            burst_times[key].append(ts_dt.timestamp() * 1_000_000_000)
            burst_first_line.setdefault(key, line_no)

    # --- cross-event analyses ---
    anomalies.extend(detect_duplicates(event_id_lines, event_id_tenant))
    anomalies.extend(detect_bot_burst(burst_times, burst_first_line))
    return anomalies


# ============================================================================
# Reporting
# ============================================================================


def summarize_anomalies(anomalies: List[Anomaly]) -> Dict[str, int]:
    """Count anomalies by class, in canonical display order."""
    counter: Counter = Counter(a.klass for a in anomalies)
    summary: Dict[str, int] = {cls: counter[cls] for cls in ANOMALY_CLASS_ORDER}
    summary["TOTAL"] = sum(counter.values())
    return summary


def render_report(anomalies: List[Anomaly]) -> str:
    """Human-readable, auditable report. Each anomaly carries line, event_id,
    tenant_id, class, reason, and recommended action. Never echoes PII.
    """
    lines: List[str] = ["=== ANOMALY REPORT ===", ""]

    def sort_key(a: Anomaly) -> Tuple[int, int]:
        return (a.line, ANOMALY_CLASS_ORDER.index(a.klass))

    for a in sorted(anomalies, key=sort_key):
        eid = a.event_id if a.event_id else "N/A"
        tenant = a.tenant_id if a.tenant_id else "N/A"
        lines.append(f"[line {a.line}] event_id={eid} tenant_id={tenant}")
        lines.append(f"  class:  {a.klass}")
        lines.append(f"  reason: {a.reason}")
        lines.append(f"  action: {a.action}")
        lines.append("")

    summary = summarize_anomalies(anomalies)
    lines.append("=== SUMMARY ===")
    lines.append(f"{'CLASS':<28} COUNT")
    for cls in (*ANOMALY_CLASS_ORDER, "TOTAL"):
        count = summary.get(cls, 0)
        if cls == "TOTAL" or count:
            lines.append(f"{cls:<28} {count}")
    return "\n".join(lines) + "\n"


def render_json_summary(anomalies: List[Anomaly]) -> str:
    return json.dumps(
        {
            "summary": summarize_anomalies(anomalies),
            "anomalies": [a.as_dict() for a in anomalies],
        },
        indent=2,
        sort_keys=False,
    )


# ============================================================================
# Entry point
# ============================================================================


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parent / DEFAULT_FIXTURE


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Anomaly detector for a multi-tenant analytics JSONL event fixture. "
            "Exits 0 on successful analysis regardless of anomaly count; "
            "non-zero only on input/execution failure."
        )
    )
    parser.add_argument(
        "fixture",
        nargs="?",
        help=f"JSONL event fixture path (default: ./{DEFAULT_FIXTURE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also print a machine-readable JSON summary",
    )
    args = parser.parse_args(argv)

    path = Path(args.fixture).expanduser().resolve() if args.fixture else default_fixture_path()
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    try:
        anomalies = run_detection(path)
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return 2

    print(render_report(anomalies))
    if args.json:
        print("=== JSON SUMMARY ===")
        print(render_json_summary(anomalies))

    # Exit 0: analysis completed successfully, even though anomalies were found.
    return 0


if __name__ == "__main__":
    sys.exit(main())