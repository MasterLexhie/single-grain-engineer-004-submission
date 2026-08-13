# Real-Time Analytics Platform Design Submission

## 1. Executive Summary

The current analytics platform has reliability issues during peak traffic periods, including [Observed] approximately 3% event loss under load. The goal of this redesign is to provide a scalable real-time analytics platform capable of handling 10x traffic spikes while improving durability, migration safety, operational simplicity, and cost control.

The proposed architecture introduces:

- Durable event capture before downstream processing
- Scalable event streaming
- Independent ingestion and consumer scaling
- Database workload separation
- Replay capability for recovery and migration validation

The system is designed around the following traffic model:

- Baseline traffic: [Assumed] 50 million events/day
- Peak traffic: [Estimated] 500 million events/day ([Assumed] 10x multiplier)
- Peak processing requirement: approximately [Estimated] 5,787 events/sec
- Monthly records processed: approximately [Estimated] 1.95 billion events

The monthly operating cost is approximately [Estimated] $5.7k based on [Benchmarked] AWS pricing calculations and [Assumed] architecture assumptions, significantly below the engineering budget target.

The design prioritizes reliability and operational simplicity by using managed AWS services while focusing engineering effort on the application-specific components that directly affect correctness and customer experience.

Evidence references:

- `diagrams/architecture.png` — proposed real-time analytics architecture
- `artifacts/capacity_cost_model.py` — capacity sizing and AWS cost model
- `docs/evidence-log.md` — evidence tier mapping and supporting artifacts
- `docs/number-score.md` — challenge assumptions and scored metrics
---

# 2. Team Constraint and Delivery Approach

The solution is intentionally designed for a delivery model of **two senior engineers working full time**.

The architecture avoids unnecessary operational complexity by relying on managed AWS services instead of building custom infrastructure. This allows the engineering team to focus on the areas where domain-specific decisions are required:

- Event ingestion reliability
- Data validation
- Idempotent processing
- Stream consumer behavior
- Database write batching
- Replay workflows
- Migration validation

Managed services reduce operational ownership:

| Requirement | AWS Service | Reason |
|---|---|---|
| Event streaming | Kinesis Data Streams On-Demand | Removes shard capacity planning |
| Durable storage | S3 | Provides replay storage without infrastructure management |
| Queue retry handling | SQS | Provides managed dead-letter processing |
| Database operations | RDS PostgreSQL | Removes database cluster administration |
| Batch exports | Glue | Removes ETL infrastructure management |

The two-engineer constraint also influences scope decisions.

The MVP intentionally excludes:

- Multi-region active-active architecture
- Custom streaming infrastructure
- Complex data lake processing
- Large-scale data governance tooling
- Advanced automated migration orchestration

These capabilities may be added later as operational requirements increase.

The selected architecture provides production capability while maintaining a realistic implementation and ownership model for a small senior engineering team.

---

# 3. Architecture Design and Key Decisions

## Event Ingestion Layer

The ingestion layer uses an Application Load Balancer with EC2 Auto Scaling workers.

Responsibilities:

- Receive customer events
- Validate incoming payloads
- Apply schema checks
- Persist events into durable storage
- Publish events into the streaming layer

Initial capacity:

- 8 EC2 ingestion instances
- EC2 Auto Scaling for peak periods

The ingestion layer is separated from downstream processing to prevent consumer delays from affecting event acceptance.

---

## Durable Event Storage

A raw event store is implemented using Amazon S3 Standard.

The raw event store provides:

1. Replay after processing failures
2. Batch write safety before database updates
3. Migration validation source of truth

Configuration:

- Storage class: S3 Standard
- Retention: [Assumed] 1 year
- Stored data estimate: [Estimated] 11.5 TB

Estimated cost:

[Benchmarked] $264.60/month

This design ensures that temporary downstream failures do not result in permanent event loss.

---

## Streaming Layer

Amazon Kinesis Data Streams On-Demand is used as the event distribution layer.

On-Demand mode was selected because the workload has unpredictable peak periods and the engineering team should not spend operational effort managing shard capacity.

Configuration:

- Mode: On-Demand
- Record size assumption: [Assumed] 1 KB
- Monthly records: [Estimated] 1.95 billion
- Consumer applications: 1 
- Enhanced fan-out: disabled

Estimated monthly cost:

[Benchmarked] $215.17

---

## Stream Consumers

Stream consumers run independently using ECS tasks on EC2.

Configuration:

- 4 ECS consumer tasks
- ECS Service Auto Scaling

Responsibilities:

- Consume ordered events
- Perform enrichment
- Update real-time state
- Batch database writes

Separating consumers from ingestion allows each layer to scale independently.

---

# 4. Data Storage and Serving Architecture

## PostgreSQL Operational Database

The database layer uses Amazon RDS PostgreSQL.

Deployment:

- Primary writer database
- Read replica for read-heavy workloads

Primary database responsibilities:

- Transactional writes
- Operational queries

Read replica responsibilities:

- Dashboard reads
- Export workloads
- Analytical queries

Configuration:

Primary:

- Instance type: [Assumed] db.m7g.large
- Storage: [Assumed] 15 TB gp3
- Cost: [Estimated] $1,847.64/month

Read replica:

- Instance type: [Assumed] db.m7g.large
- Storage: [Assumed] 15 TB gp3
- Cost: [Estimated] $1,847.64/month

This prevents reporting workloads from impacting ingestion writes.

---

## Redis Real-Time State Cache

Amazon ElastiCache Redis provides low-latency access for:

- Personalization state
- Real-time dashboard state

Configuration:

- Single node
- On-Demand pricing
- TTL: [Assumed]  24 hours
- Data tiering disabled

Estimated cost:

[Benchmarked] $113.88/month

The current model assumes no additional Redis nodes during peak periods because the workload is expected to benefit primarily from caching rather than increased storage.

Production validation is still required for:

- Cache hit ratio
- Memory utilization
- Operations/sec
- Object size distribution

---

# 5. Reliability, Migration, and Failure Handling

## Migration Strategy

The migration approach minimizes customer disruption.

### Phase 1 — Parallel Validation

The new ingestion path operates alongside the existing system.

Validation compares:

- Event counts
- Event identifiers
- Processing results
- Data completeness

### Phase 2 — Consumer Migration

Processing moves gradually to the new stream consumers.

The S3 raw event store provides replay capability if discrepancies are detected.

### Phase 3 — Production Cutover

Traffic is migrated after validation confirms:

- Event delivery reliability
- Processing consistency
- Customer-facing correctness

Rollback is possible by returning traffic to the existing pipeline.

---

## Failure Handling

### Ingestion Failures

Failed events are routed through SQS DLQ handling.

Configuration:

- Queue type: [Benchmarked] Standard SQS
- Peak failure rate: [Assumed] 3%

Estimated monthly cost:

[Benchmarked] $18/month

---

### Stream Failures

Recovery process:

1. Consumers restart from checkpoints
2. Missing events are replayed from durable storage
3. Data validation confirms recovery completeness

---

### Database Failures

The architecture isolates read workloads from write workloads.

If database issues occur:

- Event ingestion can continue
- Events remain recoverable
- Replay prevents permanent loss

---

# 6. Capacity and Cost Validation

The design was evaluated against:

| Metric |              Value |
|---|-------------------:|
| Baseline events/day |      [Assumed] 50M |
| Peak multiplier |     [Assumed]  10x |
| Peak events/day |  [Estimated]  500M |
| Peak EPS | [Estimated]  5,787 |
| Monthly records | [Estimated]  1.95B |

Estimated monthly cost:

| Component |                                       Cost |
|-|-------------------------------------------:|
| ALB |                        [Benchmarked] $7.42 |
| EC2 ingestion |                    [Estimated]     $588.67 |
| Kinesis |                      [Benchmarked] $215.17 |
| ECS consumers |                      [Estimated]   $294.34 |
| RDS primary |                   [Estimated]    $1,847.64 |
| RDS replica |                    [Estimated]   $1,847.64 |
| Redis |                        [Estimated] $113.88 |
| S3 |                      [Benchmarked] $264.60 |
| SQS |                      [Benchmarked]  $18.00 |
| Glue |                          [Estimated] $4.40 |
| Monitoring estimate |                           [Assumed] $60.00 |
| Miscellaneous |                        [Estimated] $500.00 |

Total:

[Estimated] $5,761.75/month

Budget validation:

Engineering target: [Assumed] $20,000/month  
Status: PASS

Hard budget: [Assumed] $50,000/month  
Status: PASS

---

# 7. Compliance, Data Quality, and Human Decisions

The platform supports auditability and controlled data processing through:

- Durable event retention
- Replay capability
- Validation workflows
- Traceable event identifiers

Automated decisions:

- Event validation
- Scaling actions
- Retry handling
- Replay execution

Human decisions:

- Migration approval
- Compliance interpretation
- Threshold changes
- Production tradeoffs

---

# 8. MVP Scope and Future Improvements

The MVP focuses on eliminating data loss and enabling scalable analytics.

Included:

- Reliable ingestion
- Durable event storage
- Stream processing
- Database separation
- Real-time cache
- Export workflow

Future improvements:

- Multi-region disaster recovery
- Advanced observability
- Automated migration tooling
- Additional consumer workloads
- More detailed cache optimization

The final architecture balances reliability, scalability, cost, and the practical delivery constraints of a two-senior-engineer team.