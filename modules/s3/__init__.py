"""S3 module for cellphane."""

from .src.hooks import s3_fetch
from .src.mixins import S3Sample
from .src.util import fetch

__all__ = ["S3Sample", "fetch", "s3_fetch"]
