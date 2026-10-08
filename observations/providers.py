"""Provider adapter interface and shared HTTP helper.

Provider-specific code lives in ``usgs.py`` / ``usace.py``.  A provider turns (station, parameter, date range)
into a tidy raw table with a ``DateTime`` column (naive, local clock of the source) plus provider-specific
columns; the processing layer converts raw tables into canonical units.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd
import requests

from core.exceptions import ProviderError
from observations.station_catalog import Station

logger = logging.getLogger(__name__)

USER_AGENT = "RAS-Sediment-Calibration-Workbench/1.0 (+research use)"


@dataclass
class FetchResult:
    df: pd.DataFrame
    units: dict[str, str] = field(default_factory=dict)
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)
    revision: str = ""


class ObservationProvider(ABC):
    """Base class for observation providers."""
    name: str = "provider"
    # parameter key -> human description
    parameters: dict[str, str] = {}

    def handles(self, parameter: str) -> bool:
        return parameter in self.parameters

    @abstractmethod
    def fetch(self, station: Station, parameter: str, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
        """Download one parameter for one station and date range (inclusive days)."""


def http_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 90.0,
             retries: int = 2) -> requests.Response:
    """GET with retry/backoff; failures become :class:`ProviderError` with a readable message."""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            logger.warning("HTTP error (%d/%d) %s: %s", attempt + 1, retries + 1, url, exc)
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code in (200, 204, 404):
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            last = ProviderError(f"Server returned HTTP {resp.status_code}")
            time.sleep(2.0 * (attempt + 1))
            continue
        raise ProviderError(f"The data service rejected the request (HTTP {resp.status_code}): {resp.text[:200]}")
    raise ProviderError(f"Could not reach the data service ({url.split('/')[2]}). Check the network connection. "
                        f"Detail: {last}")
