"""Exact rational acceptance/correction proof for Eaglegate qualification."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

from .contract import EAGLEGATE_ACCEPTANCE_CONTRACT_ID
from .exactness_common import (
    EAGLEGATE_EXACTNESS_CONTRACT_ID,
    EaglegateExactnessError,
    UINT32_MAX,
    canonical_root,
    require_int,
)


def _normalize_distribution(
    name: str,
    distribution: Mapping[int, Fraction | int],
) -> dict[int, Fraction]:
    if not isinstance(distribution, Mapping) or not distribution:
        raise EaglegateExactnessError(f"{name} must be a non-empty mapping")
    result: dict[int, Fraction] = {}
    for token, mass in distribution.items():
        require_int(f"{name} token", token, 0, UINT32_MAX)
        if isinstance(mass, bool) or not isinstance(mass, (Fraction, int)):
            raise EaglegateExactnessError(
                f"{name} masses must be Fraction or int values"
            )
        exact = mass if isinstance(mass, Fraction) else Fraction(mass, 1)
        if exact < 0:
            raise EaglegateExactnessError(f"{name} contains a negative mass")
        result[token] = exact
    if sum(result.values(), Fraction()) != Fraction(1, 1):
        raise EaglegateExactnessError(f"{name} must sum exactly to one")
    return result


def _mass_root(domain: str, distribution: Mapping[int, Fraction]) -> str:
    return canonical_root(
        domain,
        {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "masses": [
                [token, mass.numerator, mass.denominator]
                for token, mass in sorted(distribution.items())
            ],
        },
    )


@dataclass(frozen=True, slots=True)
class LosslessDistributionProof:
    target_mass_root: str
    draft_mass_root: str
    accepted_mass_root: str
    residual_mass_root: str
    output_mass_root: str
    acceptance_mass: Fraction
    rejection_mass: Fraction
    exact: bool

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_id": EAGLEGATE_EXACTNESS_CONTRACT_ID,
            "acceptance_contract_id": EAGLEGATE_ACCEPTANCE_CONTRACT_ID,
            "target_mass_root": self.target_mass_root,
            "draft_mass_root": self.draft_mass_root,
            "accepted_mass_root": self.accepted_mass_root,
            "residual_mass_root": self.residual_mass_root,
            "output_mass_root": self.output_mass_root,
            "acceptance_mass": [
                self.acceptance_mass.numerator,
                self.acceptance_mass.denominator,
            ],
            "rejection_mass": [
                self.rejection_mass.numerator,
                self.rejection_mass.denominator,
            ],
            "exact": self.exact,
        }

    @property
    def proof_root(self) -> str:
        return canonical_root("distribution-proof", self.canonical_dict())


def prove_lossless_one_step_distribution(
    target: Mapping[int, Fraction | int],
    draft: Mapping[int, Fraction | int],
) -> LosslessDistributionProof:
    """Prove exact one-step recovery of target mass without float tolerances."""

    p = _normalize_distribution("target", target)
    q = _normalize_distribution("draft", draft)
    support = sorted(set(p) | set(q))
    zero = Fraction()
    target_mass = {token: p.get(token, zero) for token in support}
    draft_mass = {token: q.get(token, zero) for token in support}
    accepted = {
        token: min(target_mass[token], draft_mass[token]) for token in support
    }
    residual = {
        token: max(target_mass[token] - draft_mass[token], zero)
        for token in support
    }
    output = {
        token: accepted[token] + residual[token] for token in support
    }
    acceptance_mass = sum(accepted.values(), zero)
    rejection_mass = sum(residual.values(), zero)
    exact = (
        output == target_mass
        and acceptance_mass + rejection_mass == Fraction(1, 1)
    )
    if not exact:
        raise EaglegateExactnessError("lossless correction failed exact equality")
    return LosslessDistributionProof(
        target_mass_root=_mass_root("target-mass", target_mass),
        draft_mass_root=_mass_root("draft-mass", draft_mass),
        accepted_mass_root=_mass_root("accepted-mass", accepted),
        residual_mass_root=_mass_root("residual-mass", residual),
        output_mass_root=_mass_root("output-mass", output),
        acceptance_mass=acceptance_mass,
        rejection_mass=rejection_mass,
        exact=True,
    )


__all__ = [
    "LosslessDistributionProof",
    "prove_lossless_one_step_distribution",
]
