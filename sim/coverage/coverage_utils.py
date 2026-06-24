"""Shared helpers for the deterministic cocotb functional coverage suite."""

import os
from pathlib import Path

from cocotb_coverage.coverage import coverage_db


FIXED_SEED = 0x5EEDC0DE


def export_coverage() -> None:
    output = Path(os.environ["COVERAGE_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    coverage_db.export_to_yaml(str(output))


def to_fixed_18(value: float) -> int:
    return int(round(value * (1 << 10)))


def signed_18(value: int) -> int:
    return value - (1 << 18) if value & (1 << 17) else value


def safe_int(value, *, default=None) -> int:
    """Convert a resolved simulation value to int.

    Pass an explicit ``default`` only for pre-reset/startup sampling where X/Z
    is expected. Post-reset checks must fail on unresolved values instead of
    silently treating them as zero.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise
