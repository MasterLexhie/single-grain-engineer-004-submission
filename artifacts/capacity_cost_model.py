#!/usr/bin/env python3
"""
Capacity + Cost Model v1.1
Real-time analytics pipeline

Purpose:
- Model infrastructure capacity at peak traffic.
- Model monthly cost using realistic traffic distribution.
- Separate fixed infrastructure costs from variable usage costs.
- Validate AWS service assumptions before production planning.

Traffic model:
    Baseline:
        50,000,000 events/day

    Peak:
        10x capacity requirement
        500,000,000 events/day

    Monthly cost assumption:
        29 baseline days
        1 peak day

Evidence labels:

[OBSERVED]
Directly provided system requirement.

[REQUIREMENT]
Required design target.

[ASSUMED]
Engineering assumption requiring validation.

[DERIVED]
Calculated value.

[VENDOR-SOURCED: VERIFY]
Pricing requiring AWS validation.

[LOAD-TEST REQUIRED]
Must be confirmed experimentally.
"""

import argparse
import json
import math


# ============================================================================
# CONSTANTS
# ============================================================================

SECONDS_PER_DAY = 86_400
HOURS_PER_MONTH = 730
DAYS_PER_MONTH = 30

BYTES_PER_KB = 1024
BYTES_PER_GB = 1024 ** 3
BYTES_PER_MIB = 1024 ** 2


# ============================================================================
# SYSTEM INPUTS
# ============================================================================

# [OBSERVED]
BASELINE_EVENTS_PER_DAY = 50_000_000


# [REQUIREMENT]
PEAK_MULTIPLIER = 10


# [ASSUMED]
DEFAULT_EVENT_SIZE_KB = 0.5


# Peak frequency:
#
# We are NOT assuming peak traffic happens every day.
#
# Cost model:
#
# 29 normal days
# 1 peak day

PEAK_DAYS_PER_MONTH = 1


# ============================================================================
# BUDGET
# ============================================================================

ENGINEERING_TARGET = 20_000
HARD_BUDGET = 50_000


# ============================================================================
# CAPACITY ASSUMPTIONS
# ============================================================================

# EC2 ingestion layer: EC2 Auto Scaling, On-Demand, m7i.large, shared tenancy.
# Workload pattern: daily spike traffic.
#
# [ASSUMED]
# 1,000 events/sec per ingestion EC2 node.
# m7i.large suitability for this workload.
#
# [LOAD-TEST REQUIRED]
# Validate actual ingestion throughput per EC2 instance
# using production-like event payloads.

INGESTION_EVENTS_PER_SECOND_PER_NODE = 1000

# ECS stream consumer layer: ECS on EC2, On-Demand, m7i.large, shared tenancy.
# Workload pattern: daily spike traffic.
# This is separate from the EC2 ingestion Auto Scaling layer.
#
# [ASSUMED]
# 2,000 events/sec per ECS consumer EC2 node.
# m7i.large suitability for this workload.
#
# [LOAD-TEST REQUIRED]
# Validate:
# - Kinesis consumer throughput
# - ECS task CPU usage
# - Memory usage
# - Batch processing performance
# - Downstream write performance

CONSUMER_EVENTS_PER_SECOND_PER_NODE = 2000


# HA minimums

MIN_INGESTION_NODES = 2
MIN_CONSUMER_NODES = 2


# [ASSUMED]
# 25% capacity headroom applied to peak node requirement.

CAPACITY_HEADROOM = 0.25


# PostgreSQL batching

POSTGRES_BATCH_SIZE = 500


# RDS PostgreSQL storage allocation.
#
# [VALIDATED: AWS CALCULATOR]
# 15 TB gp3 allocation.
# Includes 1 year retention + PostgreSQL overhead.
# Provisioned IOPS: 12,000
# Provisioned throughput: 500 MiB/s

RDS_STORAGE_GB = 15000


# S3 raw event store storage allocation.
#
# [VALIDATED]
# Retention: 1 year
# Stored raw event data: 11,500 GB

S3_STORAGE_GB = 11_500


# AWS Glue ETL job configuration.
#
# [ASSUMED]
# Manual database export workload only.
# Not part of the real-time ingestion or stream processing path.
# No peak scaling factor applied.

GLUE_CONFIG = {
    "dpus": 10,
    "runtime_hours_per_month": 1,
}


# Monitoring configuration.
#
# [ASSUMED - VALIDATION REQUIRED]
# Detailed observability requirements not provided.
# CloudWatch and Sentry costs are operational estimates.

MONITORING_CONFIG = {
    "cloudwatch": True,
    "sentry": True,
}


# ============================================================================
# KINESIS SETTINGS
# ============================================================================

"""
These match the AWS calculator concepts.

Kinesis cost depends on:

- records/month
- rounded record size
- ingestion volume
- retrieval volume
- consumer applications
- enhanced fan-out consumers
- retention

"""


# Number of consumer applications reading the stream.

# Example:
# analytics processor
# enrichment processor
# fraud detector

KINESIS_CONSUMER_APPLICATIONS = 1


# Enhanced fan-out consumers

KINESIS_ENHANCED_FANOUT_CONSUMERS = 0


# Retention

DEFAULT_RETENTION_HOURS = 24

EXTENDED_RETENTION_HOURS = 0


# ============================================================================
# ALB SETTINGS
# ============================================================================

"""
AWS Application Load Balancer configuration.

ALB charges per Load Balancer Capacity Unit (LCU).

The billed LCU is the maximum of four dimensions:

    - processed bytes
    - new connections
    - active connections
    - rule evaluations

This model uses the processed-bytes dimension as the driver,
derived from AWS calculator validation.

ALB_PROCESSED_BYTES_LCU is derived from monthly processed data
divided by monthly hours.

Derivation:

    Monthly traffic:
        29 baseline days x 50M events
        + 1 peak day x 500M events
        = 1.95B events/month

    Average event size:
        0.5 KB

    Monthly processed data:
        1.95B events x 0.5 KB
        = 929.83 GB/month

    Average hourly processed data:
        929.83 GB / 730 hours
        = 1.27 GB/hour

    Since ALB charges 1 LCU per 1 GB processed/hour:
        Processed bytes LCU = 1.27

Validation model:

    Capacity validation uses peak traffic.
    Cost validation uses the monthly traffic model:
        29 baseline days + 1 peak day.
"""

# [ASSUMED]
ALB_COUNT = 1


# [DERIVED]
# Processed bytes LCU: derived from AWS calculator validation.

ALB_PROCESSED_BYTES_LCU = 1.27


# [ASSUMED - VALIDATE]
# Connection metrics: not the dominant LCU dimension for this workload.

ALB_CONNECTION_LCU = 0


# [ASSUMED - VALIDATE]

ALB_ACTIVE_CONNECTION_LCU = 0


# [ASSUMED]
# Rule evaluations: single listener rule set, no complex rule charges.

ALB_RULE_EVALUATION_LCU = 0


# ============================================================================
# PRICING
# ============================================================================

"""
Planning prices.

VERIFY against selected AWS region.
"""


PRICES = {

    # ALB
    # [VENDOR-SOURCED: VERIFY]
    # Price per LCU-hour.

    "alb_lcu_price": 0.008,


    # EC2 ingestion
    # [VENDOR-SOURCED: VERIFY]
    # m7i.large On-Demand, us-east-1.

    "ec2_ingestion_hour": 0.1008,

    # EC2 stream consumer (ECS on EC2)
    # [VENDOR-SOURCED: VERIFY]
    # m7i.large On-Demand, us-east-1.

    "ec2_consumer_hour": 0.1008,


    # Kinesis On-Demand

    "kinesis_stream_hour": 0.04,

    "kinesis_ingest_gb": 0.08,

    "kinesis_retrieval_gb": 0.04,


    # Enhanced fan-out

    "kinesis_enhanced_fanout_gb": 0.015,


    # Retention

    "kinesis_extended_retention_gb_hour": 0.020,


    # RDS PostgreSQL
    # [VALIDATED: AWS CALCULATOR]
    # db.m7g.large On-Demand, Single-AZ, us-east-1.

    "rds_primary_hour": 0.168,

    "rds_replica_hour": 0.168,

    # [VALIDATED: AWS CALCULATOR]
    # gp3 storage pricing.

    "rds_storage_gb_month": 0.115,


    # Redis
    # [VALIDATED: AWS CALCULATOR]
    # ElastiCache Redis, single node, On-Demand, us-east-1.

    "redis_hour": 0.156,


    # S3
    # [VENDOR-SOURCED: VERIFY]

    "s3_gb_month": 0.023,

    "s3_put_requests_month": 19_500,

    "s3_get_requests_month": 5_000,

    "s3_put_request_price": 0.000005,

    "s3_get_request_price": 0.0000004,


    # SQS

    "sqs_million_requests": 0.40,


    # AWS Glue
    # [VENDOR-SOURCED: VERIFY]
    # Glue Spark ETL DPU-hour pricing.

    "glue_dpu_hour": 0.44,


    # Monitoring
    # [ASSUMED - VALIDATION REQUIRED]
    # Detailed observability requirements not provided.
    # These are operational cost estimates only.

    "cloudwatch_assumed_monthly": 10.00,

    "sentry_assumed_monthly": 50.00,


    # Misc

    "misc_month": 500,
}


# ============================================================================
# BASIC CALCULATIONS
# ============================================================================


def events_per_second(events_per_day):
    """
    Convert daily events into average EPS.
    """

    return events_per_day / SECONDS_PER_DAY



def throughput_mib_per_second(
        eps,
        event_size_kb
):

    bytes_per_second = (
            eps
            *
            event_size_kb
            *
            BYTES_PER_KB
    )

    return (
            bytes_per_second
            /
            BYTES_PER_MIB
    )



def raw_gb_per_day(
        events_per_day,
        event_size_kb
):

    total_bytes = (
            events_per_day
            *
            event_size_kb
            *
            BYTES_PER_KB
    )

    return total_bytes / BYTES_PER_GB



def calculate_nodes(
        peak_eps,
        eps_per_node,
        minimum_nodes
):

    required = (
            peak_eps
            /
            eps_per_node
    )


    with_headroom = (
            required
            *
            (1 + CAPACITY_HEADROOM)
    )


    return max(
        minimum_nodes,
        math.ceil(with_headroom)
    )



def postgres_batches_per_second(
        peak_eps
):

    return peak_eps / POSTGRES_BATCH_SIZE

# ============================================================================
# MONTHLY TRAFFIC MODEL
# ============================================================================

def monthly_event_volume(
        baseline_events_per_day,
        peak_multiplier,
        peak_days
):
    """
    Calculates realistic monthly traffic.

    Example:

        Baseline:
        50M/day x 29 days

        Peak:
        500M/day x 1 day

        Total:
        1.95B events/month

    This avoids the incorrect assumption that
    peak traffic happens every day.
    """

    normal_days = (
            DAYS_PER_MONTH
            -
            peak_days
    )


    baseline_volume = (
            baseline_events_per_day
            *
            normal_days
    )


    peak_volume = (
            baseline_events_per_day
            *
            peak_multiplier
            *
            peak_days
    )


    return (
            baseline_volume
            +
            peak_volume
    )



def monthly_event_volume_gb(
        baseline_events_per_day,
        peak_multiplier,
        event_size_kb,
        peak_days
):
    """
    Converts monthly event count into GB.
    """

    records = monthly_event_volume(
        baseline_events_per_day,
        peak_multiplier,
        peak_days
    )


    total_bytes = (
            records
            *
            event_size_kb
            *
            BYTES_PER_KB
    )


    return total_bytes / BYTES_PER_GB



def rounded_kinesis_record_kb(
        event_size_kb
):
    """
    Kinesis pricing rounds records.

    Example:

        0.5 KB event
        rounds to 1 KB

    """

    return math.ceil(event_size_kb)



# ============================================================================
# KINESIS COST MODEL
# ============================================================================

def kinesis_cost(
        baseline_events_per_day,
        peak_multiplier,
        event_size_kb,
        peak_days
):

    """
    Models AWS Kinesis On-Demand.

    Based on:

    - stream hours
    - records/month
    - rounded record size
    - ingestion
    - consumer retrieval
    - enhanced fan-out
    """


    records_month = monthly_event_volume(
        baseline_events_per_day,
        peak_multiplier,
        peak_days
    )


    rounded_kb = rounded_kinesis_record_kb(
        event_size_kb
    )


    total_kb_ingested = (
            records_month
            *
            rounded_kb
    )


    total_gb_ingested = (
            total_kb_ingested
            /
            1024
            /
            1024
    )


    stream_cost = (
            HOURS_PER_MONTH
            *
            PRICES["kinesis_stream_hour"]
    )


    ingest_cost = (
            total_gb_ingested
            *
            PRICES["kinesis_ingest_gb"]
    )


    total_kb_retrieved = (
            records_month
            *
            rounded_kb
            *
            KINESIS_CONSUMER_APPLICATIONS
    )

    retrieval_gb = (
            total_kb_retrieved
            /
            1024
            /
            1024
            /
            2
    )


    retrieval_cost = (
            retrieval_gb
            *
            PRICES["kinesis_retrieval_gb"]
    )


    enhanced_fanout_cost = (
            retrieval_gb
            *
            KINESIS_ENHANCED_FANOUT_CONSUMERS
            *
            PRICES["kinesis_enhanced_fanout_gb"]
    )


    extended_retention_cost = 0


    if EXTENDED_RETENTION_HOURS > 0:

        extended_retention_cost = (
                total_gb_ingested
                *
                EXTENDED_RETENTION_HOURS
                *
                PRICES[
                    "kinesis_extended_retention_gb_hour"
                ]
        )


    total = (
            stream_cost
            +
            ingest_cost
            +
            retrieval_cost
            +
            enhanced_fanout_cost
            +
            extended_retention_cost
    )


    return {

        "records_month": records_month,

        "rounded_record_kb": rounded_kb,

        "ingested_gb": total_gb_ingested,

        "retrieved_gb": retrieval_gb,

        "stream_cost": stream_cost,

        "data_ingest_cost": ingest_cost,

        "data_retrieval_cost": retrieval_cost,

        "enhanced_fanout_cost": enhanced_fanout_cost,

        "extended_retention_cost": (
            extended_retention_cost
        ),

        "total": total,
    }



# ============================================================================
# ALB COST MODEL
# ============================================================================

def calculate_alb_cost():
    """
    Models AWS Application Load Balancer cost.

    ALB cost is driven by the Load Balancer Capacity Unit (LCU).
    The billed LCU is the maximum across four dimensions:

        - processed bytes
        - new connections
        - active connections
        - rule evaluations

    Cost:

        monthly_cost =
            ALB_COUNT
            * maximum_lcu
            * alb_lcu_price
            * HOURS_PER_MONTH

    Validation model:

        Capacity validation uses peak traffic.
        Cost validation uses 29 baseline days + 1 peak day
        (monthly average LCU, NOT peak LCU).
    """

    maximum_lcu = max(
        ALB_PROCESSED_BYTES_LCU,
        ALB_CONNECTION_LCU,
        ALB_ACTIVE_CONNECTION_LCU,
        ALB_RULE_EVALUATION_LCU,
    )


    monthly_cost = (
            ALB_COUNT
            *
            maximum_lcu
            *
            PRICES["alb_lcu_price"]
            *
            HOURS_PER_MONTH
    )


    return {

        "maximum_lcu": maximum_lcu,

        "processed_bytes_lcu": ALB_PROCESSED_BYTES_LCU,

        "connection_lcu": ALB_CONNECTION_LCU,

        "active_connection_lcu": ALB_ACTIVE_CONNECTION_LCU,

        "rule_evaluation_lcu": ALB_RULE_EVALUATION_LCU,

        "monthly_cost": monthly_cost,
    }



# ============================================================================
# FULL COST MODEL
# ============================================================================

def calculate_cost_model(
        events_per_day,
        peak_multiplier,
        event_size_kb
):

    """
    Main capacity and cost calculation.
    """


    # ------------------------------------------------------------
    # Capacity calculations
    # ------------------------------------------------------------

    baseline_eps = events_per_second(
        events_per_day
    )


    peak_events_day = (
            events_per_day
            *
            peak_multiplier
    )


    peak_eps = events_per_second(
        peak_events_day
    )


    peak_mib = throughput_mib_per_second(
        peak_eps,
        event_size_kb
    )


    ingestion_nodes = calculate_nodes(
        peak_eps,
        INGESTION_EVENTS_PER_SECOND_PER_NODE,
        MIN_INGESTION_NODES
    )


    consumer_nodes = calculate_nodes(
        peak_eps,
        CONSUMER_EVENTS_PER_SECOND_PER_NODE,
        MIN_CONSUMER_NODES
    )


    # ------------------------------------------------------------
    # Monthly traffic
    # ------------------------------------------------------------

    monthly_records = monthly_event_volume(
        events_per_day,
        peak_multiplier,
        PEAK_DAYS_PER_MONTH
    )


    monthly_raw_gb = monthly_event_volume_gb(
        events_per_day,
        peak_multiplier,
        event_size_kb,
        PEAK_DAYS_PER_MONTH
    )


    # ------------------------------------------------------------
    # Kinesis
    # ------------------------------------------------------------

    kinesis = kinesis_cost(
        events_per_day,
        peak_multiplier,
        event_size_kb,
        PEAK_DAYS_PER_MONTH
    )


    # ------------------------------------------------------------
    # Cost components
    # ------------------------------------------------------------

    costs = {}


    # ALB

    alb = calculate_alb_cost()

    costs["ALB"] = alb["monthly_cost"]


    # EC2 ingestion

    costs["EC2 ingestion"] = (
            ingestion_nodes
            *
            PRICES["ec2_ingestion_hour"]
            *
            HOURS_PER_MONTH
    )


    # Kinesis

    costs["Kinesis Data Streams"] = (
        kinesis["total"]
    )


    # Consumers

    costs["EC2 stream consumers"] = (
            consumer_nodes
            *
            PRICES["ec2_consumer_hour"]
            *
            HOURS_PER_MONTH
    )


    # RDS

    rds_storage_cost = (
            RDS_STORAGE_GB
            *
            PRICES["rds_storage_gb_month"]
    )


    costs["RDS PostgreSQL primary"] = (
            PRICES["rds_primary_hour"]
            *
            HOURS_PER_MONTH
            +
            rds_storage_cost
    )


    costs["RDS PostgreSQL read replica"] = (
            PRICES["rds_replica_hour"]
            *
            HOURS_PER_MONTH
            +
            rds_storage_cost
    )


    # Redis
    #
    # [REQUIREMENT]
    # Single Redis node deployment.
    #
    # Purpose:
    # - personalization cache
    # - real-time dashboard state
    #
    # Cost model:
    # Redis is provisioned capacity, therefore the 10x traffic
    # peak does NOT directly multiply Redis cost.
    #
    # [ASSUMED - VALIDATION REQUIRED]
    # Peak traffic may impact Redis capacity requirements:
    # - cache operations/sec
    # - memory utilization
    # - key count
    # - object size
    #
    # The challenge does not provide:
    # - Redis object size
    # - number of cached keys
    # - cache hit ratio
    # - Redis throughput requirements
    #
    # Therefore Redis cost remains fixed, while capacity validation
    # remains an open validation item.

    redis_nodes = 1

    costs["ElastiCache Redis"] = (
            redis_nodes
            *
            PRICES["redis_hour"]
            *
            HOURS_PER_MONTH
    )


    # S3 Raw Event Store
    #
    # [REQUIREMENT]
    # Retention: 1 year
    #
    # Responsibilities:
    # - Replay buffer
    # - Batch write safety
    # - Migration validation source of truth
    #
    # Architecture:
    # Ingestion nodes write directly to S3.
    # S3 does not receive data from Kinesis.
    #
    # [ASSUMED - VALIDATION REQUIRED]
    # Events are batched into S3 objects.
    #
    # PUT requests:
    # 19,500/month
    #
    # Replay:
    # One monthly full replay validation.
    #
    # GET requests:
    # 5,000/month

    s3_storage_cost = (
            S3_STORAGE_GB
            *
            PRICES["s3_gb_month"]
    )


    s3_put_cost = (
            PRICES["s3_put_requests_month"]
            *
            PRICES["s3_put_request_price"]
    )


    s3_get_cost = (
            PRICES["s3_get_requests_month"]
            *
            PRICES["s3_get_request_price"]
    )


    costs["S3 raw event store"] = (
            s3_storage_cost
            +
            s3_put_cost
            +
            s3_get_cost
    )


    # SQS Dead Letter Queue
    #
    # [REQUIREMENT]
    # SQS is used only for failed event capture and retry handling
    # from ingestion nodes.
    # SQS is NOT part of the main ingestion path.
    #
    # Failure model:
    # Baseline: normal ingestion failures are negligible.
    # Peak:     3% data loss during peak periods.
    #
    # Peak ingestion records (1 peak day):
    peak_ingestion_records = (
            BASELINE_EVENTS_PER_DAY
            *
            PEAK_MULTIPLIER
    )

    # Failed events = peak ingestion records * 3%
    sqs_failed_events_peak = (
            peak_ingestion_records
            *
            0.03
    )

    # Each failed event generates 3 SQS requests:
    # 1 SendMessage + 1 ReceiveMessage + 1 DeleteMessage
    sqs_requests = (
            sqs_failed_events_peak
            *
            3
    )

    costs["SQS DLQ"] = (
            sqs_requests
            /
            1_000_000
            *
            PRICES["sqs_million_requests"]
    )


    # AWS Glue ETL
    #
    # [REQUIREMENT]
    # Manual PostgreSQL export to data warehouse.
    # Glue is not part of real-time ingestion or stream processing.
    # No peak scaling factor applied.
    #
    # Calculation:
    # DPUs x runtime hours x DPU-hour price

    glue_cost = (
            GLUE_CONFIG["dpus"]
            *
            GLUE_CONFIG["runtime_hours_per_month"]
            *
            PRICES["glue_dpu_hour"]
    )

    costs["AWS Glue ETL"] = glue_cost


    # Monitoring
    #
    # [ASSUMED - VALIDATION REQUIRED]
    # Detailed observability requirements not provided.
    # CloudWatch and Sentry costs are operational estimates only.

    monitoring_cloudwatch = (
        PRICES["cloudwatch_assumed_monthly"]
        if MONITORING_CONFIG["cloudwatch"]
        else 0
    )

    monitoring_sentry = (
        PRICES["sentry_assumed_monthly"]
        if MONITORING_CONFIG["sentry"]
        else 0
    )

    monitoring_cost = (
            monitoring_cloudwatch
            +
            monitoring_sentry
    )

    costs["Monitoring"] = monitoring_cost


    costs["Misc / EBS / network"] = (
        PRICES["misc_month"]
    )


    return {

        "baseline_eps": baseline_eps,

        "peak_eps": peak_eps,

        "peak_mib_per_sec": peak_mib,

        "peak_events_per_day": peak_events_day,

        "monthly_records": monthly_records,

        "monthly_raw_gb": monthly_raw_gb,

        "ingestion_nodes": ingestion_nodes,

        "consumer_nodes": consumer_nodes,

        "kinesis": kinesis,

        "alb": alb,

        "sqs": {
            "baseline_dlq_messages": 0,
            "peak_dlq_messages": sqs_failed_events_peak,
            "total_sqs_requests": sqs_requests,
            "monthly_cost": costs["SQS DLQ"],
        },

        "glue": {
            "dpus": GLUE_CONFIG["dpus"],
            "runtime_hours_per_month": GLUE_CONFIG["runtime_hours_per_month"],
            "monthly_cost": glue_cost,
        },

        "monitoring": {
            "cloudwatch_monthly": monitoring_cloudwatch,
            "sentry_monthly": monitoring_sentry,
            "monthly_cost": monitoring_cost,
        },

        "costs": costs,

        "total": sum(costs.values())
    }

# ============================================================================
# REPORTING
# ============================================================================

def print_report(model):

    print("=" * 72)
    print("REAL-TIME ANALYTICS: CAPACITY + COST MODEL v1.1")
    print("=" * 72)

    print()

    print("TRAFFIC MODEL")
    print("-" * 72)

    print(
        f"Baseline events/day: "
        f"{BASELINE_EVENTS_PER_DAY:,}"
    )

    print(
        f"Peak multiplier:     "
        f"{PEAK_MULTIPLIER}x"
    )

    print(
        f"Peak events/day:     "
        f"{model['peak_events_per_day']:,}"
    )

    print(
        f"Monthly records:     "
        f"{model['monthly_records']:,}"
    )

    print(
        "Monthly calculation: "
        f"{DAYS_PER_MONTH - PEAK_DAYS_PER_MONTH} baseline days "
        f"+ {PEAK_DAYS_PER_MONTH} peak day"
    )

    print()


    print("CAPACITY")
    print("-" * 72)

    print(
        f"Baseline EPS:         "
        f"{model['baseline_eps']:,.2f}"
    )

    print(
        f"Peak EPS:             "
        f"{model['peak_eps']:,.2f}"
    )

    print(
        f"Peak throughput:      "
        f"{model['peak_mib_per_sec']:,.2f} MiB/s"
    )

    print(
        f"Ingestion nodes:      "
        f"{model['ingestion_nodes']} EC2 instances (baseline)"
    )

    print(
        f"Scaling model:        EC2 Auto Scaling"
    )

    print(
        f"Peak handling:        Scale-out capacity required during 10x traffic periods"
    )

    print()

    print(
        f"Stream consumers:     {model['consumer_nodes']} ECS tasks on EC2 (baseline)"
    )

    print(
        f"Scaling model:        ECS Service Auto Scaling"
    )

    print(
        f"Peak handling:        Scale-out capacity required during traffic spikes"
    )

    print()

    print(
        f"Note: EC2 Auto Scaling maintains ingestion throughput during peak traffic."
    )

    print(
        f"      ECS Service Auto Scaling is separate from the EC2 ingestion layer."
    )

    print()


    print("KINESIS AUDIT")
    print("-" * 72)

    k = model["kinesis"]

    print(
        f"Mode:                 Kinesis Data Streams On-Demand"
    )

    print(
        f"Capacity model:       Automatic scaling based on ingestion traffic"
    )

    print(
        f"Shard count:          Not modeled (On-Demand pricing)"
    )

    print()

    print(
        f"Consumer applications:"
        f" {KINESIS_CONSUMER_APPLICATIONS}"
    )

    print(
        f"Enhanced fan-out:     "
        f"{KINESIS_ENHANCED_FANOUT_CONSUMERS}"
    )

    print(
        f"Rounded record size:  "
        f"{k['rounded_record_kb']} KB"
    )

    print(
        f"Records/month:        "
        f"{k['records_month']:,}"
    )

    print(
        f"Ingested GB/month:    "
        f"{k['ingested_gb']:,.2f}"
    )

    print(
        f"Retrieved GB/month:   "
        f"{k['retrieved_gb']:,.2f}"
    )

    print()

    print(
        f"Stream cost:          "
        f"${k['stream_cost']:,.2f}"
    )

    print(
        f"Data ingest cost:     "
        f"${k['data_ingest_cost']:,.2f}"
    )

    print(
        f"Data retrieval cost: "
        f"${k['data_retrieval_cost']:,.2f}"
    )

    print(
        f"Enhanced fan-out:    "
        f"${k['enhanced_fanout_cost']:,.2f}"
    )

    print(
        f"Total Kinesis:        "
        f"${k['total']:,.2f}"
    )

    print()


    print("ALB CAPACITY AUDIT")
    print("-" * 72)

    monthly_processed_gb = (
        model["monthly_raw_gb"]
    )

    avg_processed_throughput_gb_hr = (
            monthly_processed_gb
            /
            HOURS_PER_MONTH
    )

    peak_events_day = model["peak_events_per_day"]

    peak_eps = model["peak_eps"]

    peak_throughput_mib = model["peak_mib_per_sec"]

    print(
        f"Monthly processed data:      "
        f"{monthly_processed_gb:,.2f} GB/month"
    )

    print(
        f"Average processed throughput:"
        f" {avg_processed_throughput_gb_hr:,.2f} GB/hour"
    )

    print(
        f"Processed bytes LCU:         "
        f"{model['alb']['processed_bytes_lcu']:,.2f}"
    )

    print(
        f"Peak capacity validation:"
    )

    print(
        f"  Peak events:               "
        f"{peak_events_day:,}/day"
    )

    print(
        f"  Peak EPS:                  "
        f"{peak_eps:,.0f} events/sec"
    )

    print(
        f"  Peak throughput:           "
        f"{peak_throughput_mib:,.2f} MiB/sec"
    )

    print()


    print("ALB COST AUDIT")
    print("-" * 72)

    a = model["alb"]

    print(
        f"Processed bytes LCU:         "
        f"{a['processed_bytes_lcu']:,.2f}"
    )

    print(
        f"Maximum LCUs:                "
        f"{a['maximum_lcu']:,.2f}"
    )

    print(
        f"Monthly ALB LCU cost:        "
        f"${a['monthly_cost']:,.2f}"
    )

    print()


    print("RDS POSTGRESQL AUDIT")
    print("-" * 72)

    rds_primary_cost = (
            PRICES["rds_primary_hour"]
            *
            HOURS_PER_MONTH
            +
            RDS_STORAGE_GB
            *
            PRICES["rds_storage_gb_month"]
    )

    rds_replica_cost = (
            PRICES["rds_replica_hour"]
            *
            HOURS_PER_MONTH
            +
            RDS_STORAGE_GB
            *
            PRICES["rds_storage_gb_month"]
    )

    print(
        f"Deployment topology:   Primary PostgreSQL writer"
    )

    print(
        f"                       + PostgreSQL Read Replica for read scaling/export workloads"
    )

    print(
        f"Deployment type:       Single-AZ (Multi-AZ not configured)"
    )

    print()

    print(
        f"Primary instance:      db.m7g.large"
    )

    print(
        f"Primary storage:       {RDS_STORAGE_GB:,} GB gp3"
    )

    print(
        f"Primary monthly cost:  ${rds_primary_cost:,.2f}"
    )

    print()

    print(
        f"Read replica:          db.m7g.large"
    )

    print(
        f"Replica storage:       {RDS_STORAGE_GB:,} GB gp3"
    )

    print(
        f"Replica monthly cost:  ${rds_replica_cost:,.2f}"
    )

    print()


    print("ELASTICACHE REDIS AUDIT")
    print("-" * 72)

    redis_monthly_cost = (
            1
            *
            PRICES["redis_hour"]
            *
            HOURS_PER_MONTH
    )

    print(
        f"Deployment:           Single node"
    )

    print(
        f"Purpose:              Personalization + real-time dashboard state"
    )

    print(
        f"Pricing model:        On-Demand"
    )

    print(
        f"Data tiering:         Disabled"
    )

    print(
        f"TTL:                  24 hours"
    )

    print(
        f"Node count:           1"
    )

    print()

    print(
        f"Monthly cost:         ${redis_monthly_cost:,.2f}"
    )

    print()

    print(
        f"Peak impact:"
    )

    print(
        f"Cost impact:          None"
    )

    print(
        f"Scaling impact:       No additional Redis nodes modeled"
    )

    print(
        f"Validation required:  Cache hit ratio, memory utilization, operations/sec"
    )

    print()

    print(
        f"Missing inputs:"
    )

    print(
        f"- Redis object size"
    )

    print(
        f"- Number of keys"
    )

    print(
        f"- Cache hit ratio"
    )

    print(
        f"- Operations/sec"
    )

    print()


    print("S3 RAW EVENT STORE AUDIT")
    print("-" * 72)

    s3_storage_cost = (
            S3_STORAGE_GB
            *
            PRICES["s3_gb_month"]
    )

    s3_put_cost = (
            PRICES["s3_put_requests_month"]
            *
            PRICES["s3_put_request_price"]
    )

    s3_get_cost = (
            PRICES["s3_get_requests_month"]
            *
            PRICES["s3_get_request_price"]
    )

    s3_total = (
            s3_storage_cost
            +
            s3_put_cost
            +
            s3_get_cost
    )

    print(
        f"Storage class:        S3 Standard"
    )

    print(
        f"Retention:            1 year"
    )

    print(
        f"Stored data:          {S3_STORAGE_GB:,} GB"
    )

    print()

    print(
        f"Monthly PUT requests: {PRICES['s3_put_requests_month']:,}"
    )

    print(
        f"Monthly GET requests: {PRICES['s3_get_requests_month']:,}"
    )

    print()

    print(
        f"Storage cost:         ${s3_storage_cost:,.2f}"
    )

    print(
        f"PUT request cost:     ${s3_put_cost:,.2f}"
    )

    print(
        f"GET request cost:     ${s3_get_cost:,.2f}"
    )

    print()

    print(
        f"Total S3:             ${s3_total:,.2f}"
    )

    print()


    print("SQS DLQ AUDIT")
    print("-" * 72)

    sq = model["sqs"]

    print(
        f"Queue type:                Standard SQS"
    )

    print(
        f"Role:                      Ingestion node DLQ only"
    )

    print(
        f"Failure rate (peak):       3%"
    )

    print()

    print(
        f"Baseline DLQ messages:     {int(sq['baseline_dlq_messages']):,}/month"
    )

    print(
        f"Peak DLQ messages:         {int(sq['peak_dlq_messages']):,}/month"
    )

    print(
        f"Total SQS requests:        {int(sq['total_sqs_requests']):,}/month"
    )

    print(
        f"  (3 requests per event: SendMessage + ReceiveMessage + DeleteMessage)"
    )

    print()

    print(
        f"Monthly SQS cost:          ${sq['monthly_cost']:,.2f}"
    )

    print()


    print("AWS GLUE ETL AUDIT")
    print("-" * 72)

    gl = model["glue"]

    print(
        f"Service:              AWS Glue Spark ETL Jobs"
    )

    print(
        f"Workload:             Manual PostgreSQL export to data warehouse"
    )

    print(
        f"Pipeline role:        Batch analytics/export only"
    )

    print(
        f"                      Not part of real-time ingestion path"
    )

    print(
        f"Peak scaling:         None (not on ingestion path)"
    )

    print()

    print(
        f"DPU allocation:       {gl['dpus']}"
    )

    print(
        f"Runtime per month:    {gl['runtime_hours_per_month']} hour"
    )

    print(
        f"Monthly Glue cost:    ${gl['monthly_cost']:,.2f}"
    )

    print()


    print("MONITORING AUDIT (Operational Estimate)")
    print("-" * 72)

    mo = model["monitoring"]

    print(
        f"Note:"
    )

    print(
        f"  Detailed observability requirements were not provided."
    )

    print(
        f"  CloudWatch and Sentry costs are assumed operational estimates."
    )

    print()

    print(
        f"CloudWatch (assumed): ${mo['cloudwatch_monthly']:,.2f}/month"
    )

    print(
        f"Sentry (assumed):     ${mo['sentry_monthly']:,.2f}/month"
    )

    print()

    print(
        f"Monthly monitoring:   ${mo['monthly_cost']:,.2f}"
    )

    print()



def print_costs(model):

    print("MONTHLY COST")
    print("-" * 72)

    for name, value in model["costs"].items():

        print(
            f"{name:30}"
            f"${value:,.2f}"
        )


    print("-" * 72)

    print(
        f"{'TOTAL':30}"
        f"${model['total']:,.2f}"
    )

    print()



def print_budget(model):

    print("BUDGET VALIDATION")
    print("-" * 72)


    target_difference = (
            ENGINEERING_TARGET
            -
            model["total"]
    )


    budget_difference = (
            HARD_BUDGET
            -
            model["total"]
    )


    print(
        f"Engineering target: "
        f"${ENGINEERING_TARGET:,.2f}"
    )

    print(
        f"Target headroom:    "
        f"${target_difference:,.2f}"
    )


    print(
        "Target status:      "
        +
        (
            "PASS"
            if target_difference >= 0
            else "FAIL"
        )
    )

    print()


    print(
        f"Hard budget:        "
        f"${HARD_BUDGET:,.2f}"
    )

    print(
        f"Budget headroom:   "
        f"${budget_difference:,.2f}"
    )


    print(
        "Budget status:     "
        +
        (
            "PASS"
            if budget_difference >= 0
            else "FAIL"
        )
    )

    print()



# ============================================================================
# SENSITIVITY ANALYSIS
# ============================================================================

def sensitivity():

    print("SENSITIVITY")
    print("-" * 72)

    print(
        "payload   peak     monthly records      monthly cost"
    )


    payloads = [
        0.5,
        1,
        2,
        5
    ]


    peaks = [
        10,
        20,
        50
    ]


    for payload in payloads:

        for peak in peaks:

            model = calculate_cost_model(
                BASELINE_EVENTS_PER_DAY,
                peak,
                payload
            )


            print(
                f"{payload:>5.1f}KB "
                f"{peak:>5}x "
                f"{model['monthly_records']:>15,} "
                f"${model['total']:>12,.2f}"
            )


    print()



# ============================================================================
# JSON REPORT
# ============================================================================

def create_json(model):

    return {

        "inputs": {

            "baseline_events_per_day":
                BASELINE_EVENTS_PER_DAY,

            "peak_multiplier":
                PEAK_MULTIPLIER,

            "peak_days_per_month":
                PEAK_DAYS_PER_MONTH,

            "event_size_kb":
                DEFAULT_EVENT_SIZE_KB,
        },


        "capacity": {

            "baseline_eps":
                model["baseline_eps"],

            "peak_eps":
                model["peak_eps"],

            "ingestion_nodes":
                model["ingestion_nodes"],

            "consumer_nodes":
                model["consumer_nodes"],
        },


        "traffic": {

            "monthly_records":
                model["monthly_records"],

            "monthly_raw_gb":
                model["monthly_raw_gb"],
        },


        "kinesis":
            model["kinesis"],


        "alb":
            model["alb"],


        "s3": {

            "storage_class":
                "S3 Standard",

            "retention_years":
                1,

            "storage_gb":
                S3_STORAGE_GB,

            "put_requests_month":
                PRICES["s3_put_requests_month"],

            "get_requests_month":
                PRICES["s3_get_requests_month"],

            "monthly_cost":
                model["costs"]["S3 raw event store"],
        },


        "costs":
            model["costs"],


        "total":
            model["total"],


        "pricing_note":
            "AWS pricing values require verification."
    }



# ============================================================================
# MAIN
# ============================================================================

def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(
        "--json-output",
        default=None
    )


    args = parser.parse_args()


    model = calculate_cost_model(
        BASELINE_EVENTS_PER_DAY,
        PEAK_MULTIPLIER,
        DEFAULT_EVENT_SIZE_KB
    )


    print_report(model)

    print_costs(model)

    print_budget(model)

    sensitivity()


    if args.json_output:

        with open(
                args.json_output,
                "w",
                encoding="utf-8"
        ) as f:

            json.dump(
                create_json(model),
                f,
                indent=2
            )


        print(
            f"JSON written to {args.json_output}"
        )



if __name__ == "__main__":

    main()