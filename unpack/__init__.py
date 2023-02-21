"""Module for fetching files from HCP."""

from concurrent.futures import ProcessPoolExecutor, Future
import os
import sys
from functools import partial
from logging import LoggerAdapter
from pathlib import Path

from cellophane import cfg, data, modules, sge


def _extract(
    method: str,
    /,
    compressed_path: Path,
    extract_path: Path,
    config: cfg.Config,
) -> None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

    match method:
        case "petagene":
            args = f"-d -t {config.unpack.sge_slots} {compressed_path}"
        case "spring":
            args = f"-d -t {config.unpack.sge_slots} {compressed_path}"
        case _:
            raise ValueError(f"Unknown unpack method: {method}")

    sge.submit(
        str(Path(__file__).parent / "scripts" / f"{method}.sh"),
        args,
        env={"_MODULES_INIT": config.modules_init},
        queue=config.unpack.sge_queue,
        pe=config.unpack.sge_pe,
        slots=config.unpack.sge_slots,
        name="petagene",
        stderr=config.logdir / f"{extract_path.name}.{method}.err",
        stdout=config.logdir / f"{extract_path.name}.{method}.out",
        cwd=compressed_path.parent,
        check=True,
    )


def _extract_callback(
    future: Future,
    /,
    logger: LoggerAdapter,
    samples: data.Samples,
    compressed_path: Path,
    extract_path: Path,
    s_idx: int,
    f_idx: int,
):
    if (exception := future.exception()) is not None:
        logger.error(f"Failed to extract {compressed_path} ({exception})")
        samples[s_idx].fastq_paths[f_idx] = None
    else:
        logger.debug(f"Extracted {compressed_path} to {extract_path}")
        samples[s_idx].fastq_paths[f_idx] = extract_path


@modules.pre_hook(label="petagene", priority=15)
def petagene_extract(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Extract petagene fasterq files."""

    with ProcessPoolExecutor(config.petagene.parallel) as pool:
        for s_idx, sample in enumerate(samples):
            for f_idx, fastq in enumerate(sample.fastq_paths):
                if (compressed_path := Path(fastq)).exists():
                    if compressed_path.suffix == ".fasterq":
                        method = "petagene"
                    elif compressed_path.suffix == ".spring":
                        method = "spring"
                    else:
                        continue

                    extract_path = compressed_path.with_suffix(".fastq.gz")
                    if extract_path.exists():
                        logger.debug(f"Extracted file found for {sample.id}")
                        sample.fastq_paths[f_idx] = extract_path
                        continue
                    else:
                        logger.debug(f"Extracting {compressed_path} to {extract_path}")
                        pool.submit(
                            _extract,
                            method,
                            compressed_path=compressed_path,
                            extract_path=extract_path,
                            config=config,
                        ).add_done_callback(
                            partial(
                                _extract_callback,
                                logger=logger,
                                samples=samples,
                                compressed_path=compressed_path,
                                extract_path=extract_path,
                                s_idx=s_idx,
                                f_idx=f_idx,
                            )
                        )

    return samples.__class__([s for s in samples if s is not None])
