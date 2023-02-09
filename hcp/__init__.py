"""Module for fetching files from HCP."""

import multiprocessing as mp
import os
import sys
from logging import LoggerAdapter
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Optional

from NGPIris import hcp

from cellophane import data, cfg, modules, sge


def _fetch(
    local_path: Path,
    config: cfg.Config,
    pipe: Connection,
    remote_key: Optional[str] = None,
) -> None:
    sys.stdout = open(config.logdir / f"iris.{local_path.name}.out", "w", encoding="utf-8")
    sys.stderr = open(config.logdir / f"iris.{local_path.name}.err", "w", encoding="utf-8")

    hcpm = hcp.HCPManager(
        credentials_path=config.iris.credentials,
        bucket="data",  # FIXME: make this configurable
    )

    _local_path = local_path
    while Path(_local_path).suffix:
        _local_path = _local_path.with_suffix("")

    if (_remote_key := remote_key) is None:
        remote = hcpm.search_objects(_local_path.name)
        if remote is not None and len(remote) == 1:
            _remote_key = remote[0].key
        else:
            print(f"Could not find remote key for {local_path}")
            raise SystemExit(1)

    if (suffix := Path(_remote_key).suffix) in (".fasterq", ".fastq", ".fastq.gz"):
        _local_path = _local_path.with_suffix(suffix)
    else:
        print(f"Could not determine suffix for {local_path}")
        raise SystemExit(1)

    if not _local_path.exists():
        hcpm.download_file(
            _remote_key,
            local_path=str(_local_path),
            callback=False,
            force=True,
        )

    if _local_path.suffix == ".fasterq":
        if not _local_path.with_suffix(".fastq.gz").exists():
            sge.submit(
                str(Path(__file__).parent / "scripts" / "petasuite.sh"),
                f"-d -f -t {config.petasuite.sge_slots} {_local_path}",
                env={"_MODULES_INIT": config.modules_init},
                queue=config.petasuite.sge_queue,
                pe=config.petasuite.sge_pe,
                slots=config.petasuite.sge_slots,
                name="petasuite",
                stderr=config.logdir / f"petasuite.{local_path.name}.err",
                stdout=config.logdir / f"petasuite.{local_path.name}.out",
                cwd=local_path.parent,
                check=True,
            )
        _local_path = _local_path.with_suffix(".fastq.gz")

    pipe.send(_local_path)
    pipe.close()


@modules.pre_hook(label="HCP", priority=10)
def hcp_fetch(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Fetch files from HCP."""

    _procs: list[tuple[mp.Process, int, int, Connection]] = []

    for s_idx, sample in enumerate(samples):
        if all(Path(p).exists() for p in sample.fastq_paths):
            logger.debug(
                f"Files found for {sample.id} ({','.join(sample.fastq_paths)})"
            )
        else:
            logger.info(f"Fetching files for {sample.id} from HCP")
            if "remote_keys" not in sample.backup:
                logger.warning(f"Remote key not found for {sample.id}, will search")
                sample.backup.remote_keys = [None, None]
            for f_idx, fastq in enumerate(sample.fastq_paths):
                remote_key: Optional[str] = (
                    sample.backup.remote_keys[f_idx]
                    if "remote_keys" in sample.backup
                    else None
                )

                local_path = config.iris.fastq_temp / Path(fastq).name

                _in, _out = mp.Pipe()
                proc = mp.Process(
                    target=_fetch,
                    kwargs={
                        "pipe": _in,
                        "remote_key": remote_key,
                        "local_path": local_path,
                        "config": config,
                    },
                )
                proc.start()
                _procs.append((proc, s_idx, f_idx, _out))

    for proc, s_idx, f_idx, pipe in _procs:
        proc.join()
        if proc.exitcode != 0:
            logger.error(f"Failed to fetch {samples[s_idx].id}")
            samples[s_idx].fastq_paths[f_idx] = None
        else:
            samples[s_idx].fastq_paths[f_idx] = pipe.recv()

    return samples.__class__([s for s in samples if s is not None])
