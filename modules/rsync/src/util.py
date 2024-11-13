"""Utility functions for rsync module."""

from copy import copy
from logging import LoggerAdapter
from pathlib import Path
from time import sleep


def sync_callback(
    result: None,
    /,
    logger: LoggerAdapter,
    manifest: list[tuple[str, str]],
    timeout: int,
):
    """Callback function for rsync_results. Waits for files to become available."""
    del result  # Unused
    for src, dst in manifest:
        if not Path(dst).exists():
            logger.debug(f"Waiting {timeout} seconds for {dst} to become available")
        _timeout = copy(timeout)
        while not (available := Path(dst).exists()) and (_timeout := _timeout - 1) > 0:
            sleep(1)
        if available:
            logger.debug(f"Copied {src} -> {dst}")
        else:
            logger.warning(f"{dst} is missing")

def add_timestamp(
        resultdir: Path,
        dst: Path,
        timestamp: str,
) -> Path:
    """Add datetag to outputfolder."""
    if dst.is_relative_to(resultdir):
        # Unique outputfolder for each sample located after resultdir
        dst_parts = dst.relative_to(resultdir).parts
        dst_name_with_tag = f"{dst_parts[0]}_{timestamp}"
        dst = resultdir / dst_name_with_tag / Path(*dst_parts[1:])
    return dst
