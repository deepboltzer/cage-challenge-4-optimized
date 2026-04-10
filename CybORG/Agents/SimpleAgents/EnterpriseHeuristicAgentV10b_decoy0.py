"""V10b variant with MAX_DECOYS=0 (no decoys at all) for ablation study."""
from __future__ import annotations
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
)

MAX_DECOYS_OVERRIDE = 0


class EnterpriseHeuristicAgentV10b_Decoy0(EnterpriseHeuristicAgentV10b):
    """V10b with MAX_DECOYS=0: all decoy deployment disabled."""

    def get_action(self, observation, action_mask=None):
        # Temporarily override MAX_DECOYS
        import CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b as mod
        original = mod.MAX_DECOYS
        mod.MAX_DECOYS = MAX_DECOYS_OVERRIDE
        try:
            return super().get_action(observation, action_mask)
        finally:
            mod.MAX_DECOYS = original


def make_heuristic_agents_decoy0(env):
    """Create V10b agents with MAX_DECOYS=0."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Decoy0(agent_name=agent_name)
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
