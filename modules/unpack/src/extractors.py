from logging import LoggerAdapter
from pathlib import Path
from typing import Callable, Iterator

from cellophane import cfg, executors
from mpire.async_result import AsyncResult


class Extractor:
    """Base class for extractors."""

    label: str
    script: Path

    def __init_subclass__(cls, label: str, script: Path) -> None:
        cls.label = label
        cls.script = script

    @staticmethod
    def extracted_paths(compressed_path: Path) -> Iterator[Path]:
        raise NotImplementedError

    def extract(
        self,
        *,
        logger: LoggerAdapter,
        compressed_path: Path,
        config: cfg.Config,
        env: dict | None = None,
        executor: executors.Executor,
        callback: Callable | None = None,
        error_callback: Callable | None = None,
    ) -> AsyncResult | None:
        """
        Summary:
        Extracts a compressed file using the provided executor and configuration.

        Args:
            logger: LoggerAdapter - The logger to use for logging messages.
            compressed_path: Path - The path to the compressed file to extract.
            config: cfg.Config - The configuration settings to use for extraction.
            env: dict | None - Optional environment variables to set during extraction.
            executor: executors.Executor - The executor to use for jobs.
            callback: Callable | None - Optional callback called on completion.
            error_callback: Callable | None - Optional callback called on error.

        Returns:
            AsyncResult | None - The result of the extraction process,
                or None if already extracted.
        """

        if [*self.extracted_paths(compressed_path)]:  # pylint: disable=using-constant-test
            if callback is not None:
                callback(None)
            return None
        else:
            logger.info(f"Extracting {compressed_path.name} with {self.label}")
            result, _ = executor.submit(
                self.script,
                name=f"unpack_{compressed_path.name}",
                env={
                    **(env or {}),
                    "UNPACK_INIT": config.unpack.get("init", ""),
                    "UNPACK_EXIT": config.unpack.get("exit", ""),
                    "COMPRESSED_PATH": compressed_path,
                    "THREADS": config.unpack.threads,
                },
                cpus=config.unpack.threads,
                workdir=compressed_path.parent,
                callback=callback,
                error_callback=error_callback,
            )

            return result


class PetageneExtractor(
    Extractor,
    label="petagene",
    script=Path(__file__).parent.parent / "scripts" / "petagene.sh",
):
    """Petagene extractor."""
    @staticmethod
    def extracted_paths(compressed_path: Path) -> Iterator[Path]:
        _base = compressed_path.name.partition(".")[0]
        _parent = compressed_path.parent
        if (extracted := _parent / f"{_base}.fastq.gz").exists():
            yield extracted


class SpringExtractor(
    Extractor,
    label="spring",
    script=Path(__file__).parent.parent / "scripts" / "spring.sh",
):
    """Spring extractor."""
    @staticmethod
    def extracted_paths(compressed_path: Path) -> Iterator[Path]:
        _base = compressed_path.name.partition(".")[0]
        _parent = compressed_path.parent
        if (extracted := _parent / f"{_base}.fastq.gz").exists():
            yield extracted

        elif all(
            (
                (extracted1 := _parent / f"{_base}.1.fastq.gz").exists(),
                (extracted2 := _parent / f"{_base}.2.fastq.gz").exists(),
            )
        ):
            yield extracted1
            yield extracted2

        elif all(
            (
                (extracted1 := _parent / f"{_base}.fastq.gz.1").exists(),
                (extracted2 := _parent / f"{_base}.fastq.gz.2").exists(),
            )
        ):
            yield extracted1.rename(_parent / f"{_base}.1.fastq.gz")
            yield extracted2.rename(_parent / f"{_base}.2.fastq.gz")
