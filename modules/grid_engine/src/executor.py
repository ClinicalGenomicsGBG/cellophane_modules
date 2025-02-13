import logging
from pathlib import Path
from time import sleep
from typing import Any
from uuid import UUID

import drmaa2
from attrs import define
from cellophane import Executor
from cellophane.util import freeze_logs

_GE_JOBS: dict[UUID, dict[UUID, tuple[drmaa2.JobSession, drmaa2.Job]]] = {}


def _destroy_ge_session(session: drmaa2.JobSession, logger: logging.LoggerAdapter) -> None:
    if session.name is not None and session.name in drmaa2.JobSession.list_session_names():
        try:
            session.close()
            session.destroy()
        except drmaa2.Drmaa2Exception as exc:
            logger.warning(f"Caught an exception while closing Grid Engine session '{session.name=}': {exc!r}")

@define(slots=False, init=False)
class GridEngineExecutor(Executor, name="grid_engine"):  # type: ignore[call-arg]
    """Executor using grid engine."""

    @property
    def ge_jobs(self) -> dict[UUID, tuple[drmaa2.JobSession, drmaa2.Job]]:
        if self.uuid not in _GE_JOBS:
            _GE_JOBS[self.uuid] = {}
        return _GE_JOBS[self.uuid]

    def target(
        self,
        *args: str,
        name: str,
        uuid: UUID,
        workdir: Path,
        env: dict[str, str],
        os_env: bool = True,
        logger: logging.LoggerAdapter,
        cpus: int,
        stdout: Path | None = None,
        stderr: Path | None = None,
        **kwargs: Any,
    ) -> None:
        del kwargs  # Unused
        _name = f"{name}_{uuid.hex[:8]}"
        # NOTE: Thw stdout and stderr kwargs will be added in a feature release of cellophane.
        # This is a workaround to remain compatible with the 1.1.x and earlier versions.
        _stdout = stdout or workdir / f"{_name}.grid_engine.out"
        _stderr = stderr or workdir / f"{_name}.grid_engine.err"

        session = None
        exit_status: int | None = None
        try:
            session = drmaa2.JobSession(_name)
            job = session.run_job(
                {
                    "remote_command": args[0],
                    "args": args[1:],
                    "min_slots": cpus,
                    "implementation_specific": {
                        "uge_jt_pe": self.config.grid_engine.pe,
                        "uge_jt_native": (
                            "-l excl=1 "
                            "-S /bin/bash "
                            f"-notify -q {self.config.grid_engine.queue} "
                            f"{'-V' if os_env else ''}"
                        ),
                    },
                    "job_name": f"{name}_{uuid.hex[:8]}",
                    "job_environment": env,
                    "output_path": str(_stdout),
                    "error_path": str(_stderr),
                    "working_directory": str(workdir),
                }
            )
            logger.debug(f"Grid Engine job started ({_name}, {job.id=})")
            self.ge_jobs[uuid] = (session, job)
        except drmaa2.Drmaa2Exception as exception:
            logger.error(f"Failed to submit job to Grid Engine ({_name})")
            logger.debug(f"Message: {exception}", exc_info=exception)
            _stderr.write_text(str(exception))
            exit_status = 1
        else:
            while exit_status is None:
                with freeze_logs():
                    exit_status = job.get_info().exit_status
                sleep(1)


        if uuid in self.ge_jobs:
            session, _ = self.ge_jobs[uuid]
            _destroy_ge_session(session, logger)
            del self.ge_jobs[uuid]

        raise SystemExit(exit_status)

    def terminate_hook(self, uuid: UUID, logger: logging.LoggerAdapter) -> int:
        if uuid in self.ge_jobs:
            session, job = self.ge_jobs[uuid]
            try:
                job.terminate()
                job.wait_terminated()
                logger.debug(f"Grid Engine job '{job.job_name}' (id={job.id}) terminated")
            except drmaa2.Drmaa2Exception as exc:
                logger.warning(
                    f"Caught an exception while terminating Grid Engine job '{job.job_name}' ({job.id=}): {exc!r}"
                )
            _destroy_ge_session(session, logger)
            del self.ge_jobs[uuid]
        return 143
