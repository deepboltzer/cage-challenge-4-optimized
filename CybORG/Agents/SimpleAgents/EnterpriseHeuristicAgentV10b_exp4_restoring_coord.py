"""Experiment 4: Use RESTORING bit for coordination.

If the upstream peer is Restoring, increase own alert sensitivity:
  - Red may migrate from the upstream zone during Restore
  - Lower proc_flag threshold to 0 (immediate Restore) when upstream restoring

This makes the RESTORING bit actually influence decisions.
"""
from __future__ import annotations
import numpy as np
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
)


class EnterpriseHeuristicAgentV10b_Exp4(EnterpriseHeuristicAgentV10b):
    """V10b with RESTORING bit used to trigger immediate Restore."""

    def _read_peer_messages(self, obs, msg_start, phase):
        """Parse messages normally, then if upstream is restoring, escalate."""
        state = super()._read_peer_messages(obs, msg_start, phase)

        # If upstream is restoring, red may be migrating. Escalate to T3.
        if state.get("upstream_restoring", False):
            state["upstream_red_count"] = max(state["upstream_red_count"], 3)

        return state


def make_heuristic_agents_exp4(env):
    """Create Exp4 agents (RESTORING coordination)."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Exp4(agent_name=agent_name)
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
