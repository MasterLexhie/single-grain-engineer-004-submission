# Evidence Log

## Evidence Tier Definition

Evidence tiers follow the challenge scoring standard:

| Tier | Evidence Type |
|---|---|
| Tier 0 | Claims only |
| Tier 1 | Screenshots |
| Tier 2 | Demo artifact |
| Tier 3 | Logs or source records |
| Tier 4 | Before and after measured data |
| Tier 5 | Independent verification |

---

# Capacity and Cost Evidence

| Claim |                       Value | Number Source Label | Evidence Tier | Evidence Artifact |
|---|----------------------------:|---|---|---|
| Baseline traffic |    [Assumed] 50M events/day | Assumed | Tier 3 | `artifacts/capacity-cost-model.py` |
| Peak traffic | [Estimated] 500M events/day | Estimated | Tier 3 | `artifacts/capacity-cost-model.py` |
| Peak EPS |          [Estimated]         5,787/sec | Estimated | Tier 3 | `artifacts/capacity-cost-model.py` |
| Ingestion capacity |              [Assumed]   8 EC2 nodes | Assumed | Tier 2 | `diagrams/architecture.png`, `written-answer.md` |
| Stream consumer capacity |      [Assumed]    4 ECS tasks on EC2 | Assumed | Tier 2 | `diagrams/architecture.png`, `written-answer.md` |
| Monthly AWS cost |               [Estimated]    $5,761.75 | Estimated | Tier 3 | `artifacts/capacity-cost-model.py` |

## Verification

Capacity and cost calculations can be reproduced using:

```bash
python3 artifacts/capacity_cost_model.py
```

The capacity model provides:

- Traffic assumptions
- Peak throughput calculations
- AWS service sizing
- Monthly cost estimates
- Budget validation

---

# AWS Service Evidence

| Claim |                   Value | Number Source Label | Evidence Tier | Evidence Artifact |
|---|------------------------:|---|---|---|
| Kinesis monthly cost |   [Benchmarked] $215.17 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| ALB monthly cost |     [Benchmarked] $7.42 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| RDS PostgreSQL cost | [Benchmarked] $3,695.28 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| Redis monthly cost |     [Benchmarked]            $113.88 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| S3 monthly cost |              [Benchmarked]   $264.60 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| SQS DLQ cost |                [Benchmarked]  $18.00 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |
| AWS Glue export cost |              [Benchmarked]     $4.40 | Benchmarked | Tier 3 | `artifacts/capacity-cost-model.py` |

## Verification

AWS service selection and architecture responsibilities are documented in:

- `written-answer.md`
- `diagrams/architecture.png`
- `artifacts/capacity-cost-model.py`

The capacity model contains the pricing assumptions and calculations used for cost validation.

---

# Reliability Evidence

| Claim | Value                        | Number Source Label | Evidence Tier | Evidence Artifact |
|---|------------------------------|---|---|---|
| Existing peak loss rate | [Observed] 3%                          | Observed | Tier 2 | `docs/failure-modes.md`, `written-answer.md` |
| DLQ recovery mechanism | SQS DLQ                      | Assumed | Tier 2 | `diagrams/architecture.png`, `docs/failure-modes.md` |
| Replay storage | S3 raw event store           | Assumed | Tier 2 | `diagrams/architecture.png`, `docs/failure-modes.md` |
| Event validation workflow | Anomaly detection validation | Estimated | Tier 3 | `artifacts/detect_anomalies.py`, `fixture/events.jsonl` |

## Verification

The event validation workflow can be reproduced using:

```bash
python3 artifacts/detect_anomalies.py
```

Reliability design evidence is supported by:

- Failure mode analysis
- Architecture diagram
- Validation artifact

---

# Risk and Validation Gaps

| Claim | Current Status | Evidence Tier |
|---|---|---|
| Redis capacity validation | Missing production metrics | Tier 0 until measured |
| Cache hit ratio | Unknown | Tier 0 |
| Load test performance | Not executed | Tier 0 |
| Before/after migration metrics | Not available | Tier 0 |

These represent known validation gaps and are intentionally identified as areas requiring future measurement rather than unsupported claims.

---

# Submission Strength Assessment

## Current Evidence Coverage

### Tier 2 Evidence

Available:

- Architecture diagram
- Written design response
- Failure handling documentation

Artifacts:

- `diagrams/architecture.png`
- `written-answer.md`
- `docs/failure-modes.md`

---

### Tier 3 Evidence

Available:

- Capacity calculations
- AWS cost calculations
- Validation scripts
- Reproducible analysis workflow

Artifacts:

- `artifacts/capacity-cost-model.py`
- `artifacts/detect_anomalies.py`
- `fixture/events.jsonl`

---

## Missing Evidence Differentiators

The following evidence categories are not included in this submission package:

| Evidence Type | Status | Reason |
|---|---|---|
| Tier 4 measured before/after results | Not available | No production migration environment or controlled benchmark environment was provided |
| Tier 5 independent verification | Not available | No external validation process was performed |

Current supporting artifacts remain:

- Capacity model:
    - `artifacts/capacity-cost-model.py`

- Reliability analysis:
    - `docs/failure-modes.md`

- Validation workflow:
    - `artifacts/detect_anomalies.py`

- Architecture:
    - `diagrams/architecture.png`

These missing evidence categories are documented as validation gaps and are not used as submission claims.