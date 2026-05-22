"""Module for getting samples from SLIMS"""

import re
from contextlib import suppress
from functools import cache, reduce, singledispatch
from json import loads
from typing import Any
from warnings import warn

from attrs import define
from cellophane import Sample
from slims.criteria import (
    Criterion,
    Junction,
    between_inclusive,
    conjunction,
    contains,
    disjunction,
    ends_with,
    equals,
    equals_ignore_case,
    greater_than,
    is_not,
    is_one_of,
    less_than,
    starts_with,
)
from slims.criteria import _JunctionType as op
from slims.slims import Record, Slims

from .connection import PaginatedSlims


@cache
def split_criteria(criteria: str) -> list[str]:
    """
    Tokenize string criteria, maintaining parentheses

    >>> split_criteria("a is x and (b is y or c is d) or g is h")
    ['a', 'is', 'x', 'and', 'b is y or c is d', 'or', 'g', 'is', 'h']
    """
    depth = 0
    part = ""
    parts = []
    # Ensure that criteria is separated by spaces
    _criteria = " ".join(criteria.split())

    while _criteria:
        if (delta := _criteria[0] == "(") and (depth := depth + delta) == 1:
            part = ""
        elif (delta := _criteria[0] == ")") and (depth := depth - delta) == 0:
            parts.append(part)
            part = ""
        elif depth > 0:
            part += _criteria[0]
        elif _criteria[0] == " " and part:
            parts.append(part.strip())
            part = ""
        else:
            part += _criteria[0]

        _criteria = _criteria[1:]

    if depth != 0:
        raise ValueError(f"Unmatched parentheses: {criteria}")

    if part:
        parts.append(part.strip())
    return parts

def parse_criteria(criteria: str | list[str]) -> Criterion:
    """Parse criteria"""

    match criteria:
        case str(criteria) if all(
            w not in criteria
            for w in [
                "equals",
                "not_equals",
                "one_of",
                "not_one_of",
                "equals_ignore_case",
                "not_equals_ignore_case",
                "contains",
                "not_contains",
                "starts_with",
                "not_starts_with",
                "ends_with",
                "not_ends_with",
                "between",
                "not_between",
                "greater_than",
                "less_than",
            ]
        ):
            raise ValueError(f"Invalid criteria: {criteria}")
        case str(criterion):
            c = split_criteria(criterion)
            return parse_criteria(c)

        case [criterion]:
            c = split_criteria(criterion)
            return parse_criteria(c)

        case [*criterion] if "and" in criterion:
            idx = criterion.index("and")
            a, b = criterion[:idx], criterion[idx+1:]
            return conjunction().add(parse_criteria(a)).add(parse_criteria(b))
        case [*criterion] if "or" in criterion:
            idx = criterion.index("or")
            a, b = criterion[:idx], criterion[idx+1:]
            return disjunction().add(parse_criteria(a)).add(parse_criteria(b))

        case ["has_parent", *a]:
            return HasParent(parse_criteria(a))
        case ["not_has_parent", *a]:
            return HasParent(parse_criteria(a), negate=True)
        case ["has_derived", *a]:
            return HasDerived(parse_criteria(a))
        case ["not_has_derived", *a]:
            return HasDerived(parse_criteria(a), negate=True)

        case [field, *_] if not field.startswith("cntn_"):
            raise ValueError(f"Invalid field: {field}")

        case [field, "equals", value]:
            return equals(field, value)
        case [field, "not_equals", value]:
            return is_not(equals(field, value))
        case [field, "one_of", *values]:
            return is_one_of(field, values)
        case [field, "not_one_of", *values]:
            return is_not(is_one_of(field, values))

        case [field, "equals_ignore_case", value]:
            return equals_ignore_case(field, value)
        case [field, "not_equals_ignore_case", value]:
            return is_not(equals_ignore_case(field, value))

        case [field, "contains", value]:
            return contains(field, value)
        case [field, "not_contains", value]:
            return is_not(contains(field, value))

        case [field, "starts_with", value]:
            return starts_with(field, value)
        case [field, "not_starts_with", value]:
            return is_not(starts_with(field, value))

        case [field, "ends_with", value]:
            return ends_with(field, value)
        case [field, "not_ends_with", value]:
            return is_not(ends_with(field, value))

        case [field, "between", *values]:
            return between_inclusive(field, *values)
        case [field, "not_between", *values]:
            return is_not(between_inclusive(field, *values))

        case [field, "greater_than", value]:
            return greater_than(field, value)
        case [field, "less_than", value]:
            return less_than(field, value)
        case _:
            raise ValueError(f"Invalid criteria: {criteria}")


def get_field(record: Record, field: str, default=None) -> Any:
    """Get a field from SLIMS record"""
    try:
        if not field.startswith("json:"):
            return getattr(record, field).value
        _field, *_key = re.split(r"\.|(\[[0-9]*\])", field[5:])
        _key = [int(k.strip("[]")) if k.startswith("[") else k for k in _key if k]
        _json = loads(record.__dict__[_field].value)
        return reduce(lambda x, y: x[y], _key, _json)
    except (AttributeError, KeyError):
        warn(f"Unable to get field '{field}' from record")
        return default


def get_fields_from_sample(
    sample: Sample,
    map_: dict[str, Any],
    keys: list[tuple[str, ...]],
    sync_keys_or_fields: list[str],
):
    fields = {}
    for key in keys:
        try:
            field_ = reduce(lambda x, y: x.get(y) or {}, key, map_)
            if (
                field_ not in sync_keys_or_fields
                and ".".join(key) not in sync_keys_or_fields
            ):
                continue
            value = reduce(lambda x, y: x.get(y), key[1:], getattr(sample, key[0]))
        except Exception as exc:
            warn(f"Unable to map '{'.'.join(key)}' to field: {exc!r}")
            continue

        fields[field_] = value
    return fields


@define
class HasParent:
    value: Criterion
    negate: bool = False

    def to_dict(self):
        base = {
            "operator": "has_parent",
            "value": self.value.to_dict(),
        }
        return {"operator": "not", "criteria": [base]} if self.negate else base


@define
class HasDerived:
    value: Criterion
    negate: bool = False

    def to_dict(self):
        base = {
            "operator": "has_derived",
            "value": self.value.to_dict(),
        }
        return {"operator": "not", "criteria": [base]} if self.negate else base


def barnch_has_parent_derived_criteria(branch: Criterion) -> bool:
    """
    Checks if the specified junction has any HasParent or HasDerived members,
    including nested junctions.

    Args:
        branch: The junction to check.

    Returns:
        bool: True if the junction has any HasParent or HasDerived members,
            False otherwise.
    """
    ret = False
    for member in branch.members if isinstance(branch, Junction) else [branch]:
        if isinstance(member, Junction):
            ret = barnch_has_parent_derived_criteria(member)
        elif isinstance(member, (HasParent, HasDerived)):
            ret = True

    return ret


class NoMatch(Exception):
    """Raised when no match is found for a has_parent or has_derived criterion."""


class NoOp(Exception):
    """Raised when a no-op is encountered (eg. no records match a negated HasParent/HasDerived)."""


@singledispatch
def resolve_criteria(
    criteria: Any,
    connection: Slims | PaginatedSlims,
    _base: Criterion | None = None,
) -> Criterion:  # pragma: no cover
    """
    Resolve criteria to a new criterion that can be used to filter records.
    Recursively replaces HasParent and HasDerived criteria with criteria that
    filter by the primary keys of the parent or derived records.

    Args:
        criteria: The criteria to resolve.
        connection: The SLIMS connection.
        _base: The base criteria to filter by.

    Returns:
        Criterion: The resolved criterion.
    """
    del connection, _base  # Unused
    raise NotImplementedError(f"Cannot resolve {criteria}")


@resolve_criteria.register
def _(
    criteria: HasParent,
    connection: PaginatedSlims | Slims,
    _base: Criterion | None = None,
) -> Criterion:
    # Parent records must match the specified criteria
    criteria_ = conjunction()
    if _base:
        # If a base criteria is provided, filter the potential parent records by it
        derived = connection.fetch("Content", _base)
        criteria_.add(
            is_one_of("cntn_pk", [r.cntn_fk_originalContent.value for r in derived])
        )

    if parents := connection.fetch("Content", criteria=criteria_.add(criteria.value)):
        resolved = is_one_of("cntn_fk_originalContent", [r.pk() for r in parents])
    elif criteria.negate:
        raise NoOp()
    else:
        raise NoMatch()

    # Return a new criterion that filters by the originalContent of the parent records
    return is_not(resolved) if criteria.negate else resolved


@resolve_criteria.register
def _(
    criteria: HasDerived,
    connection: Slims | PaginatedSlims,
    _base: Criterion | None = None,
) -> Criterion:
    # Derived records must match the specified criteria
    if _base:
        # If a base criteria is provided, filter the potential derived records by it
        parents = connection.fetch("Content", _base)
        derived = None
        if parent_pks := [r.pk() for r in parents]:
            derived = connection.fetch(
                "Content",
                criteria=conjunction()
                .add(criteria.value)
                .add(is_one_of("cntn_fk_originalContent", parent_pks)),
            )

    # Fetch the matching derived records
    if derived:
        resolved = is_one_of(
            "cntn_pk", [r.cntn_fk_originalContent.value for r in derived]
        )
        return is_not(resolved) if criteria.negate else resolved
    elif criteria.negate:
        raise NoOp()
    else:
        raise NoMatch()


@resolve_criteria.register
def _(
    criteria: Criterion,
    connection: Slims | PaginatedSlims,
    _base: Criterion | None = None,
) -> Criterion:
    del connection, _base  # Unused

    # Return base criteria as is
    return criteria


@resolve_criteria.register
def _(
    criteria: Junction,
    connection: Slims | PaginatedSlims,
    _base: Junction | None = None,
) -> Criterion:
    resolved = Junction(criteria.operator)
    if criteria.operator == op.AND:
        base = _base or conjunction()
        for member in criteria.members:
            if not barnch_has_parent_derived_criteria(member):
                base.add(member)

        for member in criteria.members:
            # If a member is a no-op, it can be ignored.
            with suppress(NoOp):
                resolved.add(resolve_criteria(member, connection, base))
        if not resolved.members:
            # If all members are no-op, the entire junction can be ignored.
            raise NoOp()
        return resolved

    elif criteria.operator == op.OR:
        for member in criteria.members:
            # In an OR junction, each member is resolved independently, so no-match
            # should be ignored to allow other members to be resolved.
            with suppress(NoMatch):
                resolved.add(resolve_criteria(member, connection, _base))

        if not resolved.members:
            # If all members are no-match, the junction should match no records.
            raise NoMatch()

    elif criteria.operator == op.NOT:
        resolved.add(resolve_criteria(criteria.members[0], connection, _base))

    return resolved


def unnest_criteria(criteria: Criterion) -> Criterion:
    """Unnest nested junctions with the same operator."""
    if not isinstance(criteria, Junction):
        return criteria
    operator = criteria.operator
    resolved = Junction(operator)
    for member in criteria.members:
        if isinstance(member, Junction):
            resolved_member = unnest_criteria(member)
            if resolved_member.operator == operator:
                resolved.members.extend(resolved_member.members)
            else:
                resolved.add(resolved_member)
        else:
            resolved.add(member)
    return resolved


@singledispatch
def validate_criteria(criteria: Criterion, connection: Slims | PaginatedSlims) -> None:
    """Validate criteria fields to ensure they are valid SLIMS fields."""
    field = criteria.to_dict()["fieldName"]
    if not connection.fetch("Field", equals("tbfl_name", field)):
        raise ValueError(f"Invalid field: {field}")


@validate_criteria.register
def _(criteria: Junction, connection: Slims | PaginatedSlims) -> None:
    for member in criteria.members:
        validate_criteria(member, connection)


@validate_criteria.register
def _(criteria: HasParent, connection: Slims | PaginatedSlims) -> None:
    validate_criteria(criteria.value, connection)


@validate_criteria.register
def _(criteria: HasDerived, connection: Slims | PaginatedSlims) -> None:
    validate_criteria(criteria.value, connection)


def get_records(
    criteria: str | Criterion,
    connection: Slims | PaginatedSlims,
    **kwargs: Any,
) -> list[Record]:
    parsed = parse_criteria(criteria) if isinstance(criteria, str) else [criteria]
    unnested = unnest_criteria(parsed)
    validate_criteria(unnested, connection)
    try:
        resolved = resolve_criteria(unnested, connection)
    except NoMatch:
        warn(f"No record matches criteria '{criteria}'")
        return []
    except NoOp:
        warn(f"Ignoring fetch as ALL SLIMS records would match criteria '{criteria}'")
        return []
    return connection.fetch("Content", resolved)
