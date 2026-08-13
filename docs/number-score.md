# Number Score

## Purpose

This document classifies all major quantitative claims in the submission according to the required number source labels:

- Observed
- Estimated
- Benchmarked
- Assumed

Every number is explicitly labeled because unlabeled numbers reduce review confidence.

---

# Traffic Model

| Metric |                           Value | Source Label | Rationale |
|---|--------------------------------:|---|---|
| Baseline events/day |            [Assumed] 50,000,000 | Assumed | Challenge sizing input used to model system capacity |
| Peak multiplier |                   [Assumed] 10x | Assumed | Required peak scaling scenario |
| Peak events/day |         [Estimated] 500,000,000 | Estimated | Derived from baseline × peak multiplier |
| Monthly records |       [Estimated] 1,950,000,000 | Estimated | Derived from 29 baseline days + 1 peak day |
| Baseline EPS |              [Estimated] 578.70 | Estimated | Derived from monthly traffic model |
| Peak EPS |            [Estimated] 5,787.04 | Estimated | Derived from peak traffic model |

---

# Compute Capacity

| Metric |                    Value | Source Label | Rationale |
|---|-------------------------:|---|---|
| Ingestion nodes |         [Assumed] 8 EC2 instances | Assumed | Capacity decision based on throughput requirements |
| Ingestion scaling model |         EC2 Auto Scaling | Assumed | Architecture decision |
| Stream consumers |    [Assumed]   4 ECS tasks on EC2 | Assumed | Capacity sizing decision |
| Consumer scaling model | ECS Service Auto Scaling | Assumed | Architecture decision |

---

# Kinesis

| Metric |                   Value | Source Label | Rationale |
|---|------------------------:|---|---|
| Pricing mode |               On-Demand | Benchmarked | AWS pricing model |
| Record size |          [Assumed] 1 KB | Assumed | Modeling input |
| Monthly records processed |       [Estimated] 1.95B | Estimated | Derived from traffic model |
| Monthly Kinesis cost | [Benchmarked]   $215.17 | Benchmarked | AWS pricing calculation |

---

# Database

| Metric |                               Value | Source Label | Rationale |
|---|------------------------------------:|---|---|
| Primary instance |              [Assumed] db.m7g.large | Assumed | Architecture selection |
| Primary storage |                 [Assumed] 15 TB gp3 | Assumed | Capacity requirement |
| Read replica |              [Assumed] db.m7g.large | Assumed | Read scaling/export workload |
| Monthly database cost | [Benchmarked + Estimated] $3,695.28 | Benchmarked + Estimated | AWS pricing calculation |

---

# Redis Cache

| Metric |                 Value | Source Label | Rationale |
|---|----------------------:|---|---|
| Deployment |           Single node | Assumed | Design decision |
| TTL |           [Assumed]   24 hours | Assumed | Cache lifecycle decision |
| Monthly cost | [Benchmarked] $113.88 | Benchmarked | AWS pricing calculation |

---

# Raw Event Store

| Metric |            Value | Source Label | Rationale |
|---|-----------------:|---|---|
| Retention | [Assumed] 1 year | Assumed | Replay and validation requirement |
| Stored data |       [Estimated]   11.5 TB | Estimated | Derived from event retention model |
| Monthly S3 cost |       [Benchmarked]   $264.60 | Benchmarked | AWS pricing calculation |

---

# Reliability

| Metric |                 Value | Source Label | Rationale |
|---|----------------------:|---|---|
| Existing peak data loss |               [Observed]     3% | Observed | Current system behavior provided in challenge context |
| DLQ messages during peak | [Estimated] 15M/month | Estimated | Derived from failure rate assumption |

Evidence references:

- `docs/evidence-log.md` — Reliability Evidence mapping
- `docs/failure-modes.md` — Validation Against Broken Baseline analysis
- `diagrams/architecture.png` — Raw Event Store validation flow
---

# Total Cost Model

| Metric |      Value | Source Label |
|---|-----------:|---|
| Monthly AWS operating cost | [Benchmarked + Estimated] $5,761.75 | Benchmarked + Estimated inputs |
| Engineering budget target |  [Assumed]  $20,000 | Assumed challenge constraint |
| Hard budget ceiling |  [Assumed]  $50,000 | Assumed challenge constraint |

---

# Known Weaknesses

The following values remain assumptions and require validation:

- Redis object size
- Redis key count
- Cache hit ratio
- Operations/sec
- Actual ingestion node utilization
- Actual consumer throughput under load
- Production CloudWatch/Sentry usage

These should not be presented as observed production metrics.