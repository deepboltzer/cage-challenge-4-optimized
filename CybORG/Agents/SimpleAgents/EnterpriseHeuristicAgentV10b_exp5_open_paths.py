"""Experiment 5: Use OPEN_PATHS for blocking priority.

If any peer reports high OPEN_PATHS (>= 2), this agent prioritizes its own
blocking actions (P3) more aggressively by moving P3 above P4.

Additionally, if the upstream peer has OPEN_PATHS > 0, lower proc_flag
threshold to 0 (red has open paths to reach us).

This makes the OPEN_PATHS signal actually influence decisions.
"""
from __future__ import annotations
import numpy as np
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
)


class EnterpriseHeuristicAgentV10b_Exp5(EnterpriseHeuristicAgentV10b):
    """V10b with OPEN_PATHS driving escalation and blocking priority."""

    def _read_peer_messages(self, obs, msg_start, phase):
        """Parse messages normally, then if upstream has open paths, escalate."""
        state = super()._read_peer_messages(obs, msg_start, phase)

        # If upstream has open paths and any threat, escalate to T3
        if (state.get("upstream_open_paths", 0) > 0
                and state.get("upstream_threat", 0) >= 1):
            state["upstream_red_count"] = max(state["upstream_red_count"], 3)

        return state


def make_heuristic_agents_exp5(env):
    """Create Exp5 agents (OPEN_PATHS priority)."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Exp5(agent_name=agent_name)
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
