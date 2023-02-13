"""Module for fetching files from HCP."""

import multiprocessing as mp
import os
import sys
from functools import partial
from logging import LoggerAdapter
from pathlib import Path
from typing import Optional

from NGPIris import hcp

from cellophane import cfg, data, modules


def _fetch(
    config: cfg.Config,
    local_path: Path,
    remote_key: Optional[str] = None,
) -> None:
    sys.stdout = open(
        config.logdir / f"iris.{local_path.name}.out", "w", encoding="utf-8"
    )
    sys.stderr = open(
        config.logdir / f"iris.{local_path.name}.err", "w", encoding="utf-8"
    )

    hcpm = hcp.HCPManager(
        credentials_path=config.iris.credentials,
        bucket="data",  # FIXME: make this configurable
    )

    if remote_key is None:
        search_path = local_path
        while Path(search_path).suffix:
            search_path = search_path.with_suffix("")

        result = hcpm.search_objects(search_path.name)
        if result is not None and len(result) == 1:
            remote_key = result[0].key
        else:
            raise ValueError(f"Could not find remote key for {local_path}")
    if not local_path.exists():
        hcpm.download_file(
            remote_key,
            local_path=str(local_path),
            callback=False,
            force=True,
        )


def _fetch_callback(
    exception: Optional[Exception],
    /,
    config: cfg.Config,
    logger: LoggerAdapter,
    samples: data.Samples,
    local_path: Path,
    s_idx: int,
    f_idx: int,
):
    if exception is not None:
        logger.error(
            f"Failed to fetch {local_path} from HCP",
            exc_info=config.log_level == "DEBUG",
        )
        samples[s_idx].fastq_paths[f_idx] = None
    else:
        samples[s_idx].fastq_paths[f_idx] = str(local_path)


@modules.pre_hook(label="HCP", priority=10)
def hcp_fetch(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Fetch files from HCP."""
    with mp.Pool(processes=config.iris.parallel) as pool:
        for s_idx, sample in enumerate(samples):
            if all(
                fastq is not None and Path(fastq).exists()
                for fastq in sample.fastq_paths
            ):
                logger.debug(f"Files found for {sample.id} {sample.fastq_paths}")

            elif "remote_keys" in sample.backup:
                logger.info(f"Fetching files for {sample.id} from HCP")
                if "remote_keys" not in sample.backup:
                    logger.warning(f"Remote key not found for {sample.id}, will search")
                    sample.backup.remote_keys = [None] * len(sample.fastq_paths)

                for f_idx, local_key in enumerate(sample.fastq_paths):
                    remote_key = sample.backup.remote_keys[f_idx]
                    _local_key = local_key or remote_key or f"{sample.id}_{f_idx}"
                    local_path = config.iris.fastq_temp / Path(_local_key).name

                    callback = partial(
                        _fetch_callback,
                        config=config,
                        logger=logger,
                        samples=samples,
                        local_path=local_path,
                        s_idx=s_idx,
                        f_idx=f_idx,
                    )

                    pool.apply_async(
                        _fetch,
                        kwds={
                            "config": config,
                            "remote_key": remote_key,
                            "local_path": local_path,
                        },
                        callback=callback,
                        error_callback=callback,
                    )
            else:
                logger.warning(f"Unable to fetch files for {sample.id} from HCP")

        pool.close()
        pool.join()

    return samples.__class__([s for s in samples if s is not None])
