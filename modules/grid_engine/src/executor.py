import logging
from pathlib import Path
from time import sleep
from typing import Any
from uuid import UUID

import drmaa2
from attrs import define, field
from cellophane import executors


@define(slots=False)
class GridEngineExecutor(
    executors.Executor,
    name="grid_engine",
):  # type: ignore[call-arg]
    """Executor using grid engine."""

    ge_jobs: dict[
        UUID,
        tuple[
            drmaa2.JobSession,
            drmaa2.Job,
        ],
    ] = field(factory=dict, init=False)

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
            while (exit_status := job.get_info().exit_status) is None: # pragma: no cover
                sleep(1)

        if session is not None:
            session.close()
            session.destroy()

        raise SystemExit(exit_status)

    def terminate_hook(self, uuid: UUID, logger: logging.LoggerAdapter) -> int:
        if uuid in self.ge_jobs:
            session, job = self.ge_jobs[uuid]
            logger.debug(f"Terminating SGE job (id={job.id})")
            job.terminate()
            job.wait_terminated()
            session.close()
            session.destroy()
        return 143