"""Tests for accent support (Phase 4.1).

Model selection is pure filesystem logic — no microphone, no Vosk,
no network needed:
    python test_accent.py
"""

import os
import tempfile

from aura.models import pick_model_dir


def main():
    with tempfile.TemporaryDirectory() as tmp:
        en_in_big = os.path.join(tmp, "vosk-model-en-in-0.5")
        en_in = os.path.join(tmp, "vosk-model-small-en-in-0.4")
        en_us = os.path.join(tmp, "vosk-model-small-en-us-0.15")
        candidates = [en_in_big, en_in, en_us]

        # Nothing installed -> None.
        assert pick_model_dir(candidates) is None

        # Only US installed -> US model.
        os.mkdir(en_us)
        assert pick_model_dir(candidates) == en_us

        # Small Indian installed -> Indian model wins (accent priority).
        os.mkdir(en_in)
        assert pick_model_dir(candidates) == en_in

        # Big Indian installed -> big model wins (accuracy priority).
        os.mkdir(en_in_big)
        assert pick_model_dir(candidates) == en_in_big

        # Only big Indian installed -> big model.
        os.rmdir(en_in)
        os.rmdir(en_us)
        assert pick_model_dir(candidates) == en_in_big

    print("All accent/model-selection tests passed.")


if __name__ == "__main__":
    main()
