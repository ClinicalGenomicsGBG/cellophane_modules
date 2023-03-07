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
            args = (
                "-d"
                f"-t {config.unpack.sge_slots}"
                f"{compressed_path}"
            )
        case "spring":
            args = (
                "-d"
                f"-t {config.unpack.sge_slots}"
                f"-i {compressed_path}"
                f"-o {extract_path}"
            )
        case _:
            raise ValueError(f"Unknown unpack method: {method}")

    sge.submit(
        str(Path(__file__).parent / "scripts" / f"{method}.sh"),
        args,
        queue=config.unpack.sge_queue,
        pe=config.unpack.sge_pe,
        slots=config.unpack.sge_slots,
        name="petagene",
        stderr=config.logdir / f"{compressed_path.name}.{method}.err",
        stdout=config.logdir / f"{compressed_path.name}.{method}.out",
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
    elif extract_path.exists():
        logger.debug(f"Extracted {extract_path}")
        samples[s_idx].fastq_paths[f_idx] = extract_path
    elif (
        (fq1 := extract_path.with_suffix(".1")).exists() and
        (fq2 := extract_path.with_suffix(".2")).exists()
    ):
        logger.debug(f"Extracted {fq1} and {fq2}")
        samples[s_idx].fastq_paths = [fq1, fq2]
    else:
        logger.error(f"Extraction completed, but {extract_path} does not exist")
        samples[s_idx].fastq_paths[f_idx] = None


@modules.pre_hook(label="unpack", priority=15)
def petagene_extract(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Extract petagene fasterq files."""
    with ProcessPoolExecutor(config.unpack.parallel) as pool:
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
