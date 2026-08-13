# What Stays Human

This document identifies decisions within the real-time analytics pipeline
that must always involve human judgment and approval. These are not gaps in
automation they are deliberate checkpoints where the consequences of a
wrong decision are too significant, ambiguous, or irreversible to delegate
to an automated system.




## 1. Bot Traffic Quarantine Policy

**Decision:** Which traffic patterns are classified as non-human and
quarantined from analytics.

**Why human:** The line between bot traffic and legitimate automation is
ambiguous. A monitoring tool, a CI pipeline, or a legitimate web crawler
could trigger bot detection rules. Misclassification in either direction
has real consequences polluting customer analytics with non-human
traffic, or silently dropping legitimate events from a real visitor.
This is a business and product judgment call, not a deterministic rule.
Humans define the policy; the system enforces it.




## 2. Anomaly Validation Rule Updates

**Decision:** Any change to the rules that determine what events are
accepted, rejected, normalised, or quarantined at ingestion.

**Why human:** Validation rules apply across [Assumed] 500+ tenants simultaneously.
A bad rule change could silently drop millions of legitimate events or
allow a new class of dirty data through undetected. Rule changes require
engineering review, deliberate testing against the fixture dataset, and
controlled deployment. This must never be automated or self-modifying.




## 3. Pipeline Migration Cutover

**Decision:** The final approval to switch production traffic from the
old broken pipeline to the new system.

**Why human:** Cutting over prematurely or incorrectly has catastrophic
consequences data loss, broken customer dashboards, inaccurate
analytics, and potential SLA violations across all [Assumed] 500+ customers.
No automated threshold alone should trigger this. A human engineering
lead must explicitly sign off after reviewing the 3-month parallel
validation data, error rates, DLQ rates, and latency comparisons.
Rollback must also be a human decision.




## 4. Data Warehouse Export Initiation

**Decision:** When a customer triggers a data export to Snowflake or
BigQuery.

**Why human:** The customer must explicitly confirm the data range,
destination, and scope of the export. This is a business decision
with compliance implications exporting the wrong date range or
to an unintended destination cannot be easily undone. Once initiated
by a human, the export process itself is fully automated.




## 5. Definition of "Recent" for Personalisation

**Decision:** What time window constitutes "recent" visitor behaviour for
personalisation triggering.

**Why human:** The brief states personalisation should be triggered based
on "recent behaviour" but does not define what recent means. This is a
product and business decision with direct architectural implications. A
1-day window maps to the current 24hr Redis TTL. A 7-day window requires
a different storage and query strategy entirely. For anonymous visitors
researching across multiple days, a narrow TTL means missed personalisation
opportunities that could directly impact revenue. Engineering cannot make
this call unilaterally. The business must define the window before the
architecture can be finalised.


## Summary

| Decision | Reason |
|---|---|
| Bot traffic quarantine policy | Ambiguous boundary, business judgment required |
| Anomaly validation rule updates | Cross-tenant impact, irreversible at scale |
| Migration cutover approval | Catastrophic if wrong, requires validation review |
| Export initiation | Compliance scope, business confirmation required |
| Definition of "recent" for personalisation | Product decision with direct architectural implications |