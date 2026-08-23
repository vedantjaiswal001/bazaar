"""Reproducible benchmark datasets.

Development set and a separately-seeded HELD-OUT set of fresh, unseen instances.
Because the gate is deterministic it cannot "overfit" — the held-out result is
reported anyway, as the strongest honest signal that the numbers are real.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from bazaar.crypto.signing import generate_keypair
from bazaar.redteam.attacks import Case, generate_adversarial, generate_legitimate


@dataclass
class Datasets:
    dev: list[Case]
    held_out: list[Case]


def build(dev_seed: int = 1, held_out_seed: int = 9973,
          per_class: int = 16, legit_n: int = 400) -> Datasets:
    # One signing key per split; every mandate in the split is validly signed.
    dev_rng = random.Random(dev_seed)
    dsk, dpk = generate_keypair()
    dev = generate_adversarial(dev_rng, dsk, dpk, per_class=per_class) + \
        generate_legitimate(dev_rng, dsk, dpk, n=legit_n)

    ho_rng = random.Random(held_out_seed)
    hsk, hpk = generate_keypair()
    held = generate_adversarial(ho_rng, hsk, hpk, per_class=max(4, per_class // 2)) + \
        generate_legitimate(ho_rng, hsk, hpk, n=legit_n // 2)

    return Datasets(dev=dev, held_out=held)
