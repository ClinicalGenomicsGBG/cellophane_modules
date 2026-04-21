"""Hooks for fetching files from S3 bucket."""

from collections import deque
from logging import LoggerAdapter
from pathlib import Path
from urllib.parse import urlparse

from cellophane import Cleaner, Config, Samples, pre_hook, post_hook, Output
from mpire import WorkerPool

from .util import (
    callback,
    error_callback,
    fetch,
    get_endpoint_credentials,
    recurse_outputs,
    upload,
    upload_callback,
    upload_error_callback,
)


@pre_hook(after=["slims_fetch"])
def s3_fetch(
    samples: Samples,
    config: Config,
    logger: LoggerAdapter,
    cleaner: Cleaner,
    workdir: Path,
    **_,
) -> Samples:
    """Fetch files from S3."""
    for sample in samples.with_files:
        logger.debug(f"Found all files for {sample.id} locally")

    if not config.s3.get("credentials"):
        logger.warning("Missing credentials for S3 backup")
        return samples

    if samples.without_files:
        logger.info(f"Fetching {len(samples.without_files)} samples from S3 bucket")

    with WorkerPool(
        n_jobs=config.s3.parallel,
        use_dill=True,
    ) as pool:
        for sample in samples.without_files:
            if sample.s3_remote_keys is None:
                logger.warning(f"No backup for {sample.id}")
                continue
            if sample.s3_bucket is None:
                logger.warning(f"No S3 bucket for {sample.id}")
                continue
            if sample.s3_endpoint is None:
                logger.warning(f"No S3 endpoint for {sample.id}")
                continue
            if (credentials := get_endpoint_credentials(config.s3.credentials, sample.s3_endpoint)) is None:
                logger.warning(f"No credentials for S3 endpoint '{sample.s3_endpoint}'")
                continue

            fastq_temp = (workdir / "from_s3")
            for f_idx, remote_key in enumerate(sample.s3_remote_keys):
                local_path = fastq_temp / Path(remote_key).name

                if local_path.exists():
                    sample.files[f_idx] = local_path
                    logger.debug(f"Found {local_path.name} locally")
                    cleaner.register(local_path.resolve())
                    continue

                fastq_temp.mkdir(parents=True, exist_ok=True)
                pool.apply_async(
                    fetch,
                    kwargs={
                        "credentials": credentials,
                        "local_path": local_path,
                        "remote_key": remote_key,
                        "bucket": sample.s3_bucket,
                    },
                    callback=callback(
                        sample=sample,
                        f_idx=f_idx,
                        logger=logger,
                        cleaner=cleaner,
                        bucket=sample.s3_bucket,
                    ),
                    error_callback=error_callback(
                        sample=sample,
                        logger=logger,
                        bucket=sample.s3_bucket,
                    ),
                )

        pool.join()

    return samples


@post_hook(label="S3 Upload", condition="complete")
def s3_upload_results(
    samples: Samples,
    config: Config,
    logger: LoggerAdapter,
    **_,
) -> None:
    """Upload output files to S3."""

    if not config.s3.upload.get("enable"):
        logger.info("S3 upload is disabled, skipping")
        return
    if not config.s3.get("credentials"):
        logger.warning("Missing credentials for S3 upload, skipping")
        return
    if not samples.output:
        logger.warning("No output to upload to S3, skipping")
        return

    endpoint = config.s3.upload.get("endpoint")
    if not (credentials := get_endpoint_credentials(
        config.s3.get("credentials"),
        endpoint,
    )):
        logger.warning(f"No credentials for S3 endpoint '{endpoint}', skipping")
        return

    upload_path = config.s3.upload.get("path")
    parsed = urlparse(upload_path)
    upload_bucket = parsed.netloc
    # AWS keys do not start with a slash, but urlparse includes the leading slash in the path, so we need to remove it
    upload_prefix = parsed.path.lstrip("/")


    logger.info(f"Uploading output to {upload_path}")

    with WorkerPool(
        n_jobs=config.s3.parallel,
        use_dill=True,
    ) as pool:

        for output in recurse_outputs(samples.output):
            # Preserve directory structure of results in S3
            # output.dst is already prefixed with resultdir
            relative_dst = output.dst.relative_to(config.get("resultdir"))
            # Making sure to avoid double slashes
            remote_key = f"{upload_prefix.rstrip('/')}/{relative_dst}"
            pool.apply_async(
                upload,
                kwargs={
                    "credentials": credentials,
                    "local_path": output.src,
                    "remote_key": remote_key,
                    "bucket": upload_bucket,
                },
                callback=upload_callback(
                    logger=logger,
                    bucket=upload_bucket,
                    remote_key=remote_key,
                ),
                error_callback=upload_error_callback(
                    logger=logger,
                    bucket=upload_bucket,
                    remote_key=remote_key,
                ),
            )

        pool.join()

    logger.info("Finished uploading output to S3")
