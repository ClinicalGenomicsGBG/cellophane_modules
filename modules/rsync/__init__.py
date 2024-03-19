from copy import copy
from functools import partial
from logging import LoggerAdapter
from pathlib import Path
from time import sleep

from cellophane import cfg, data, executors, modules
from humanfriendly import parse_size


def _sync_callback(
    result: None,
    /,
    logger: LoggerAdapter,
    manifest: list[tuple[str, str]],
    timeout: int,
):
    del result  # Unused
    for src, dst in manifest:
        if not Path(dst).exists():
            logger.debug(f"Waiting {timeout} seconds for {dst} to become available")
        _timeout = copy(timeout)
        while not (available := Path(dst).exists()) and (_timeout := _timeout - 1) > 0:
            sleep(1)
        if available:
            logger.debug(f"Copied {src} -> {dst}")
        else:
            logger.warning(f"{dst} is missing")


@modules.post_hook(label="Sync Output", condition="complete")
def rsync_results(
    samples: data.Samples,
    logger: LoggerAdapter,
    config: cfg.Config,
    workdir: Path,
    executor: executors.Executor,
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
    labels: dict[str, str] = {
        "large": f"large files (>{config.rsync.large_file_threshold})",
        "small": f"small files (<{config.rsync.large_file_threshold})",
        "dir": "directories",
    }
    manifests: dict[str, list[tuple[str, str]]] = {
        "large": [],
        "small": [],
        "dir": [],
    }

    for output in samples.output.copy():
        if not output.src.exists():
            logger.warning(f"{output.src} does not exist")
            samples.output.remove(output)
            continue
        elif output.dst.exists() and not config.rsync.overwrite:
            logger.warning(f"{output.dst} already exists")
            samples.output.remove(output)
            continue
        elif not output.dst.is_relative_to(config.resultdir):
            logger.warning(f"{output.dst} is outside {config.rsync.base}")
            samples.output.remove(output)
            continue

        output.dst.parent.mkdir(parents=True, exist_ok=True)
        if output.src.is_dir():
            manifests["dir"] += [
                (f"{output.src.absolute()}/", f"{output.dst.absolute()}")
            ]
        elif output.src.stat().st_size > parse_size(config.rsync.large_file_threshold):
            manifests["large"] += [
                (f"{output.src.absolute()}", f"{output.dst.absolute()}")
            ]
        else:
            manifests["small"] += [
                (f"{output.src.absolute()}", f"{output.dst.absolute()}")
            ]

    for type_, manifest in manifests.items():
        if manifest:
            logger.info(f"Syncing {len(manifest)} {labels[type_]}")
            manifest_path = workdir / f"rsync.{type_}.manifest"
            with open(manifest_path, "w", encoding="utf-8") as m:
                m.writelines([f"{src} {dst}\n" for src, dst in manifest])
            executor.submit(
                str(Path(__file__).parent / "scripts" / "rsync.sh"),
                name="rsync",
                env={"MANIFEST": str(manifest_path)},
                callback=partial(
                    _sync_callback,
                    logger=logger,
                    manifest=manifest,
                    timeout=config.rsync.timeout,
                ),
            )

    executor.wait()
    logger.info("Finished syncing output")
    return samples
