"""Module for fetching files from HCP."""

from pathlib import Path
from typing import Optional

from cellophane import cfg, sge


def run_nextflow(
    main: Path,
    *args,
    config: cfg.Config,
    env: dict[str, str] = {},
    log: Optional[Path] = None,
    report: Optional[Path] = None,
    **kwargs,
):
    if "workdir" in config.nextflow:
        config.nextflow.workdir.mkdir(parents=True, exist_ok=True)

    sge.submit(
        str(Path(__file__).parent / "scripts" / "nextflow.sh"),
        f"-log {log}",
        (f"-config {config.nextflow.config}" if "config" in config.nextflow else ""),
        f"run {config.rnaseq.nf_main}",
        "-ansi-log false" if not config.nextflow.ansi_log else "",
        "-resume" if config.nextflow.resume else "",
        f"-work-dir {config.nextflow.workdir}" if "workdir" in config.nextflow else "",
        f"-with-report {report}" if report else "",
        f"-profile {config.nextflow.profile}",
        *args,
        env={"_MODULES_INIT": config.modules_init, **env},
        queue=config.nextflow.sge_queue,
        pe=config.nextflow.sge_pe,
        slots=config.nextflow.sge_slots,
        **kwargs,
    )
