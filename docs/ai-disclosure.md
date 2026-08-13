# AI Usage Disclosure

Brief version: 2026-07

## Tools Used

- **Claude Sonnet** (Anthropic) via claude.ai, used for brainstorming,
  document generation, and cost modeling
- **ChatGPT** (OpenAI), used for brainstorming and concept exploration
- **GLM** via Open Code, used for development work

## What AI Helped With

- Reviewing and organising information from the provided challenge materials
- Generating supporting documents including failure modes analysis,
  cost model, and architecture documentation based on decisions and
  reasoning I developed throughout the session
- Brainstorming potential failure points, edge cases, and mitigations
- Explaining unfamiliar concepts when asked, including time-series
  databases, SOC requirements, AWS Glue vs Lambda
  trade-offs, and Kinesis shard sizing
- Pointing out gaps in reasoning when requirements, estimations, or
  architecture decisions were incomplete
- Producing cost estimates for AWS services against the [Assumed] $50K/month
  budget ceiling, which I then manually verified against AWS pricing

The architecture diagram was produced independently. All AI-generated
documents were produced under my direction, with final decisions on
content and approach made by me.

## What I Personally Decided

- All functional and non-functional requirements : including the
  decision to differentiate availability SLAs between ingestion
  ([Assumed] 99.99%) and other components ([Assumed] 99.9%)
- The MVP vs full system scope split : what to defer to month 6
- The decision to set a self-imposed engineering target of [Assumed] $20,000/month against the [Assumed] $50,000 hard budget ceiling, to preserve overhead for extreme peak traffic scenarios
- Technology choices : Kinesis over SQS, TimescaleDB over Redshift,
  Redis for both idempotency and hot path cache, AWS Glue for exports
- The dual read path strategy : Redis for hot path, TimescaleDB for
  warm path and historical queries
- The Raw Event Store as source of truth for migration validation,
  replay, and batch write safety
- The decision to clean data at ingestion before Kinesis rather than
  after
- The decision to store identity mappings and resolve at query time
  rather than retroactively rewriting events
- The routing layer design : routing by event type and anomaly class
  rather than building a separate compliance API endpoint
- All anomaly class identification from the fixture data
- The migration strategy : strangler fig pattern with 3-month parallel
  validation window
- The decision to use per-tenant rate limiting for noisy tenant
  mitigation
- All architectural pushbacks and scope decisions throughout the session

## What I Checked or Changed

- Manually verified all AWS cost estimates against public pricing pages
- Pushed back on AI suggestions that did not fit the brief constraints,
  including the suggestion to add a separate compliance API endpoint
- Challenged the load balancer placement when it was suggested as an
  NFR concern rather than a core architectural component
- Corrected the payload size assumption reasoning when the initial
  estimate of 0.97KB was questioned
- Verified all anomaly classes against the actual fixture data
  line by line
- Questioned whether export belonged in MVP scope and correctly
  deferred it to full system
- Identified that the personalisation output arrow was incorrectly
  pointing to the dashboard and corrected it
- Identified that "recent" is undefined in the brief and flagged it
  as a business decision gap