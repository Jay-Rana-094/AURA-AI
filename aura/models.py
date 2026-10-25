"""Offline voice-model selection — no heavy imports.

Kept separate from listener.py so it can be unit-tested anywhere.

Priority: big Indian English first (most accurate for Indian
accents), then small Indian English, then US English as fallback.
AURA uses whichever model folder is present in ``models/`` —
installing a model is just dropping its folder in next to the
others. Note the big model needs a few GB of free RAM and answers
a little slower; on a low-RAM PC, prefer the small Indian model.
"""

import os

_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models",
)

MODEL_CANDIDATES = [
    os.path.join(_MODELS_DIR, "vosk-model-en-in-0.5"),
    os.path.join(_MODELS_DIR, "vosk-model-small-en-in-0.4"),
    os.path.join(_MODELS_DIR, "vosk-model-small-en-us-0.15"),
]

# Backwards-compatible name (the first candidate).
MODEL_DIR = MODEL_CANDIDATES[0]


def pick_model_dir(candidates=None):
    """First existing model folder, or None if no model is installed."""
    for folder in candidates or MODEL_CANDIDATES:
        if os.path.isdir(folder):
            return folder
    return None
