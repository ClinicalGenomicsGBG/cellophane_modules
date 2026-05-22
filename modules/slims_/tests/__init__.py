from datetime import datetime
from functools import partial
from json import dumps
from logging import getLogger
from typing import Any
from unittest.mock import Mock

from cellophane import data
from slims.criteria import Criterion
from slims.internal import Record

logger = getLogger()


class RecordMock(Mock):
    def __init__(self, **kwargs):
        defaults = {
            "cntn_pk": {"value": 1},
            "cntn_id": {"value": "DUMMY"},
            "cntn_createdOn": {"value": datetime.now().isoformat()},
            "slims_api": {"username": "DUMMY", "password": "DUMMY", "raw_url": "DUMMY"},
        }
        for k, v in data.Container(defaults | kwargs).items():
            object.__setattr__(self, k, v)
        object.__setattr__(self, "json_entity", defaults | kwargs)
        super().__init__(spec_set=Record)

    def pk(self):
        return self.cntn_pk.value

    def update(self, values):
        logger.debug(f"record.update: {values=}")

    def __reduce__(self):
        return partial(RecordMock, **self.json_entity), (), {}


def add_factory():
    def add(instance, type_, fields):
        del instance  # Unused
        logger.debug("Mocking add to table '%s'", type_)
        for k, v in fields.items():
            logger.debug("FIELD %s: %s", k, v)
        return RecordMock(**fields)

    return add


def fetch_factory(
    db: list[RecordMock] | None = None,
    fields: list[str] | None = None,
):
    db_ = db or []
    fields_ = fields or [f for r in db_ for f in dir(r) if f.startswith("cntn_")]

    def fetch(
        conn: Any,
        table: str,
        criteria: Criterion,
        sort: list[str] | None = None,
        start: int | None = None,
        end: int | None = None,
    ):
        del conn, sort  # Unused

        logger.debug("Mocking fetch from from table '%s'", table)
        if table == "Field" and not fields:
            return [criteria.to_dict()["value"]][start:end]
        elif table == "Field":
            return [f for f in fields_ if f == criteria.to_dict()["value"]][start:end]
        logger.debug("Criteria: %s", criteria.to_dict())
        match = [r for r in db_ if _match_criteria(criteria, r)][start:end]
        logger.debug("Matched %s records", len(match))
        return match

    return fetch


def _match_criteria(criteria: Criterion, record: RecordMock) -> Any:
    match criteria.to_dict():
        case {"fieldName": field} if not hasattr(record, field):
            return False
        case {
            "operator": "equals",
            "fieldName": field,
            "value": value,
        }:
            # JSON serialization is used to compare values that may be both JSON and python form
            r_value = dumps(getattr(record, field).value).strip('"')
            c_value = dumps(value).strip('"')
            return r_value == c_value

        case {
            "operator": "iEquals",
            "fieldName": field,
            "value": value,
        }:
            # JSON serialization is used to compare values that may be both JSON and python form
            r_value = dumps(getattr(record, field).value).strip('"')
            c_value = dumps(value).strip('"')
            return r_value.lower() == c_value.lower()
        case {
            "operator": "startsWith",
            "fieldName": field,
            "value": value,
        }:
            return str(getattr(record, field).value).startswith(str(value))
        case {
            "operator": "endsWith",
            "fieldName": field,
            "value": value,
        }:
            return str(getattr(record, field).value).endswith(str(value))
        case {
            "operator": "iContains",
            "fieldName": field,
            "value": value,
        }:
            return str(value).lower() in str(getattr(record, field).value).lower()
        case {
            "operator": "inSet",
            "fieldName": field,
            "value": value,
        }:
            return str(getattr(record, field).value) in [str(v) for v in value]
        case {
            "operator": "betweeenInclusive",
            "fieldName": field,
            "start": start,
            "end": end,
        }:
            try:
                f_value = datetime.fromisoformat(
                    getattr(record, field).value
                ).timestamp()
                start_ = datetime.fromisoformat(start).timestamp()
                end_ = datetime.fromisoformat(end).timestamp()
            except ValueError:
                f_value = float(getattr(record, field).value)
                start_ = float(start)
                end_ = float(end)

            return start_ <= f_value <= end_

        case {
            "operator": "greaterThan",
            "fieldName": field,
            "value": value,
        }:
            try:
                f_value = datetime.fromisoformat(
                    getattr(record, field).value
                ).timestamp()
                value_ = datetime.fromisoformat(value).timestamp()
            except ValueError:
                f_value = float(getattr(record, field).value)
                value = float(value)

            return f_value > value_
        case {
            "operator": "lessThan",
            "fieldName": field,
            "value": value,
        }:
            try:
                f_value = datetime.fromisoformat(
                    getattr(record, field).value
                ).timestamp()
                value_ = datetime.fromisoformat(value).timestamp()
            except ValueError:
                f_value = float(getattr(record, field).value)
                value_ = value
            return f_value < value

        case {"operator": "and"}:
            return all(_match_criteria(c, record) for c in criteria.members)
        case {"operator": "or"}:
            return any(_match_criteria(c, record) for c in criteria.members)
        case {"operator": "not"}:
            return not _match_criteria(criteria.members[0], record)
        case {"operator": "isNull", "fieldName": "cntn_pk"}:
            # This is treated by SLIMS as a boolean false since PK is always set
            return False
        case {"operator": "isNull", "fieldName": field}:
            return getattr(record, field).value is None
        case _:
            return True
