"""Experiment 2: Fix dead code -- make T2/compound escalation threshold=0.

In V10b, T2 and compound escalation both set threshold=1, same as default.
This experiment changes them to threshold=0 (immediate Restore), making
peer escalation actually meaningful for more conditions.

Implementation: override _read_peer_messages to map T2 conditions into
the T3 bucket (upstream_red_count=3), so the parent's T3 check fires.
This avoids duplicating 250+ lines of get_action.
"""
from __future__ import annotations
import numpy as np
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
)


class EnterpriseHeuristicAgentV10b_Exp2(EnterpriseHeuristicAgentV10b):
    """V10b with T2/compound escalation promoted to threshold=0."""

    def _read_peer_messages(self, obs, msg_start, phase):
        """Parse messages normally, then promote T2/compound to T3."""
        state = super()._read_peer_messages(obs, msg_start, phase)

        # T2 conditions: any_root OR upstream_threat >= 2
        t2 = (
            state.get("any_root", False)
            or state.get("upstream_threat", 0) >= 2
        )
        # Compound: upstream_threat >= 1 AND open_paths > 0 AND decoys_bypassed
        compound = (
            state.get("upstream_threat", 0) >= 1
            and state.get("upstream_open_paths", 0) > 0
            and state.get("upstream_decoys_bypassed", False)
        )

        # If T2 or compound, escalate upstream_red_count to 3 to trigger T3
        if t2 or compound:
            state["upstream_red_count"] = max(state["upstream_red_count"], 3)

        return state


def make_heuristic_agents_exp2(env):
    """Create Exp2 agents (aggressive escalation)."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Exp2(agent_name=agent_name)
        try:
            ag.set_action_info(
                env.action_labels(agent_name),
                env.action_mask(agent_name),
                subnet_hosts,
            )
        except Exception:
            pass
        agents[agent_name] = ag
    return agents
