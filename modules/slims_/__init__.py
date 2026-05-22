"""SLIMS module for cellophane."""

from .src.connection import PaginatedSlims
from .src.hooks import slims_fetch, slims_sync_post, slims_sync_pre
from .src.mixins import SlimsSample, SlimsSamples
from .src.util import (
    get_field,
    get_records,
    parse_criteria,
    resolve_criteria,
    unnest_criteria,
    validate_criteria,
)

__all__ = [
    "slims_sync_pre",
    "slims_sync_post",
    "slims_fetch",
    "get_field",
    "get_records",
    "parse_criteria",
    "split_criteria",
    "unnest_criteria",
    "resolve_criteria",
    "validate_criteria",
    "SlimsSample",
    "SlimsSamples",
    "PaginatedSlims",
]
