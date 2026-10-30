"""
Job Collectors module for Job Hunter v2.
"""

from src.collectors.base import JobSourceAdapter, RawJobPosting
from src.collectors.arbeitnow import ArbeitnowAdapter
from src.collectors.jobicy import JobicyAdapter
from src.collectors.ats_boards import GreenhousePublicAdapter
from src.collectors.aggregator import JobCollectorAggregator, CollectionReport, is_target_role

__all__ = [
    "JobSourceAdapter",
    "RawJobPosting",
    "ArbeitnowAdapter",
    "JobicyAdapter",
    "GreenhousePublicAdapter",
    "JobCollectorAggregator",
    "CollectionReport",
    "is_target_role",
]
