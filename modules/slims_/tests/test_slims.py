from pathlib import Path

from cellophane.testing import parametrize_from_yaml
from pytest import mark, param, raises
from pytest_mock import MockerFixture
from ruamel.yaml import YAML
from slims.slims import Slims

import slims_

_ROOT = Path(__file__).parent


class Test_integration:
    @staticmethod
    @parametrize_from_yaml([_ROOT / "integration.yaml"])
    def test_integration(definition: Path, run_definition):
        run_definition(definition)


class Test_criteria:
    @staticmethod
    @mark.parametrize(
        "criteria,parsed,unnested,resolved,exception,records,fields,kwargs",
        [
            param(
                d["criteria"],
                d.get("parsed"),
                d.get("unnested"),
                d.get("resolved"),
                d.get("exception"),
                d.get("records"),
                d.get("fields", None),
                d.get("kwargs", {}),
                id=d["id"],
            )
            for d in YAML(typ="unsafe").load_all((_ROOT / "criteria.yaml").read_text())
        ],
    )
    def test_criteria(
        mocker: MockerFixture,
        criteria,
        parsed,
        unnested,
        resolved,
        exception,
        records,
        fields,
        kwargs,
    ):
        mocker.patch(
            "slims.slims.Slims.fetch",
            new=slims_.tests.fetch_factory(records or [], fields=fields),
        )
        conn = Slims("DUMMY", url="DUMMY", username="DUMMY", password="DUMMY")
        if exception:
            with raises(exception):
                parsed_ = slims_.parse_criteria(criteria, **kwargs)
                unnested_ = slims_.unnest_criteria(parsed_, **kwargs)
                slims_.validate_criteria(unnested_, connection=conn)
                resolved_ = slims_.resolve_criteria(
                    unnested_, connection=conn, **kwargs
                )
        else:
            parsed_ = slims_.parse_criteria(criteria, **kwargs)
            unnested_ = slims_.unnest_criteria(parsed_)
            slims_.validate_criteria(unnested_, connection=conn)
            resolved_ = slims_.resolve_criteria(unnested_, connection=conn)

            if parsed is not None:
                assert parsed_.to_dict() == parsed
            if unnested is not None:
                assert unnested_.to_dict() == unnested
            if resolved is not None:
                assert resolved_.to_dict() == resolved
