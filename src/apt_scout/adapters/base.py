from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..models import Listing


@dataclass
class AdapterResult:
    """Outcome of one source's fetch.

    An adapter reports failure by returning this with an error string, never by
    raising. The orchestrator relies on that to keep one broken source from
    ending a run.
    """

    source: str
    listings: list[Listing] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class SourceAdapter(Protocol):
    name: str

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult: ...
