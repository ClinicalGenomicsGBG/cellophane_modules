"""Module for getting samples from SLIMS"""

from json import loads
from time import time
from typing import Optional
from logging import LoggerAdapter

from humanfriendly import parse_timespan
from slims.criteria import (
    Criterion,
    conjunction,
    disjunction,
    contains,
    equals,
    greater_than_or_equal,
    is_one_of,
)
from slims.slims import Record, Slims

from cellophane import data, cfg, modules


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
        for o, pk in original.values()
    }

    return derived


class SlimsSample(data.Sample):
    """A SLIMS sample container"""

    bioinformatics: Optional[Record]
    secondary_analysis: Optional[int]


class SlimsSamples(data.Samples[SlimsSample]):
    """A list of sample containers"""

    def __init__(self, connection: Slims, initlist: Optional[list[SlimsSample]] = None):
        super().__init__(initlist)
        for idx, sample in enumerate(self):
            if sample.bioinformatics is None and sample.secondary_analysis is not None:
                self[idx].bioinformatics = connection.add(
                    "Content",
                    {
                        "cntn_id": sample.cntn_id.value,  # type: ignore
                        "cntn_fk_contentType": Content.BIOINFORMATICS,
                        "cntn_status": 10,  # Pending
                        "cntn_fk_location": 83,  # FIXME: Should location be configuarable?
                        "cntn_fk_originalContent": sample.pk,
                        "cntn_fk_user": "",  # FIXME: Should user be configuarable?
                        "cntn_cstm_SecondaryAnalysisState": "novel",
                        "cntn_cstm_secondaryAnalysisBioinfo": sample.secondary_analysis,
                    }
                )
        

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

        for original, derived in _bioinformatics:
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
    def from_ids(cls, connection: Slims, ids: list[str]) -> "SlimsSamples":
        """Get samples from SLIMS by ID"""
        _fastqs = get_records(connection, content_type=Content.FASTQ, slims_id=ids)
        return cls.from_fastqs(_fastqs)

    @classmethod
    def from_fastqs(
        cls,
        fastqs: list[Record],
        secondary_analysis: Optional[int] = None,
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
                SlimsSample(
                    pk=pk,
                    id=_fastqs[pk].cntn_id.value,
                    fastq=_fastqs[pk],
                    bioinformatics=None,
                    secondary_analysis=secondary_analysis,
                    backup=_backup[pk],
                    **_demuxer[pk],
                )
                for pk in _fastqs
            ]
        )

    def update_bioinformatics(self, state: str) -> None:
        """Update bioinformatics state in SLIMS"""
        match state:
            case "running" | "complete" | "error":
                for sample in self:
                    if sample.bioinformatics is not None:
                        sample.bioinformatics = sample.bioinformatics.update(
                            {"cntn_cstm_SecondaryAnalysisState": state}
                        )
            case _:
                raise ValueError(f"Invalid state: {state}")


@modules.pre_hook(label="SLIMS", priority=0)
def slims_samples(
    config: cfg.Config,
    samples: data.Samples,
    logger: LoggerAdapter,
    **_,
) -> Optional[SlimsSamples]:
    """Load novel samples from SLIMS."""

    if samples:
        logger.info("Samples already loaded")
        return None

    elif config.slims is not None:
        slims_connection = Slims(
            name=__package__,
            url=config.slims.url,
            username=config.slims.username,
            password=config.slims.password,
        )
        if config.slims.sample_id:
            logger.info("Looking for samples by ID")
            samples = SlimsSamples.from_ids(slims_connection, config.slims.sample_id)
            for sid in config.slims.sample_id:
                if sid not in [sample.id for sample in samples]:
                    logger.warning(f"Sample {sid} not found")
        else:
            logger.info(f"Finding novel samples for analysis {config.analysis_pk}")
            samples = SlimsSamples.novel(
                connection=slims_connection,
                content_type=config.content_pk,
                analysis=config.analysis_pk,
                rerun_failed=config.slims.rerun_failed,
            )

        return samples

    else:
        logger.warning("No SLIMS connection configured")
        return None
