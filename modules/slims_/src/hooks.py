"""Module for getting samples from SLIMS"""

from datetime import datetime, timedelta
from logging import LoggerAdapter
from typing import Any, Sequence
from warnings import warn

from cellophane import Config, Samples, post_hook, pre_hook
from humanfriendly import parse_timespan
from slims.internal import Record
from slims.slims import Slims

from .mixins import SlimsSample, SlimsSamples
from .util import get_records


def _augment_sample(
    sample: SlimsSample,
    records: Sequence[Record],
    match: list[str] | None = None,
    map_: dict[str, Any] | None = None,
):
    """Augment existing samples with SLIMS records."""
    _map = {"id": "cntn_id"} | (map_ or {})

    matching_record = None
    for record in records:
        if sample.matches_record(record, _map, match):
            if matching_record is not None:
                warn(f"Multiple records match sample '{sample.id}'")
                return
            matching_record = record

    if matching_record is None:
        warn(f"No records match sample '{sample.id}' with run={getattr(sample,'run',None)}")
        return

    sample.map_from_record(matching_record, _map)


@pre_hook(label="SLIMS Fetch", before=["hcp_fetch", "slims_derive"])
def slims_fetch(
    samples: Samples,
    config: Config,
    logger: LoggerAdapter,
    **_,
) -> SlimsSamples | None:
    """Load novel samples from SLIMS."""
    if any(w not in config.slims for w in ["url", "username", "password"]):
        logger.warning("SLIMS connection not configured")
        return None

    criteria: str
    if not (criteria := config.slims.get("criteria")):
        logger.warning("No SLIMS criteria - Skipping fetch")
        return None

    slims_connection = Slims(
        name=__package__,
        url=config.slims.url,
        username=config.slims.username,
        password=config.slims.password,
    )

    if samples:
        logger.info("Augmenting existing samples with info from SLIMS")
        criteria = f"({criteria}) and cntn_id one_of {' '.join(s.id for s in samples)}"

    else:
        logger.info("Fetching novel samples from SLIMS")
        min_date = datetime.now() - timedelta(
            seconds=parse_timespan(config.slims.novel.max_age)
        )
        # SLIMS expects ISO 8601 timestamps
        criteria = (
            f"({criteria}) and cntn_createdOn greater_than {min_date.isoformat()}"
        )
        if (novel_criteria := config.slims.novel.get("criteria")) is not None:
            criteria = f"({criteria}) and ({novel_criteria})"

    records = get_records(
        criteria=criteria,
        connection=slims_connection,
    )
    if not records:
        logger.warning("No SLIMS records found")
        return None

    if not samples:
        logger.info(f"Found {len(records)} novel SLIMS samples")
        return samples.from_records(records, config)
    for sample in samples:
        _augment_sample(
            sample=sample,
            records=records,
            map_=config.slims.map,
            match=config.slims.match,
        )
    return samples


def _sync_hook(config: Config, samples: SlimsSamples, logger: LoggerAdapter):
    if config.slims.dry_run:
        logger.info("Dry run - Not updating SLIMS")
        return samples

    if config.slims.sync:
        logger.info("Syncing fields to SLIMS record(s)")
        samples.sync_records(config)
    else:
        logger.debug("No fields to sync to SLIMS record(s)")

    if config.slims.derive:
        logger.info("Updating derived record(s)")
        samples.sync_derived(config)
    else:
        logger.debug("No derived records to update")

    return samples


@pre_hook(label="SLIMS Sync (Pre)", after=["slims_fetch"])
def slims_sync_pre(
    samples: SlimsSamples,
    config: Config,
    logger: LoggerAdapter,
    **_,
) -> SlimsSamples:
    """Add derived content to SLIMS samples"""
    return _sync_hook(config, samples, logger)


@post_hook(label="SLIMS Sync (Post)")
def slims_sync_post(
    samples: Samples,
    config: Config,
    logger: LoggerAdapter,
    **_,
) -> Samples:
    """Add derived content to SLIMS samples"""
    return _sync_hook(config, samples, logger)
