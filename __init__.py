"""Module for fetching files from HCP."""

from concurrent.futures import ProcessPoolExecutor, Future, as_completed
import os
import sys
from functools import partial
from logging import LoggerAdapter
from pathlib import Path

from cellophane import cfg, data, modules, sge


def _extract(
    fasterq_path: Path,
    extract_path: Path,
    config: cfg.Config,
) -> None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

    sge.submit(
        str(Path(__file__).parent / "scripts" / "petasuite.sh"),
        f"-d -f -t {config.petagene.sge_slots} {fasterq_path}",
        env={"_MODULES_INIT": config.modules_init},
        queue=config.petagene.sge_queue,
        pe=config.petagene.sge_pe,
        slots=config.petagene.sge_slots,
        name="petagene",
        stderr=config.logdir / f"{extract_path.name}.petagene.err",
        stdout=config.logdir / f"{extract_path.name}.petagene.out",
        cwd=fasterq_path.parent,
        check=True,
    )


@modules.pre_hook(label="petagene", priority=15)
def petagene_extract(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Extract petagene fasterq files."""

    results: dict[Future, tuple[int, int, str, str]] = {}
    with ProcessPoolExecutor(config.petagene.parallel) as pool:
        for s_idx, sample in enumerate(samples):
            for f_idx, fastq in enumerate(sample.fastq_paths):
                if Path(fastq).exists() and Path(fastq).suffix == ".fasterq":
                    fasterq_path = Path(fastq)
                    extract_path = fasterq_path.with_suffix(".fastq.gz")
                    if extract_path.exists():
                        logger.debug(f"Extracted file found for {sample.id}")
                        sample.fastq_paths[f_idx] = extract_path
                        continue
                    else:
                        logger.debug(f"Extracting {fasterq_path} to {extract_path}")
                        results |= {
                            pool.submit(
                                _extract,
                                fasterq_path=fasterq_path,
                                extract_path=extract_path,
                                config=config,
                            ): (s_idx, f_idx, str(extract_path), str(fasterq_path))
                        }

        pool.shutdown(wait=False)

    for future in as_completed(results.keys()):
        s_idx, f_idx, extract, fasterq = results[future]
        if (exception := future.exception()) is not None:
            logger.error(f"Failed to extract {fasterq} ({exception})")
            samples[s_idx].fastq_paths[f_idx] = None
        else:
            logger.debug(f"Extracted {fasterq} to {extract}")
            samples[s_idx].fastq_paths[f_idx] = extract_path

    return samples.__class__([s for s in samples if s is not None])
