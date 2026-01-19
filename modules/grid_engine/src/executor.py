import logging
from pathlib import Path
from time import sleep
from traceback import format_exception
from typing import Any
from uuid import UUID, uuid4

import drmaa2
from attrs import define, field
from cellophane import Executor, util


def _destroy_ge_session(session: drmaa2.JobSession, logger: logging.LoggerAdapter) -> None:
    if session.name is not None and session.name in drmaa2.JobSession.list_session_names():
        try:
            session.close()
            session.destroy()
        except drmaa2.Drmaa2Exception as exc:
            logger.warning(f"Exception while closing Grid Engine session '{session.name=}': {exc!r}")

@define(slots=False, init=False)
class GridEngineExecutor(Executor, name="grid_engine"):
    """Executor using grid engine."""

    uuid: UUID = uuid4()
    _ge_jobs: dict[UUID, tuple[drmaa2.JobSession, drmaa2.Job, str]] = field(factory=dict, init=False, repr=False)

    def __getstate__(self) -> dict[str, Any]:
        return super().__getstate__() | {"_ge_jobs": {}}

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
        # NOTE: Thw stdout and stderr kwargs will be added in a feature release of cellophane.
        # This is a workaround to remain compatible with the 1.1.x and earlier versions.
        _stdout = stdout or workdir / f"{name}.{uuid.hex}.grid_engine.out"
        _stderr = stderr or workdir / f"{name}.{uuid.hex}.grid_engine.err"

        session = None
        exit_status: int | None = None
        try:
            session = drmaa2.JobSession(f"{name}_{uuid.hex}")
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
                    "job_name": f"{name}_{uuid.hex}",
                    "job_environment": env,
                    "output_path": str(_stdout),
                    "error_path": str(_stderr),
                    "working_directory": str(workdir),
                }
            )
            logger.debug(f"Submitted job '{name}' to Grid Engine (UUID={uuid.hex[:8]} JID={job.id})")
            self._ge_jobs[uuid] = (session, job, name)
        except drmaa2.Drmaa2Exception as exc:
            logger.error(f"Failed to submit job '{name}' to Grid Engine (UUID={uuid.hex[:8]}): {exc!r}")
            with open(_stderr, "a", encoding="utf-8") as err:
                err.writelines(format_exception(type(exc), exc, exc.__traceback__))
            exit_status = 1
        else:
            while exit_status is None:
                with util.freeze_logs():
                    exit_status = job.get_info().exit_status
                sleep(1)


        if uuid in self._ge_jobs:
            session, _, _ = self._ge_jobs[uuid]
            _destroy_ge_session(session, logger)
            del self._ge_jobs[uuid]

        raise SystemExit(exit_status)

    def terminate_hook(self, uuid: UUID, logger: logging.LoggerAdapter) -> int:
        if uuid in self._ge_jobs:
            session, job, name = self._ge_jobs[uuid]
            try:
                job.terminate()
                job.wait_terminated()
                logger.debug(f"Terminated Grid Engine job '{name}' (UUID={uuid.hex[:8]} JID={job.id})")
            except drmaa2.Drmaa2Exception as exc:
                logger.warning(
                    f"Exception while terminating Grid Engine job '{name}' (UUID={uuid.hex[:8]} JID={job.id}): {exc!r}"
                )
            finally:
                _destroy_ge_session(session, logger)
                del self._ge_jobs[uuid]
        return 143
