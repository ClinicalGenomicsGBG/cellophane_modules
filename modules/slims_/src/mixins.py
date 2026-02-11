"""Module for getting samples from SLIMS"""

from contextlib import suppress
from functools import reduce
from warnings import warn

from attrs import Attribute, define, field
from attrs.setters import validate
from cellophane import Config, Sample, Samples
from cellophane.data import Container
from cellophane.util import map_nested_keys
from slims.slims import Record, Slims

from .connection import PaginatedSlims
from .util import get_field, get_fields_from_sample, get_records


@define(slots=False)
class SlimsSample(Sample):
    """A sample container with SLIMS integration"""

    record: Record | None = field(
        default=None,
        on_setattr=validate,
    )
    page_size: int = field(default=100)
    _derived: dict[str, tuple[Record, dict]] | None = field(
        default=None,
        on_setattr=validate,
    )
    _connection: Slims | PaginatedSlims | None = field(
        default=None,
        init=False,
    )

    def matches_record(
        self,
        record: Record,
        map_: dict,
        match: list[str] | None = None,
    ):
        """Check if the record matches the sample"""

        keys: list[list[str]] = [k.split(".") for k in match or []] + [["id"]]
        c_map = Container(map_)
        matches_ = False
        for key in keys:
            with suppress(KeyError, AttributeError):
                r_value = get_field(record, c_map[key])
                s_value = reduce(getattr, key, self)
                if r_value != s_value:
                    matches_ = False
                    break
                else:
                    matches_ = True

        return matches_

    def map_from_record(
        self,
        record: Record,
        map_: dict,
        map_ignore: list[tuple[str, ...]] | None = None,
    ):
        """Map fields from a SLIMS record to the sample"""
        _map_ignore = map_ignore or []
        _keys = map_nested_keys(map_)
        c_map = Container(map_)
        try:
            for key in _keys:
                if key in _map_ignore:
                    continue
                value = get_field(record, c_map[key])
                if isinstance(self[key[0]], Container):
                    self[key[0]][key[1:]] = value
                else:
                    node = reduce(getattr, key[:-1], self)
                    setattr(node, key[-1], value)
        except (KeyError, AttributeError):
            warn(f"Unable to map '{'.'.join(key)}' to field in sample")
        except Exception as exc:
            warn(
                "Unhandled exception when mapping "
                f"'{'.'.join(key)}' to field in sample: {exc!r}"
            )
        else:
            self.record = record

    @classmethod
    def from_record(cls: Sample, record: Record, config: Config, **kwargs):
        """Create a sample from a SLIMS fastq record"""

        _sample = cls(
            id=record.cntn_id.value,
            page_size=config.slims.page_size,
            **kwargs,
        )
        _sample.map_from_record(
            record,
            map_=config.slims.get("map"),
            map_ignore=[(key,) for key in kwargs],
        )
        return _sample

    def sync_record(self, config: Config):
        """Update the record with the sample fields"""
        if not self.record:
            warn("No record to update")
            return

        if not config.slims.map:
            warn("No values mapped to SLIMS fields")
            return

        keys = [
            part.split(".") for key in map_nested_keys(config.slims.map) for part in key
        ]
        if fields := get_fields_from_sample(
            self, config.slims.map, keys, config.slims.sync
        ):
            self.record.update(fields)

    def sync_derived(self, config: Config):
        """Update derived records in SLIMS with the mapped fields from the sample"""
        if self.record is None or self.connection is None:
            warn("No SLIMS record to derive from")
            return

        if not self._derived:
            self._derived = {
                name: (None, map_) for name, map_ in config.slims.derive.items() if map_
            }
        for name, (record, map_) in self._derived.items():
            fields = {
                field_: value.format(sample=self) if isinstance(value, str) else value
                for field_, value in map_.items()
            }
            if record is None:
                updated_record = self.connection.add(
                    "Content",
                    fields
                    | {
                        "cntn_id": self.record.cntn_id.value,
                        "cntn_fk_originalContent": self.pk,
                        "cntn_fk_user": config.slims.username,
                    },
                )
            else:
                updated_record = record.update(fields)

            self._derived[name] = (updated_record, map_)

    @_derived.validator
    def _validate_derived(
        self,
        attribute: Attribute,
        value: dict[str, tuple[Record | None, dict]] | None,
    ):
        if value is not None and not (
            isinstance(value, dict)
            and all(
                isinstance(v, tuple)
                and isinstance(k, str)
                and len(v) == 2
                and (isinstance(v[0], Record) or v[0] is None)
                and isinstance(v[1], dict)
                for k, v in value.items()
            )
        ):
            raise ValueError(
                "Expected 'dict[str, tuple[Record|None, dict]]' "
                f"for '{attribute.name}', got {value}"
            )

    @record.validator
    def _validate_record(self, attribute: Attribute, value: Record | None):
        if not (value is None or isinstance(value, Record)):
            raise ValueError(
                "Expected 'NoneType' or 'Record' for "
                f"'{attribute.name}', got '{value}'"
            )

    @property
    def pk(self):
        """Get the primary key of the record"""
        return self.record.pk() if self.record is not None else None

    @property
    def connection(self) -> Slims | PaginatedSlims | None:
        """Get a connection to SLIMS from the record"""
        if self._connection is None and self.record:
            self._connection = PaginatedSlims(
                "cellophane",
                url=self.record.slims_api.raw_url,
                username=self.record.slims_api.username,
                password=self.record.slims_api.password,
                page_size=self.page_size,
            )

        return self._connection

    def __getstate__(self) -> dict:
        """Remove open connection before pickle"""
        self._connection = None
        return super().__getstate__()


@Sample.merge.register("record")
def _(this, _):
    return this


@Sample.merge.register("_connection")
def _(*_):
    return None


@Sample.merge.register("_derived")
def _(this, that):
    if not this or that is None:
        return (this or {}) | (that or {})


@Sample.merge.register("page_size")
def _(this, that):
    return min(this, that)


class SlimsSamples(Samples):
    """A list of sample containers with SLIMS integration"""

    @classmethod
    def from_records(cls, records: list[Record], config: Config) -> "SlimsSamples":
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
        config: Config,
        connection: Slims | PaginatedSlims | None = None,
        **kwargs,
    ) -> "SlimsSamples":
        """Get samples from SLIMS records"""
        _connection = connection or PaginatedSlims(
            name=__package__,
            url=config.slims.url,
            username=config.slims.username,
            password=config.slims.password,
            page_size=config.slims.page_size,
        )
        records = get_records(
            criteria=criteria,
            connection=_connection,
            **kwargs,
        )

        return cls.from_records(records, config)

    def sync_derived(self, config: Config) -> None:
        """Update derived records in SLIMS"""
        for sample in self:
            sample.sync_derived(config)

    def sync_records(self, config: Config) -> None:
        """Update the record with the sample fields"""
        for sample in self:
            sample.sync_record(config)
