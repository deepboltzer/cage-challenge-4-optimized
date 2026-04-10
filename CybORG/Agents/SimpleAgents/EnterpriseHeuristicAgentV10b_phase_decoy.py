"""V10b variant with phase-aware decoy deployment order.

Experiment 2: Instead of static OZB->OZA->RZB->RZA order, dynamically
reorder deployment based on current mission phase:
  - Phase 0: Both OZ equally prioritized, then RZ equally
  - Phase 1: OZA first (active target), then OZB, then RZA, RZB
  - Phase 2: OZB first (active target), then OZA, then RZB, RZA
"""
from __future__ import annotations

from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
    _deploy_priority,
    MAX_DECOYS,
    RESTORE_DUR,
    _sorted_by_priority,
    _is_active_oz_server,
    _pair_priority,
    _host_priority,
    _SORTED_SUBNETS,
    _SUBNET_IDX,
    NUM_SUBNETS,
    MAX_HOSTS,
    NUM_MSG_BITS,
    _OFF_BLOCKED,
    _OFF_COMMS,
    _OFF_PROC,
    _MSG_LEN,
    _NUM_BLUE_AGENTS,
)
import numpy as np
from typing import Optional


def _phase_aware_deploy_priority(hostname: str, phase: int) -> int:
    """Deploy priority that changes with mission phase."""
    if phase == 1:
        # Phase 1: OZA is active target, prioritize it
        if "operational_zone_a" in hostname and "server_host_0" in hostname: return 0
        if "operational_zone_a" in hostname and "server" in hostname: return 1
        if "operational_zone_b" in hostname and "server_host_0" in hostname: return 2
        if "operational_zone_b" in hostname and "server" in hostname: return 3
        if "restricted_zone_a" in hostname and "server" in hostname: return 4
        if "restricted_zone_b" in hostname and "server" in hostname: return 5
    elif phase == 2:
        # Phase 2: OZB is active target, prioritize it
        if "operational_zone_b" in hostname and "server_host_0" in hostname: return 0
        if "operational_zone_b" in hostname and "server" in hostname: return 1
        if "operational_zone_a" in hostname and "server_host_0" in hostname: return 2
        if "operational_zone_a" in hostname and "server" in hostname: return 3
        if "restricted_zone_b" in hostname and "server" in hostname: return 4
        if "restricted_zone_a" in hostname and "server" in hostname: return 5
    else:
        # Phase 0: Both OZ equally prioritized
        if "operational_zone_b" in hostname and "server_host_0" in hostname: return 0
        if "operational_zone_a" in hostname and "server_host_0" in hostname: return 1
        if "operational_zone_b" in hostname and "server" in hostname: return 2
        if "operational_zone_a" in hostname and "server" in hostname: return 3
        if "restricted_zone_b" in hostname and "server" in hostname: return 4
        if "restricted_zone_a" in hostname and "server" in hostname: return 5

    if "server_host_0" in hostname: return 6
    if "server" in hostname: return 7
    if "operational_zone" in hostname: return 8
    if "restricted_zone" in hostname: return 10
    return 20


class EnterpriseHeuristicAgentV10b_PhaseDecoy(EnterpriseHeuristicAgentV10b):
    """V10b with phase-aware decoy deployment ordering."""

    def get_action(self, observation, action_mask=None):
        if not self._labels:
            return 0, np.zeros(8, dtype=bool)

        self._step += 1
        obs = np.asarray(observation, dtype=np.float32)
        mask = action_mask
        phase = int(obs[0])

        # Re-sort deploy_hosts based on current phase
        self._deploy_hosts = sorted(
            self._deploy_hosts,
            key=lambda h: _phase_aware_deploy_priority(h, phase)
        )

        # Now run parent logic but we need to decrement step since parent increments
        self._step -= 1
        return super().get_action(observation, action_mask)


def make_heuristic_agents_phase_decoy(env):
    """Create V10b agents with phase-aware decoy deployment."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_PhaseDecoy(agent_name=agent_name)
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
