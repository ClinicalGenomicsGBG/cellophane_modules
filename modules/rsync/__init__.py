import multiprocessing as mp
from copy import copy
from functools import partial
from logging import LoggerAdapter
from pathlib import Path

from cellophane import Config, Executor, Output, Samples, post_hook
from humanfriendly import parse_size


def _sync_callback(
    logger: LoggerAdapter,
    outputs: list[Output],
):
    for o in outputs:
        for s in o.src:
            dest = o.dest_dir / s.name
            if dest.exists():
                logger.debug(f"Copied {dest}")
            else:
                logger.warning(f"{dest} is missing")


@post_hook(label="Sync Output", condition="complete")
def rsync_results(
    samples: Samples,
    logger: LoggerAdapter,
    config: Config,
    workdir: Path,
    executor: Executor,
    **_,
) -> None:
    if "rsync" not in config:
        logger.info("Rsync not configured")
        return
    elif not samples.output:
        logger.warning("No output to sync")
        return
    else:
        logger.info(f"Syncing output to {config.resultdir}")

    # Split outputs into large files, small files, and directories
    _large_files: list[Output] = []
    _small_files: list[Output] = []
    _directories: list[Output] = []
    _outputs = copy(samples.output)
    for output in _outputs:
        if not output.src.exists():
            logger.warning(f"{output.src} does not exist")
            samples.output.remove(output)
        elif [*output.dst.parent.glob("*")] and not config.rsync.overwrite:
            logger.warning(f"{output.dst} is not empty")
            samples.output.remove(output)
        elif not output.dst.is_relative_to(config.resultdir):
            logger.warning(f"{output.dst} is outside {config.rsync.base}")
            samples.output.remove(output)
        elif output.src.is_dir():
            _directories.append(output)
        elif output.src.stat().st_size > parse_size(config.rsync.large_file_threshold):
            _large_files.append(output)
        else:
            _small_files.append(output)

    for tag, label, category in (
        (
            "large",
            f"large file(s) (>{config.rsync.large_file_threshold})",
            _large_files,
        ),
        (
            "small",
            f"small file(s) (<{config.rsync.large_file_threshold})",
            _small_files,
        ),
        (
            "dir",
            "directories",
            _directories,
        ),
    ):
        if category:
            logger.info(f"Syncing {len(category)} {label}")
            manifest_path = workdir / f"rsync.{tag}.manifest"
            with open(manifest_path, mode="w", encoding="utf-8") as manifest:
                for o in category:
                    manifest.write(f"{o.src.absolute()} {o.dst.absolute()}\n")

            for o in category:
                o.dst.parent.mkdir(parents=True, exist_ok=True)

            logger.debug(f"Manifest: {manifest_path}")
            logger.debug(manifest_path.read_text(encoding="utf-8"))

            executor.submit(
                str(Path(__file__).parent / "scripts" / "rsync.sh"),
                config=config,
                name="rsync",
                check=False,
                env={"MANIFEST": str(manifest_path)},
                callback=partial(
                    _sync_callback,
                    logger=logger,
                    outputs=category,
                ),
            )

    executor.wait()
    logger.info("Finished syncing output")
