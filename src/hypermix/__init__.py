"""HyperMix — phrase-native, sample-clock-driven music compiler.

Canonical time is the integer sample index at HYPERMIX_SAMPLE_RATE.
See docs/HyperMix_Complete_Implementation_Instructions.md for the full spec.
"""

__version__ = "0.1.0"
COMPILER_NAME = "hypermix"

from .config import HyperMixConfig, DEFAULT_CONFIG  # noqa: F401
from .errors import HyperMixError, ErrorCode  # noqa: F401
