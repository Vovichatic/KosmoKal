from .base import Source, SourceStatus, HttpSource
from .swpc import GoesProtons, PlanetaryKp, SwpcAlerts
from .celestrak import IssElements

from .planning import ThreeDayForecast, Socrates

REGISTRY = {
    s.source_id: s
    for s in (GoesProtons(), PlanetaryKp(), SwpcAlerts(), IssElements(), ThreeDayForecast(), Socrates())
}
__all__ = ["Source", "SourceStatus", "HttpSource", "REGISTRY",
           "GoesProtons", "PlanetaryKp", "SwpcAlerts", "IssElements"]
