"""Module for fetching files from S3."""

import json
import sys
from logging import LoggerAdapter
from pathlib import Path
from typing import Callable
from collections.abc import Generator, Iterable

import boto3
from botocore.client import Config as BotocoreClientConfig
from cellophane import Cleaner, Sample, Output
from mypy_boto3_s3.service_resource import S3ServiceResource
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning


def _get_s3_session(
    credentials: dict,
    connect_timeout: int = 10,
    read_timeout: int = 10,
    retries: int = 3,
) -> S3ServiceResource:
    """Create a boto3 session for S3."""
    return boto3.resource(
        "s3",
        endpoint_url=credentials["endpoint"],
        aws_access_key_id=credentials["aws_access_key_id"],
        aws_secret_access_key=credentials["aws_secret_access_key"],
        verify=False,
        config=BotocoreClientConfig(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": retries, "mode": "standard"},
        ),
    )


def get_endpoint_credentials(
    credential_paths: list[Path],
    endpoint: str,
) -> dict | None:
    for path in credential_paths:
        credentials = json.loads(path.read_text(encoding="utf-8"))
        if credentials.get("endpoint") == endpoint:
            return credentials
    return None


def fetch(
    *,
    credentials: dict,
    local_path: Path,
    remote_key: str,
    bucket: str,
) -> Path:
    """Fetches a file from S3."""
    sys.stdout = open("/dev/null", "w", encoding="utf-8")
    sys.stderr = open("/dev/null", "w", encoding="utf-8")
    disable_warnings(InsecureRequestWarning)

    _session = _get_s3_session(credentials=credentials)
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
        sample.files[f_idx] = local_path
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


def upload(
    *,
    credentials: dict,
    local_path: Path,
    remote_key: str,
    bucket: str,
) -> Path:
    """Uploads a file to S3."""
    sys.stdout = open("/dev/null", "w", encoding="utf-8")
    sys.stderr = open("/dev/null", "w", encoding="utf-8")
    disable_warnings(InsecureRequestWarning)

    _session = _get_s3_session(credentials=credentials)
    _bucket = _session.Bucket(bucket)
    _bucket.upload_file(
        Filename=str(local_path),
        Key=remote_key,
        ExtraArgs={"ChecksumAlgorithm": "SHA256"},
    )

    return local_path


def upload_callback(
    logger: LoggerAdapter,
    bucket: str,
    remote_key: str,
) -> Callable[[Path], None]:
    """Callback for uploading files to S3."""

    def inner(local_path: Path) -> None:
        logger.debug(f"Uploaded {local_path.name} to s3://{bucket}/{remote_key}")

    return inner


def upload_error_callback(
    logger: LoggerAdapter,
    bucket: str,
    remote_key: str,
) -> Callable[[Exception], None]:
    """Error callback for uploading files to S3."""

    def inner(exception: Exception) -> None:
        logger.error(
            f"Failed to upload {remote_key} to s3 bucket '{bucket}' ({exception})"
        )

    return inner


def recurse_outputs(outputs: Iterable[Output]) -> Generator[Output, None, None]:
    """Search recursively for output files in the given paths.

    Arguments
    ---------
    outputs: Iterable[Output]
        An iterable of Output objects to search through.

    Returns
    -------
    Generator[Output, None, None]
        A generator of Output objects for each file found in the given paths.
    """
    for output in outputs:
        if output.src.is_file():
            yield output
        elif output.src.is_dir():
            yield from (
                Output(
                    src=file,
                    dst=output.dst / file.relative_to(output.src),
                    checkpoint=output.checkpoint,
                    optional=output.optional,
                )
                for file in output.src.rglob("*")
                if file.is_file()
            )
