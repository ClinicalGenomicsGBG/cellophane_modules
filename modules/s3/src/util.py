"""Module for fetching files from S3."""

import json
import sys
from logging import LoggerAdapter
from pathlib import Path
from typing import Callable

import boto3
import botocore
from cellophane import Cleaner, Sample
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning


def _get_s3_session(
    credentials_path: Path,
    connect_timeout: int = 10,
    read_timeout: int = 10,
    retries: int = 3,
) -> boto3.Session:
    """Create a boto3 session for S3."""
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    return boto3.client(
        "s3",
        endpoint_url=credentials["endpoint"],
        aws_access_key_id=credentials["aws_access_key_id"],
        aws_secret_access_key=credentials["aws_secret_access_key"],
        verify=False,
        config=botocore.client.Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": retries, "mode": "standard"},
        ),
    )

def fetch(
    *,
    credentials: Path,
    local_path: Path,
    remote_key: str,
    bucket: str,
) -> Path:
    """Fetches a file from S3."""
    sys.stdout = open("/dev/null", "w", encoding="utf-8")
    sys.stderr = open("/dev/null", "w", encoding="utf-8")
    disable_warnings(InsecureRequestWarning)

    _session = _get_s3_session(credentials_path=credentials)
    _bucket = _session.Bucket(bucket)
    _bucket.download_file(remote_key, str(local_path))

    return local_path


def callback(
    sample: Sample,
    f_idx: int,
    logger: LoggerAdapter,
    cleaner: Cleaner,
    bucket: str,
) -> Callable[[Path], None]:
    """Callback for fetching files from S3."""

    def inner(local_path: Path) -> None:
        logger.debug(f"Fetched {local_path.name} from s3 bucket '{bucket}'")
        sample.files.insert(f_idx, local_path)
        cleaner.register(local_path.resolve())

    return inner


def error_callback(
    sample: Sample,
    logger: LoggerAdapter,
    bucket: str,
):
    """Error callback for fetching files from S3."""

    def inner(exception: Exception):
        logger.error(f"Failed to fetch backup for {sample.id} ({exception})")
        sample.fail(f"Failed to fetch backup from s3 bucket '{bucket}'")

    return inner
