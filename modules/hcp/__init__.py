"""Module for fetching files from HCP."""

import sys
from concurrent.futures import ProcessPoolExecutor, Future, as_completed
from logging import LoggerAdapter
from pathlib import Path
from typing import Sequence
from attrs import define, field
from cellophane import cfg, data, modules
from NGPIris import hcp


@define(slots=False, init=False)
class HCPSample(data.Sample):
    """Sample with HCP backup."""

    backup: list[str] | None = field(default=None)

    @backup.validator
    def validate_backup(self, attribute: str, value: Sequence[str] | None) -> None:
        if not (
            value is None
            or (isinstance(value, Sequence) and all(isinstance(v, str) for v in value))
        ):
            raise ValueError(f"Invalid {attribute} value: {value}")


def _fetch(
    credentials: Path,
    local_path: Path,
    remote_key: str,
    s_idx: int,
    f_idx: int,
) -> tuple[int, int, str, Path]:
    sys.stdout = open("/dev/null", "w", encoding="utf-8")
    sys.stderr = open("/dev/null", "w", encoding="utf-8")
    if local_path.exists():
        return s_idx, f_idx, "cache", local_path

    else:
        hcpm = hcp.HCPManager(
            credentials_path=credentials,
            bucket="data",  # FIXME: make this configurable
        )

        hcpm.download_file(
            remote_key,
            local_path=str(local_path),
            callback=False,
            force=True,
        )

        return s_idx, f_idx, "hcp", local_path


@modules.pre_hook(label="HCP", after=["slims_fetch"])
def hcp_fetch(
    samples: data.Samples,
    config: cfg.Config,
    logger: LoggerAdapter,
    **_,
) -> data.Samples:
    """Fetch files from HCP."""

    if "hcp" not in config:
        logger.info("HCP not configured")
        return samples

    _futures: list[Future] = []
    with ProcessPoolExecutor(max_workers=config.hcp.parallel) as pool:
        for s_idx, sample in enumerate(samples):
            if all(Path(f).exists() for f in sample.files):
                logger.info(f"All files for {sample.id} found locally")
                continue
            else:
                sample.files = []
                for f_idx, remote_key in enumerate(sample.backup):
                    logger.info(f"Fetching {remote_key}")
                    _future = pool.submit(
                        _fetch,
                        credentials=config.hcp.credentials,
                        local_path=config.hcp.fastq_temp / Path(remote_key).name,
                        remote_key=remote_key,
                        s_idx=s_idx,
                        f_idx=f_idx,
                    )
                    _futures.append(_future)

    _failed: list[int] = []
    for f in as_completed(_futures):
        try:
            s_idx, f_idx, location, local_path = f.result()
        except Exception as e:
            logger.error(f"Failed to fetch {local_path.name} ({e})")
            samples[s_idx].files = []
            _failed.append(s_idx)
        else:
            if s_idx not in _failed:
                logger.info(f"Fetched {local_path.name} ({location})")
                samples[s_idx].files.insert(f_idx, local_path)

    return samples
