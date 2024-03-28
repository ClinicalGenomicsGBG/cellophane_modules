"""Module for getting samples from SLIMS"""

from copy import deepcopy
from functools import reduce
from logging import LoggerAdapter
from typing import Literal

from attrs import define, field, fields_dict
from attrs.setters import validate
from cellophane import cfg, data, modules, util
from slims.slims import Record, Slims

from .src.util import get_field, get_records


@define(slots=False)
class SlimsSample(data.Sample):
    """A sample container with SLIMS integration"""

    derived: list[tuple[Record, dict]] | None = field(default=None, on_setattr=validate)
    record: Record | None = field(default=None, on_setattr=validate)
    state: Literal["novel", "running", "complete", "error"] = field(
        default="novel", on_setattr=validate
    )
    _connection: Slims | None = field(default=None, init=False)

    @classmethod
    def from_record(cls, record: Record, config: cfg.Config, **kwargs):
        """Create a sample from a SLIMS fastq record"""
        _sample = cls(
            id=record.cntn_id.value,
            state="novel",
            **kwargs,
        )
        _map = config.slims.get("map", {})
        _keys = util.map_nested_keys(_map)
        try:
            for key in _keys:
                if len(key) == 1 and key[0] in kwargs:
                    continue
                _field = reduce(lambda x, y: x[y], key, _map)
                _value = get_field(record, _field)
                if key[0] == "meta":
                    _sample.meta[key[1:]] = _value
                elif key[0] in fields_dict(cls):
                    node = reduce(getattr, key[:-1], _sample)
                    setattr(node, key[-1], _value)
                else:
                    raise KeyError
        except Exception as exc:
            raise KeyError(
                f"Unable to map '{'.'.join(key)}' to field in sample"
            ) from exc

        _sample.record = record
        return _sample

    def update_derived(
        self,
        config: cfg.Config,
    ):
        """Update/add derived records for the sample"""
        if not self.derived:
            self.derived = [(None, key_map) for key_map in config.slims.derive]
        if self.record:
            for idx, (record, key_map) in enumerate(self.derived):
                fields = {
                    key: value.format(sample=self) if isinstance(value, str) else value
                    for key, value in key_map.items()
                }
                fields |= {
                    "cntn_id": self.record.cntn_id.value,
                    "cntn_fk_originalContent": self.pk,
                    "cntn_fk_user": config.slims.username,
                }
                if record:
                    self.derived[idx] = (record.update(fields), key_map)
                elif self.connection:
                    self.derived[idx] = (
                        self.connection.add("Content", fields),
                        key_map,
                    )

    @derived.validator
    def _validate_derived(
        self,
        attribute: str,
        value: list[tuple[Record | None, dict]] | None,
    ):
        if not (value is None or isinstance(value, list)):
            raise ValueError(f"Expected 'None|list', got {value}")
        elif value is not None and not all(
            isinstance(v, tuple)
            and len(v) == 2
            and (isinstance(v[0], Record) or v[0] is None)
            and isinstance(v[1], dict)
            for v in value
        ):
            raise ValueError(
                f"Expected 'list[tuple[Record|None, dict]' for {attribute}, got {value}"
            )

    @record.validator
    def _validate_record(self, attribute: str, value: Record | None):
        if not (value is None or isinstance(value, Record)):
            raise ValueError(
                f"Expected 'NoneType' or 'Record' for {attribute}, got {value}"
            )

    @state.validator
    def _validate_state(
        self, attribute: str, value: Literal["novel", "running", "complete", "error"]
    ):
        if value not in ["novel", "running", "complete", "error"]:
            raise ValueError(f"Invalid value for {attribute}: {value}")

    @property
    def pk(self):
        """Get the primary key of the record"""
        return self.record.pk() if self.record is not None else None


    @property
    def connection(self) -> Slims | None:
        """Get a connection to SLIMS from the record"""
        if self._connection is None and self.record:
            self._connection = Slims(
                "cellophane",
                url=self.record.slims_api.raw_url,
                username=self.record.slims_api.username,
                password=self.record.slims_api.password,
            )

        return self._connection

    def __reduce__(self) -> str | tuple:
        """Remove open connection before pickle"""
        self._connection = None
        return super().__reduce__()


@data.Sample.merge.register("record")
def _(this, _):
    return this


@data.Sample.merge.register("_connection")
def _(*_):
    return None


@data.Sample.merge.register("state")
def _(this, that):
    if any(s != "complete" for s in (this, that)):
        return "error"
    else:
        return "complete"


@data.Sample.merge.register("derived")
def _(this, that):
    if not this or that is None:
        return (this or []) + (that or [])


class SlimsSamples(data.Samples):
    """A list of sample containers with SLIMS integration"""

    @classmethod
    def from_records(
        cls,
        records: list[Record],
        config: cfg.Config,
    ) -> "SlimsSamples":
        """Get samples from SLIMS records"""
        return cls(
            [
                cls.sample_class.from_record(  # pylint: disable=no-member
                    record=record, config=config
                )
                for record in records
            ]
        )

    @classmethod
    def from_criteria(
        cls,
        criteria: str,
        config: cfg.Config,
        connection: Slims | None = None,
        **kwargs,
    ) -> "SlimsSamples":
        """Get samples from SLIMS records"""
        _connection = connection or Slims(
            name=__package__,
            url=config.slims.url,
            username=config.slims.username,
            password=config.slims.password,
        )
        records = get_records(
            string_criteria=criteria,
            connection=_connection,
            **kwargs,
        )

        return cls.from_records(records, config)

    def update_derived(
        self,
        config: cfg.Config,
    ) -> None:
        """Update derived records in SLIMS"""
        for sample in self:
            sample.update_derived(config)

    def set_state(self, value: Literal["novel", "running", "complete", "error"]):
        """Set the state of the samples"""
        for sample in self:
            sample.state = value


@modules.pre_hook(label="SLIMS Fetch", before=["hcp_fetch", "slims_bioinformatics"])
def slims_fetch(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> SlimsSamples | None:
    """Load novel samples from SLIMS."""
    if any(w not in config.slims for w in ["url", "username", "password"]):
        logger.warning("SLIMS connection not configured")
        return

    slims_connection = Slims(
        name=__package__,
        url=config.slims.url,
        username=config.slims.username,
        password=config.slims.password,
    )

    slims_ids: list[str] | None = None
    if samples:
        logger.info("Augmenting existing samples with info from SLIMS")
        slims_ids = [s.id for s in samples]

    elif config.slims.get("id"):
        logger.info("Fetching samples from SLIMS by ID")
        slims_ids = config.slims.id

    records = get_records(
        string_criteria=config.slims.find_criteria,
        connection=slims_connection,
        slims_id=slims_ids,
        max_age=config.slims.novel_max_age,
        unrestrict_parents=config.slims.unrestrict_parents,
    )

    if not records:
        logger.warning("No SLIMS samples found")
        return None

    if samples:
        slims_samples = samples.from_records(records, config)
        for sample in deepcopy(samples):
            matches = [
                slims_sample
                for slims_sample in slims_samples
                if sample.id == slims_sample.id
                and all(
                    sample.meta.get(k) == slims_sample.meta.get(k) for k in sample.meta
                )
            ]

            if not matches:
                logger.warning(f"Unable to find SLIMS record for {sample.id}")
                continue

            elif len(matches) > 1 and not config.slims.allow_duplicates:
                logger.warning(f"Found multiple SLIMS records for {sample.id}")
                continue

            else:
                logger.debug(f"Found {len(matches)} SLIMS records(s) for {sample.id}")

            sample_kwargs = {
                k: v
                for k, f in fields_dict(sample.__class__).items()
                if k not in ("id", "state", "uuid", "record", "derived")
                and (v := getattr(sample, k))
                != (f.default.factory() if hasattr(f.default, "factory") else f.default)
            }
            for match in matches:
                match_sample = sample.from_record(match.record, config, **sample_kwargs)
                samples.insert(samples.index(sample), match_sample)

            samples.remove(sample)
        return samples

    else:
        logger.debug(f"Found {len(records)} SLIMS samples")
        if "check_criteria" not in config.slims:
            logger.info("No SLIMS check criteria - Skipping check")
            return samples.from_records(records, config)

        logger.info("Checking SLIMS for completed samples")
        check = get_records(
            string_criteria=config.slims.check_criteria,
            connection=slims_connection,
            derived_from=records,
        )

        original_ids = [r.cntn_id.value for r in records]
        records = [
            record
            for record in records
            if record.pk() not in [b.cntn_fk_originalContent.value for b in check]
        ]

        completed = set(original_ids) - set([r.cntn_id.value for r in records])
        logger.info(f"Skipping {len(completed)} previously completed samples")
        for sid in completed:
            logger.debug(f"{sid} already completed - Skipping")

        return samples.from_records(records, config)


@modules.pre_hook(label="SLIMS Derive", after=["slims_fetch"])
def slims_derive(
    samples: SlimsSamples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> SlimsSamples:
    """Add derived content to SLIMS samples"""
    if "derive" not in config.slims:
        return samples
    elif config.slims.dry_run:
        logger.debug("Dry run - Not adding derived records")
        return samples

    logger.info("Creating derived records")
    samples.update_derived(config)
    return samples


@modules.pre_hook(label="SLIMS Mark Running", after="all")
def slims_running(
    samples: SlimsSamples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> SlimsSamples:
    """Add derived content to SLIMS samples"""
    samples.set_state("running")
    if "derive" not in config.slims:
        return samples
    elif config.slims.dry_run:
        logger.debug("Dry run - Not updating SLIMS")
        return samples

    logger.info("Setting SLIMS samples to running")
    samples.update_derived(config)
    return samples


@modules.post_hook(label="SLIMS Update Derived")
def slims_update(
    config: cfg.Config,
    samples: SlimsSamples,
    logger: LoggerAdapter,
    **_,
) -> None:
    """Update SLIMS samples and derived records."""
    if "derive" not in config.slims:
        return samples
    elif config.slims.dry_run:
        logger.info("Dry run - Not updating SLIMS")
        return samples

    if complete := samples.complete:
        logger.info(f"Marking {len(complete)} samples as complete")
        for sample in complete:
            logger.debug(f"Marking {sample.id} as complete")
        complete.set_state("complete")
        complete.update_derived(config)

    if failed := samples.failed:
        logger.warning(f"Marking {len(failed)} samples as failed")
        for sample in failed:
            logger.debug(f"Marking {sample.id} as failed")
        failed.set_state("error")
        failed.update_derived(config)

    return samples
