"""Small accent palette for Research Desk agents.

The app remains charcoal/amber first. These colors are narrow accents for
left rails, status emphasis and compact code chips; they should not dominate
panels or create separate visual themes per agent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPalette:
    """Primary accent plus darker/subdued variants."""
    primary: str
    dark: str
    dim: str


RESEARCH = AgentPalette(primary="#7FA0B0", dark="#3D5661", dim="#5D7C8A")
REVIEW = AgentPalette(primary="#D6C99A", dark="#8A7545", dim="#B0A17F")
BUILD = AgentPalette(primary="#D08F36", dark="#704214", dim="#8A5725")
CURATE = AgentPalette(primary="#8F8F8F", dark="#565656", dim="#6F6F6F")
AUDIT = AgentPalette(primary="#C44535", dark="#7A4535", dim="#9A4D40")


AGENT_COLORS: dict[str, AgentPalette] = {
    "RESEARCH": RESEARCH,
    "REVIEW": REVIEW,
    "BUILD": BUILD,
    "CURATE": CURATE,
    "AUDIT": AUDIT,
}
