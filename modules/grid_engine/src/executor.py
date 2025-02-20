import logging
from pathlib import Path
from time import sleep
from typing import Any
from uuid import UUID

import drmaa2
from attrs import define
from cellophane import Executor

_GE_JOBS: dict[UUID, dict[UUID, tuple[drmaa2.JobSession, drmaa2.Job]]] = {}


def _destroy_ge_session(session: drmaa2.JobSession, logger: logging.LoggerAdapter) -> None:
    if session.name is not None and session.name in drmaa2.JobSession.list_session_names():
        try:
            session.close()
            session.destroy()
        except drmaa2.Drmaa2Exception as exc:
            logger.warning(f"Caught an exception while closing SGE session ({session.name=}): {exc!r}")

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
        **kwargs: Any,
    ) -> None:
        del kwargs  # Unused
        _logdir = self.config.logdir / "grid_engine" / uuid.hex
        _logdir.mkdir(exist_ok=True, parents=True)

        session = None
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
                    "job_name": f"{name}_{uuid.hex[:8]}",
                    "job_environment": env,
                    "output_path": str(_logdir / f"{name}.out"),
                    "error_path": str(_logdir / f"{name}.err"),
                    "working_directory": str(workdir),
                }
            )
            logger.debug(f"Grid Engine job started ({name=}, {uuid=}, {job.id=})")
            self.ge_jobs[uuid] = (session, job)
        except drmaa2.Drmaa2Exception as exception:
            logger.error(f"Failed to submit job to Grid Engine ({name=}, {uuid=})")
            logger.debug(f"Message: {exception}", exc_info=exception)
            with open(
                _logdir / f"{name}.err",
                mode="w",
                encoding="utf-8",
            ) as f:
                f.write(str(exception))

            exit_status = 1
        else:
            while (
                exit_status := job.get_info().exit_status
            ) is None:  # pragma: no cover
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
                logger.debug(f"Terminating SGE job (id={job.id})")
                job.terminate()
                job.wait_terminated()
                logger.debug(f"SGE job terminated (id={job.id})")
            except drmaa2.Drmaa2Exception as exc:
                logger.warning(
                    "Caught an exception while terminating SGE job "
                    f"({job.id=}): {exc!r}"
                )
            _destroy_ge_session(session, logger)
            del self.ge_jobs[uuid]
        return 143
