"""
Base interface and data models for Job Source Adapters in Job Hunter v2.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class RawJobPosting:
    """Canonical raw job representation returned by source adapters."""
    source: str
    source_job_id: str
    title: str
    company: str
    url: str
    description: str
    location: str = "Unknown"
    is_remote: bool = False
    published_at: Optional[str] = None
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class JobSourceAdapter(ABC):
    """Abstract Base Class for modular job feed adapters."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this job source."""
        pass

    @abstractmethod
    def fetch_jobs(self, limit: int = 50) -> List[RawJobPosting]:
        """
        Fetch new job postings from the external source.
        
        Args:
            limit: Maximum number of jobs to fetch in this cycle.
            
        Returns:
            List of RawJobPosting instances.
        """
        pass
