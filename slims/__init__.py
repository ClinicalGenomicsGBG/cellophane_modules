"""Module for getting samples from SLIMS"""

from copy import deepcopy
from functools import cached_property
from json import loads
from logging import LoggerAdapter
from time import time
from typing import Optional

from humanfriendly import parse_timespan
from slims.criteria import (
    Criterion,
    conjunction,
    contains,
    disjunction,
    equals,
    greater_than_or_equal,
    is_one_of,
)
from slims.slims import Record, Slims

from cellophane import cfg, data, modules


class Content:
    """Content types"""

    DNA = 6
    FASTQ = 22
    BIOINFORMATICS = 23


def get_records(
    connection: Slims,
    *args: Criterion,
    slims_id: Optional[str | list[str]] = None,
    max_age: Optional[int | str] = None,
    analysis: Optional[int | list[int]] = None,
    content_type: Optional[int | list[int]] = None,
    **kwargs: str | int | list[str | int],
) -> list[Record]:
    """Get records from SLIMS"""

    criteria = conjunction()

    match slims_id:
        case str():
            criteria = criteria.add(equals("cntn_id", slims_id))
        case [*ids]:
            criteria = criteria.add(is_one_of("cntn_id", ids))
        case _ if slims_id is not None:
            raise TypeError(f"Invalid type for id: {type(slims_id)}")

    match max_age:
        case int() | str():
            min_ctime = int(time() - parse_timespan(str(max_age))) * 1e3
            criteria = criteria.add(greater_than_or_equal("cntn_createdOn", min_ctime))
        case _ if max_age is not None:
            raise TypeError(f"Expected int or str, got {type(max_age)}")

    match analysis:
        case None:
            pass
        case int():
            criteria = criteria.add(
                disjunction()
                .add(contains("cntn_cstm_secondaryAnalysis", analysis))
                .add(equals("cntn_cstm_secondaryAnalysis", analysis))
            )
        case [*_, int()] as analysis:
            _analysis = disjunction()
            for individual_analysis in analysis:
                _analysis = _analysis.add(
                    disjunction()
                    .add(contains("cntn_cstm_secondaryAnalysis", individual_analysis))
                    .add(equals("cntn_cstm_secondaryAnalysis", individual_analysis))
                )
            criteria = criteria.add(_analysis)
        case _:
            raise TypeError(f"Expected int(s), got {type(analysis)}")

    match content_type:
        case None:
            pass
        case int():
            criteria = criteria.add(equals("cntn_fk_contentType", content_type))
        case [*_, int()]:
            criteria = criteria.add(is_one_of("cntn_fk_contentType", content_type))
        case _:
            raise TypeError(f"Expected int(s), got {type(content_type)}")

    for key, value in kwargs.items():
        criteria = criteria.add(
            is_one_of(key, [value] if isinstance(value, int | str) else value)
        )

    for arg in args:
        criteria = criteria.add(arg)

    return connection.fetch("Content", criteria)


def get_derived_records(
    connection: Slims,
    derived_from: Record | list[Record],
    *args,
    **kwargs,
) -> dict[Record, list[Record]]:
    """Get derived records from SLIMS"""
    match derived_from:
        case record if isinstance(record, Record):
            original = {record.pk(): record}
        case [*records] if all(isinstance(r, Record) for r in records):
            original = {r.pk(): r for r in records}
        case _:
            raise TypeError(f"Expected Record(s), got {derived_from}")

    criterion = is_one_of("cntn_fk_originalContent", [*original])
    records = get_records(connection, criterion, *args, **kwargs)

    derived = {
        o: [r for r in records if r.cntn_cstm_originalContent.value == pk]
        for pk, o in original.items()
    }

    return derived


class SlimsSample(data.Sample):
    """A SLIMS sample container"""

    record: Record
    bioinformatics: Optional[Record]
    pk: int
    run: str
    backup: Optional[data.Container]

    @classmethod
    def from_record(cls, record: Record, **kwargs):
        """Create a sample from a SLIMS fastq record"""
        return cls(
            id=record.cntn_id.value,
            pk=record.pk(),
            run=record.cntn_cstm_runTag.value,
            bioinformatics=None,
            record=record,
            **kwargs,
        )

    @cached_property
    def _connection(self) -> Optional[Slims]:
        return Slims(
            "cellophane",
            url=self.record.slims_api.raw_url,
            username=self.record.slims_api.username,
            password=self.record.slims_api.password,
        ) if self.record is not None else None

    def add_bioinformatics(self, analysis: int):
        """Add a bioinformatics record to the sample"""

        if self.bioinformatics is None and self._connection is not None:
            self.bioinformatics = self._connection.add(
                "Content",
                {
                    "cntn_id": self.id,
                    "cntn_fk_contentType": Content.BIOINFORMATICS,
                    "cntn_status": 10,  # Pending
                    "cntn_fk_location": 83,  # FIXME: Should location be configuarable?
                    "cntn_fk_originalContent": self.pk,
                    "cntn_fk_user": "",  # FIXME: Should user be configuarable?
                    "cntn_cstm_SecondaryAnalysisState": "novel",
                    "cntn_cstm_secondaryAnalysisBioinfo": analysis,
                },
            )

    def set_bioinformatics_state(self, state):
        """Set the bioinformatics state"""

        match state:
            case "running" | "complete" | "error":
                if self.bioinformatics is not None:
                    self.bioinformatics = self.bioinformatics.update(
                        {"cntn_cstm_SecondaryAnalysisState": state}
                    )
            case _:
                raise ValueError(f"Invalid state: {state}")

    def __reduce__(self) -> str | tuple:
        if hasattr(self, "_connection"):
            delattr(self, "_connection")
        return super().__reduce__()


class SlimsSamples(data.Samples[SlimsSample]):
    """A list of sample containers"""

    @classmethod
    def novel(
        cls,
        connection: Slims,
        analysis: int,
        content_type: int,
        rerun_failed: bool,
    ) -> "SlimsSamples":
        """Get novel samples"""

        match content_type:
            case Content.DNA:
                _dna = get_records(
                    connection,
                    analysis=analysis,
                    content_type=Content.DNA,
                )

                _fastqs = [
                    r
                    for v in get_derived_records(
                        connection,
                        derived_from=_dna,
                        content_type=Content.FASTQ,
                    ).values()
                    for r in v
                ]
            case Content.FASTQ:
                _fastqs = get_records(
                    connection,
                    analysis=analysis,
                    content_type=Content.FASTQ,
                )
            case _:
                raise ValueError(f"Invalid content type: {content_type}")

        _bioinformatics = get_derived_records(
            connection,
            derived_from=_fastqs,
            content_type=Content.BIOINFORMATICS,
            cntn_cstm_secondaryAnalysisBioinfo=analysis,
        )

        for original, derived in _bioinformatics.items():
            failed = all(
                d.cntn_cntn_cstm_SecondaryAnalysisState.value == "error"
                for d in derived
            )
            if derived and (not failed or rerun_failed):
                _fastqs.remove(original)

        return cls.from_fastqs(fastqs=_fastqs)

    @classmethod
    def from_slims(cls, connection: Slims, *args, **kwargs) -> "SlimsSamples":
        """Get samples from SLIMS"""
        _fastqs = get_records(connection, *args, **kwargs)
        return cls.from_fastqs(_fastqs)

    @classmethod
    def from_ids(
        cls,
        connection: Slims,
        ids: list[str],
        analysis: int,
    ) -> "SlimsSamples":
        """Get samples from SLIMS by ID"""
        _fastqs = get_records(
            connection,
            content_type=Content.FASTQ,
            slims_id=ids,
            analysis=analysis,
        )
        return cls.from_fastqs(_fastqs)

    @classmethod
    def from_fastqs(
        cls,
        fastqs: list[Record],
    ) -> "SlimsSamples":
        """Get samples from SLIMS records"""
        _fastqs = {f.pk(): f for f in fastqs}
        _demuxer = {
            f.pk(): {**loads(f.cntn_cstm_demuxerSampleResult.value)} for f in fastqs
        }
        _backup = {
            f.pk(): {**loads(f.cntn_cstm_demuxerBackupSampleResult.value)}
            for f in fastqs
        }

        return cls(
            [
                SlimsSample.from_record(
                    record=_fastqs[pk],
                    backup=_backup[pk],
                    **_demuxer[pk],
                )
                for pk in _fastqs
            ]
        )

    def add_bioinformatics(self, analysis: int) -> None:
        """Add bioinformatics content to SLIMS samples"""
        for sample in self:
            sample.add_bioinformatics(analysis)

    def set_bioinformatics_state(self, state: str) -> None:
        """Update bioinformatics state in SLIMS"""
        match state:
            case "running" | "complete" | "error":
                for sample in self:
                    sample.set_bioinformatics_state(state)
            case _:
                raise ValueError(f"Invalid state: {state}")


@modules.pre_hook(label="SLIMS Fetch", priority=0)
def slims_samples(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> Optional[SlimsSamples]:
    """Load novel samples from SLIMS."""

    if config.slims is not None:
        slims_connection = Slims(
            name=__package__,
            url=config.slims.url,
            username=config.slims.username,
            password=config.slims.password,
        )

        if samples:
            logger.debug("Augmenting existing samples with SLIMS data")
            _slims_samples = SlimsSamples.from_ids(
                connection=slims_connection,
                ids=[s.id for s in samples],
                analysis=config.slims.analysis_pk,
            )

            _return_samples = SlimsSamples()
            for sample in samples:
                _ss = [s for s in _slims_samples if s.id == sample.id]
                if len(_ss) > 1 and "pk" in sample:
                    _ss = [s for s in _ss if s.pk == sample.pk]
                elif len(_ss) > 1 and "run" in sample:
                    _ss = [s for s in _ss if s.run == sample.run]

                if len(_ss) > 1:
                    logger.warning(f"Multiple SLIMS samples found for {sample.id}")
                    _return_samples.append(SlimsSample(id=sample.pop("id"), **sample))
                else:
                    # FIXME: Why do the samples need to be unpacked?
                    _data = {**_ss[0]} | {**sample}
                    _return_samples.append(
                        SlimsSample(
                            id=_data.pop("id"),
                            pk=_data.pop("pk"),
                            **deepcopy(_data),
                        )
                    )

        elif config.slims.sample_id:
            logger.info("Looking for samples by ID")
            logger.debug(f"ID(s): {config.slims.sample_id}")
            _return_samples = SlimsSamples.from_ids(
                connection=slims_connection,
                ids=config.slims.sample_id,
                analysis=config.slims.analysis_pk,
            )
            for sid in config.slims.sample_id:
                if sid not in [sample.id for sample in samples]:
                    logger.warning(f"FASTQ object for {sid} not found")
                elif sum(s.id == sid for s in samples) > 1:
                    logger.warning(f"Multiple FASTQ objects found for {sid}")

        elif "analysis_pk" in config:
            logger.info(
                f"Finding novel samples for analysis {config.slims.analysis_pk}"
            )
            _return_samples = SlimsSamples.novel(
                connection=slims_connection,
                content_type=config.content_pk,
                analysis=config.slims.analysis_pk,
                rerun_failed=config.slims.rerun_failed,
            )

        else:
            logger.error("No analysis configured")
            return None

        return _return_samples

    else:
        logger.warning("No SLIMS connection configured")
        return None


@modules.pre_hook(label="SLIMS Add")
def slims_bioinformatics(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> None:
    """Load novel samples from SLIMS."""
    if config.slims.dry_run:
        logger.debug("Dry run - Not adding bioinformatics")
    elif isinstance(samples, SlimsSamples):
        logger.info("Adding bioinformatics content")
        samples.add_bioinformatics(config.slims.analysis_pk)
        samples.set_bioinformatics_state("running")
    else:
        logger.debug("Samples not from SLIMS")


@modules.post_hook(label="SLIMS Update")
def slims_update(
    config: cfg.Config,
    samples: SlimsSamples,
    logger: LoggerAdapter,
    **_,
) -> None:
    """Update SLIMS samples with bioinformatics content."""

    if config.slims.dry_run:
        logger.info("Dry run - Not updating SLIMS")
    elif isinstance(samples, SlimsSamples):
        logger.info("Updating bioinformatics")
        pks = {s.pk for s in samples if s.pk is not None}
        collect = {pk: [*filter(lambda s: s.pk == pk, samples)] for pk in pks}

        for pk_samples in collect.values():
            if all(s.complete for s in pk_samples):
                pk_samples[0].set_bioinformatics_state("complete")
            else:
                pk_samples[0].set_bioinformatics_state("error")
    else:
        logger.info("No SLIMS samples to update")
