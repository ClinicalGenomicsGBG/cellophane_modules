"""S3 backup mixin for samples."""

from attrs import Attribute, define, field
from attrs.setters import convert, validate
from cellophane import Sample


@define(slots=False)
class S3Sample(Sample):
    """Sample with S3 backup."""

    s3_remote_keys: set[str] | None = field(
        default=None,
        kw_only=True,
        converter=lambda value: None if value is None else {str(v) for v in value},
        on_setattr=convert,
    )

    s3_bucket: str | None = field(
        default="data",
        kw_only=True,
        on_setattr=validate
    )

    @s3_remote_keys.validator
    def _validate_s3_remote_keys(
        self,
        attribute: Attribute,
        value: set[str] | None,
    ) -> None:
        if value and len(value) != len(self.files):
            raise ValueError(
                f"Length mismatch between {attribute.name} and files: "
                f"{len(value)} != {len(self.files)}"
            )


@Sample.merge.register("s3_remote_keys")
def merge_s3_remote_keys(this, that) -> set[str] | None:
    """Merge S3 remote keys."""
    return None if (this or that) is None else (this or set()) | (that or set())
