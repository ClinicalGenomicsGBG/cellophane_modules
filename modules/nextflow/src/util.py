"""Module for fetching files from HCP."""

from pathlib import Path
from uuid import UUID, uuid4

from cellophane import cfg, executors
from mpire.async_result import AsyncResult

_ROOT = Path(__file__).parent.parent


def nextflow(
    main: Path,
    *args,
    config: cfg.Config,
    executor: executors.Executor,
    workdir: Path,
    env: dict[str, str] | None = None,
    nxf_config: Path | None = None,
    nxf_work: Path | None = None,
    nxf_launch: Path | None = None,
    nxf_profile: str | None = None,
    nxf_log: Path | None = None,
    ansi_log: bool = False,
    resume: bool = False,
    name: str = "nextflow",
    check: bool = True,
    **kwargs,
) -> tuple[AsyncResult, UUID]:
    """Submit a Nextflow job to SGE."""

    uuid_ = uuid4()
    _nxf_log = nxf_log or workdir / f"{name}.{uuid_.hex}.nextflow.log"
    _nxf_config = nxf_config or config.nextflow.get("config")
    _nxf_work = nxf_work or config.nextflow.get("workdir") or workdir / "nxf_work"
    _nxf_launch = nxf_launch or config.nextflow.get("launch_dir") or workdir / "nxf_launch"
    _nxf_profile = nxf_profile or config.nextflow.get("profile")

    _nxf_log.parent.mkdir(parents=True, exist_ok=True)
    _nxf_work.mkdir(parents=True, exist_ok=True)

    result, uuid = executor.submit(
        str(_ROOT / "scripts" / "nextflow.sh"),
        f"-log {_nxf_log}",
        (f"-config {_nxf_config}" if _nxf_config else ""),
        f"run {main}",
        "-ansi-log false" if not ansi_log or config.nextflow.ansi_log else "",
        f"-work-dir {_nxf_work}",
        "-resume" if resume else "",
        f"-with-report {workdir / f'{name}.{uuid_.hex}.report.html'}",
        (f"-profile {_nxf_profile}" if _nxf_profile else ""),
        *args,
        env={
            "_NXF_INIT": config.nextflow.init,
            "_NXF_LAUNCH": str(_nxf_launch),
            **config.nextflow.env,
            **(env or {}),
        },
        workdir=workdir,
        uuid=uuid_,
        name=name,
        cpus=config.nextflow.threads,
        conda_spec=config.nextflow.conda_spec,
        **kwargs,
    )

    if check:
        result.get()

    return result, uuid
