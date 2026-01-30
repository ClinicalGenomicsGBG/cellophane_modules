"""Nextflow-specific mixins for Cellophane."""

import re
from logging import LoggerAdapter
from pathlib import Path

from cellophane import Samples

# Prefer explicit tokens first (R1/R2), then fall back to bare 1/2 tokens.
_EXPLICIT = re.compile(r"(?i)(?<=[._-])R([12])(?=[._-])")
_NUMERIC  = re.compile(r"(?<=[._-])([12])(?=[._-])")

def _infer_read(path: str | Path) -> tuple[int | None, str]:
    """
    Infer read number (1 or 2) from filename tokens.
    Returns (read, how). If read is None, 'how' explains why.
    """
    name = Path(path).name  # Extract the filename only

    # Try first explicit R1/R2 tokens, then bare 1/2 tokens.
    for pattern, how in ((_EXPLICIT, "explicit R1/R2 token"), (_NUMERIC, "numeric 1/2 token")):
        seen: set[int] = set()

        for match in pattern.finditer(name):
            val = int(match.group(1))  # Extract the read number (1 or 2)
            seen.add(val)  # within the set, multiple of the same value is fine

        if seen:
            if len(seen) > 1:  # E.g. both R1 and R2 found within one filename
                return None, f"ambiguous: found both {sorted(seen)} via {how}"
            return next(iter(seen)), how

    return None, "no R1/R2 marker found"

def split_r1_r2(files, *, logger: LoggerAdapter | None = None, sample_id = None):
    """
    Strictly split a 2-file FASTQ pair into (R1, R2).
    """
    if len(files) == 1:
        if logger:
            logger.info(f"Only one FASTQ file found for sample {sample_id!r}, assuming single-end data.")
        return str(files[0]), None
    elif len(files) != 2:
        raise ValueError(f"Expected either 1 (single-end) or 2 (paired-end) FASTQ files for sample {sample_id!r}, got {len(files)}")

    r1: str | None = None
    r2: str | None = None

    for f in files:
        read, how = _infer_read(f)

        if read is None:
            raise ValueError(f"Could not classify FASTQ {f!s} for sample {sample_id!r}: {how}")
        
        if logger:
            logger.debug(f"Classified FASTQ {f} as R{read} {how}")

        if read == 1:
            if r1 is not None:
                raise ValueError(f"Multiple R1 files for sample {sample_id!r}: {r1} and {f}")
            r1 = str(f)
        else:  # read == 2
            if r2 is not None:
                raise ValueError(f"Multiple R2 files for sample {sample_id!r}: {r2} and {f}")
            r2 = str(f)

    if r1 is None or r2 is None:
        raise ValueError(f"Missing R1 or R2 for sample {sample_id!r}: {[str(f) for f in files]}")

    return r1, r2

class NextflowSamples(Samples):
    """Samples with Nextflow-specific methods."""

    def nfcore_samplesheet(
        self,
        *_,
        location: str | Path,
        logger: LoggerAdapter | None = None,
        **kwargs,
    ) -> Path:
        """Write a Nextflow samplesheet"""
        Path(location).mkdir(parents=True, exist_ok=True)
        
        _data = []
        for sample in self:
            r1, r2 = split_r1_r2(sample.files, logger=logger, sample_id=sample.id)

            row = {
                "sample": sample.id,
                "fastq_1": r1,
                "fastq_2": r2,
                **{
                    k: (v.format(sample=sample) if isinstance(v, str) else v)
                    for k, v in kwargs.items()
                },
            }

            _data.append({k: "" if v is None else str(v) for k, v in row.items()})


        _header = ",".join(_data[0].keys())

        _samplesheet = "\n".join([_header, *(",".join(d.values()) for d in _data)])
        _path = Path(location) / "samples.nextflow.csv"
        with open(_path, "w", encoding="utf-8") as handle:
            handle.write(_samplesheet)

        return _path
