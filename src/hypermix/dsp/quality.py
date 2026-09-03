"""Central MS-20M quality profiles — one place, no magic numbers in DSP fns."""
from __future__ import annotations

MS20M_QUALITY = {
    "preview": {
        "oversample": 8,
        "fir_stopband_db": 100.0,
        "internal_dtype": "float64",
    },
    "production": {
        "oversample": 16,
        "fir_stopband_db": 120.0,
        "internal_dtype": "float64",
    },
    "reference": {
        "oversample": 32,
        "fir_stopband_db": 140.0,
        "internal_dtype": "float64",
    },
}

DEFAULT_QUALITY = "production"
