"""Experiment 1: Messaging ablation -- disable all messaging.

Sends all-zeros message every step. Ignores all incoming messages.
This isolates the TRUE value of messaging in V10b.
"""
from __future__ import annotations
import numpy as np
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
)


class EnterpriseHeuristicAgentV10b_Exp1(EnterpriseHeuristicAgentV10b):
    """V10b with messaging completely disabled."""

    def _read_peer_messages(self, obs, msg_start, phase):
        """Always return default (no-threat) peer state."""
        return {
            "any_real_red": False,
            "any_root": False,
            "upstream_threat": 0,
            "upstream_open_paths": 0,
            "upstream_red_count": 0,
            "upstream_decoys_bypassed": False,
            "upstream_restoring": False,
            "max_peer_red_count": 0,
        }

    def get_action(self, observation, action_mask=None):
        """Override to always send zeros message."""
        idx, _ = super().get_action(observation, action_mask)
        return idx, np.zeros(8, dtype=bool)


def make_heuristic_agents_exp1(env):
    """Create Exp1 agents (no messaging)."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Exp1(agent_name=agent_name)
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
