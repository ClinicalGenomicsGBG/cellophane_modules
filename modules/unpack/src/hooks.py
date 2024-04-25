"""Module for fetching files from HCP."""
from functools import partial
from logging import LoggerAdapter
from pathlib import Path

from cellophane import Config, Executor, Samples, pre_hook
from mpire.async_result import AsyncResult

from .extractors import Extractor, PetageneExtractor, SpringExtractor
from .util import callback, error_callback

EXTRACORS: dict[str, Extractor] = {
    ".fasterq": PetageneExtractor(),
    ".spring": SpringExtractor(),
}

@pre_hook(label="unpack", after=["hcp_fetch"])
def unpack(
    samples: Samples,
    config: Config,
    logger: LoggerAdapter,
    executor: Executor,
    **_,
) -> Samples:
    """Extract petagene fasterq files."""
    results: list[AsyncResult] = []
    for sample, idx, path, extractor in (
        (s, i, p, EXTRACORS[Path(p).suffix])
        for s in samples
        for i, p in enumerate(s.files)
        if Path(p).suffix in EXTRACORS
    ):
        if result := extractor.extract(
            logger=logger,
            compressed_path=path,
            config=config,
            executor=executor,
            callback=partial(
                callback,
                extractor=extractor,
                timeout=config.unpack.timeout,
                sample=sample,
                idx=idx,
                logger=logger,
                path=path,
            ),
            error_callback=partial(
                error_callback,
                sample=sample,
                logger=logger,
                path=path,
            ),
        ):
            results.append(result)

    executor.wait()
    return samples