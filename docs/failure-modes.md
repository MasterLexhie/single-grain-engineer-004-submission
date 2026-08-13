# Failure Modes

This document describes the most likely failure modes, bad inputs, missing
data, and constraints that would make this design wrong or incomplete.

Each failure mode includes:

- The assumption or scenario
- The impact if the assumption is incorrect
- Detection approach
- Mitigation strategy

Supporting artifacts:

- Architecture:
    - `diagrams/architecture.png`

- Capacity model:
    - `artifacts/capacity_cost_model.py`

- Human decision boundaries:
    - `docs/what-stays-human.md`

---

# 1. Payload Size Assumption Wrong

## Assumption

Average event payload is **[Assumed] 0.5KB**.

## What breaks

If real-world payloads average **[Assumed] 5KB**, storage and throughput requirements increase significantly.

Impact:

- S3 Raw Event Store storage growth increases.
- Database write throughput requirements increase.
- Kinesis ingestion and retrieval costs increase.

The current model estimates approximately **[Estimated] 25GB/day baseline storage**.

A **[Estimated] 5KB payload** would increase storage requirements approximately **10x**.

## Detection

Monitor:

- Average event payload size
- S3 write volume
- Database storage growth

CloudWatch alarms should trigger when the rolling **[Assumed threshold] 7-day average payload size exceeds 1KB**.

## Mitigation

- Recalculate capacity using observed production payload distributions.
- Increase storage capacity if required.
- Update the capacity model after MVP traffic measurements.

Evidence:

- `artifacts/capacity_cost_model.py`

---

# 2. Peak Traffic Higher Than Estimated

## Assumption

Peak traffic is **[Assumed] 10x baseline traffic**.

Current model:

- Baseline: **[Assumed] 50M events/day**
- Peak: **[Estimated] 500M events/day**
- Peak throughput: **[Estimated] 5,787 events/sec**

## What breaks

During a larger-than-expected traffic event:

- Ingestion nodes may become saturated.
- Consumer lag may increase.
- Redis update latency may increase.
- Database write queues may grow.

## Detection

Monitor:

- EC2 ingestion node CPU and memory
- Kinesis consumer lag
- Database write latency

Example operational thresholds:

- **[Assumed] 60% ingestion capacity threshold**
- **[Assumed] 5,800 events/sec monitoring threshold**

These are operational alert thresholds, not measured production limits.

## Mitigation

- Use EC2 Auto Scaling for ingestion capacity.
- Use ECS Service Auto Scaling for consumers.
- Validate capacity using production traffic measurements.

Evidence:

- `artifacts/capacity_cost_model.py`
- `diagrams/architecture.png`

---

# 3. Noisy Tenant

## Scenario

A single tenant generates **[Assumed] 80%** of total traffic volume.

## What breaks

A noisy tenant can consume shared:

- Ingestion capacity
- Stream processing capacity
- Database write throughput

Other tenants may experience increased latency.

## Detection

Monitor per-tenant:

- Event volume
- Processing latency
- Error rates

Example alert threshold:

- **[Assumed] tenant exceeds 50% of ingestion throughput**

## Mitigation

- Apply tenant-level rate limiting.
- Partition events using:

```
tenant_id + anonymous_id
```

This maintains ordering for the same visitor while distributing workload across consumers.

Evidence:

- `diagrams/architecture.png`

---

# 4. Ingestion Node Overload

## Scenario

The load balancer distributes traffic, but individual ingestion nodes cannot process extreme peak traffic.

## What breaks

Events may be dropped before reaching the Raw Event Store.

This violates the zero-loss objective because events cannot be replayed if they were never stored.

## Detection

Monitor:

- CPU utilization
- Memory utilization
- Request queue depth
- Application errors

Monitoring tools:

- CloudWatch
- Sentry

## Mitigation

- EC2 Auto Scaling maintains ingestion capacity.
- Raw Event Store write occurs before downstream processing.

This ensures events reaching ingestion are durably captured.

Evidence:

- `diagrams/architecture.png`
- `docs/evidence-log.md`

---

# 5. Kinesis Stream Delay

## Scenario

Consumer processing cannot keep up with ingestion volume.

## What breaks

First impact:

- Dashboard updates become delayed.
- Personalization updates become stale.
- Downstream analytics processing falls behind.

## Detection

Monitor:

- Kinesis consumer lag
- Processing latency

Example alert:

- **[Assumed] consumer lag exceeds 3 seconds**

## Mitigation

- Scale consumer capacity using ECS Service Auto Scaling.
- Monitor ingestion and processing throughput.
- Use database fallback paths where required for availability.

Note:

The design uses **Kinesis Data Streams On-Demand**, therefore shard count is not manually modeled.

Evidence:

- `artifacts/capacity_cost_model.py`

---

# 6. Security / Compliance Controls Gap

## Gap

The architecture documentation does not provide measured compliance validation.

## What breaks

Missing controls could prevent future compliance requirements.

Potential gaps:

- Data access auditing
- Encryption verification
- Tenant-level access controls

## Detection

Security review before production launch.

## Mitigation

Recommended implementation:

- Enable encryption at rest.
- Enable encryption in transit.
- Enable audit logging.
- Review IAM permissions.

These are implementation controls and do not require architectural changes.

---

# 7. Redis TTL Assumption Wrong

## Assumption

Redis TTL is **[Assumed] 24 hours**.

Purpose:

- Personalization state
- Real-time dashboard state

## What breaks

If the business definition of "recent" exceeds **[Assumed] 24 hours**, required history may not exist in Redis.

Example:

A rule requiring behaviour over **[Assumed] 7 days** cannot rely only on Redis.

## Detection

This is a product requirement validation issue.

Detected through:

- Customer testing
- Personalization accuracy review

## Mitigation

Human decision required:

- Define "recent behaviour" window.
- Adjust Redis TTL if required.
- Query historical data from PostgreSQL when Redis data is insufficient.

Evidence:

- `docs/what-stays-human.md`

---

# 8. Validation Against Broken Baseline

## Observed Constraint

Existing system peak loss rate: **[Observed] 3%**

The current system baseline is considered unreliable as the sole migration validation source because peak-period event loss already exists.

Evidence reference:

- `docs/evidence-log.md` → Reliability Evidence → Existing peak loss rate
- `docs/number-score.md` → Existing peak data loss metric
- `diagrams/architecture.png` → Raw Event Store validation architecture

### Example Scenario

**[Assumed example]**

If the new system processes [Assumed] 100 events and the old system processes [Assumed] 97 events, correctness cannot be determined without an independent source of truth.

The old system may have dropped events, meaning comparison against historical output alone may hide migration defects.

## What Breaks

Using the existing system as the only migration comparison source may result in:

- False confidence in migration accuracy.
- Undetected event processing gaps.
- Incorrect validation of the new pipeline.

## Detection

Migration validation compares:

- Raw Event Store event counts.
- Processed event counts.
- Database output counts.

The Raw Event Store is used as the independent validation reference because events are durably stored before downstream processing.

Evidence:

- `diagrams/architecture.png`
- `artifacts/detect_anomalies.py`
- `docs/evidence-log.md`

## Mitigation

Migration validation uses the Raw Event Store as the source of truth.

Validation workflow:

1. Capture incoming events into the Raw Event Store.
2. Process events through the new pipeline.
3. Compare processed output against raw ingestion counts.
4. Investigate any mismatch.

The old system comparison remains a secondary signal only and is not treated as the correctness baseline.

Evidence:

```bash
python3 artifacts/detect_anomalies.py
```

Supporting artifacts:
- `artifacts/detect_anomalies.py`
- `artifacts/capacity_cost_model.py`
- `docs/evidence-log.md`
---

# 9. Identity Stitching Inaccuracy

## Scenario

An anonymous_id is incorrectly associated with multiple user identities.

## What breaks

Potential impact:

- Incorrect personalization
- Incorrect segmentation
- Incorrect user history attribution

## Detection

Monitor identity mappings for:

- Duplicate active mappings
- Unexpected identity changes

## Mitigation

Identity mappings are:

- Scoped by tenant_id
- Time-bound using valid_from and valid_to
- Protected with database constraints

Historical relationships remain available for auditing.

---

# Summary

| Failure Mode | Severity | Detection | Mitigation |
|---|---|---|---|
| Payload size wrong | High | Payload and storage monitoring | Recalculate capacity |
| Peak underestimated | Critical | Capacity metrics | Auto Scaling and validation |
| Noisy tenant | High | Tenant metrics | Rate limiting |
| Ingestion overload | Critical | CloudWatch/Sentry | Auto Scaling, durable writes |
| Kinesis delay | High | Consumer lag metrics | Consumer scaling |
| Security gaps | High | Security review | Encryption and auditing |
| Redis TTL wrong | Medium | Product validation | Business-defined TTL |
| Broken validation baseline | High | Raw Event Store comparison | Use raw events as source of truth |
| Identity stitching issue | Medium | Mapping monitoring | Database constraints |