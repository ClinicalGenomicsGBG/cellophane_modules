"""Hooks for fetching files from S3 bucket."""

from logging import LoggerAdapter
from pathlib import Path

from cellophane import Cleaner, Config, Samples, pre_hook
from mpire import WorkerPool

from .util import callback, error_callback, fetch


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
            sample.files = []
            if sample.s3_remote_keys is None:
                logger.warning(f"No backup for {sample.id}")
                continue

            fastq_temp = (workdir / "from_s3")
            for f_idx, remote_key in enumerate(sample.s3_remote_keys):
                local_path = fastq_temp / Path(remote_key).name

                if local_path.exists():
                    sample.files.insert(f_idx, local_path)
                    logger.debug(f"Found {local_path.name} locally")
                    cleaner.register(local_path.resolve())
                    continue

                fastq_temp.mkdir(parents=True, exist_ok=True)
                pool.apply_async(
                    fetch,
                    kwargs={
                        "credentials": config.s3.credentials,
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
