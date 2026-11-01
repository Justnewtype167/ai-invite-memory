"""Data types shared by the persona derivations (M16)."""

from __future__ import annotations

from dataclasses import dataclass

MODE_VALUES = ("support", "banter", "consult", "complaint")
RISK_VALUES = ("low", "medium", "high")
ORIGIN_USER = "user"
ORIGIN_APPROVED_PROPOSAL = "approved_proposal"
TRAIT_TARGET = "self.trait"
TRAIT_ON = "trait"
TRAIT_OFF = "trait_off"
TRAIT_CAP = 5


@dataclass(frozen=True)
class TraitDef:
    """One vocabulary entry: what a trait means and when it is allowed."""

    name: str
    guidance: str
    conflicts: tuple[str, ...]
    modes: tuple[str, ...]
    risk: str


@dataclass(frozen=True)
class TraitActivation:
    """One authorized enable or disable, with its evidence id."""

    name: str
    event_id: str
    order_id: str
    origin: str
    enabled: bool


@dataclass(frozen=True)
class ActiveTrait:
    """One trait that is active after conflict and mode resolution."""

    name: str
    guidance: str
    risk: str
    event_id: str
    origin: str


@dataclass(frozen=True)
class Conflict:
    """One explicit conflict resolution between two traits."""

    winner: str
    loser: str
    reason: str
    winner_event: str
    loser_event: str


@dataclass(frozen=True)
class TraitResolution:
    """The active traits, the resolved conflicts and the readable reasons."""

    active: tuple[ActiveTrait, ...]
    conflicts: tuple[Conflict, ...]
    reasons: tuple[str, ...]

    def conflicts_md(self) -> str:
        """Render the ``### Conflicts`` section for ``PersonaView.self_md``."""
        lines = ["### Conflicts"]
        if not self.conflicts:
            lines.append("- none")
            return "\n".join(lines)
        for item in self.conflicts:
            lines.append(
                f"- {item.winner} beats {item.loser}: {item.reason} "
                f"({item.winner} {item.winner_event}, {item.loser} {item.loser_event})"
            )
        return "\n".join(lines)
