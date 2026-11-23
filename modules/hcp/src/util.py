"""Module for fetching files from HCP."""

import sys
from logging import LoggerAdapter
from pathlib import Path
from typing import Callable

from cellophane import Cleaner, Sample
from NGPIris.hcp import HCPManager


def fetch(
    *,
    credentials: Path,
    local_path: Path,
    remote_key: str,
    bucket: str,
) -> Path:
    """Fetches a file from HCP."""
    sys.stdout = open("/dev/null", "w", encoding="utf-8")
    sys.stderr = open("/dev/null", "w", encoding="utf-8")

    hcpm = HCPManager(
        credentials_path=credentials,
        bucket=bucket,
    )

    hcpm.download_file(
        remote_key,
        local_path=str(local_path),
        callback=False,
        force=True,
    )
    return local_path


def callback(
    sample: Sample,
    f_idx: int,
    logger: LoggerAdapter,
    cleaner: Cleaner,
) -> Callable[[Path], None]:
    """Callback for fetching files from HCP."""

    def inner(local_path: Path) -> None:
        logger.debug(f"Fetched {local_path.name} from hcp")
        sample.files[f_idx] = local_path
        cleaner.register(local_path.resolve())

    return inner


def error_callback(
    sample: Sample,
    logger: LoggerAdapter,
):
    """Error callback for fetching files from HCP."""

    def inner(exception: Exception):
        logger.error(f"Failed to fetch backup for {sample.id} ({exception})")
        sample.fail("Failed to fetch backup from HCP")

    return inner
