"""Experiment 3: Expand upstream map.

V10b only has 2 upstream entries:
  (1, 1) -> 0  (Phase 1: OZA watches RZA)
  (2, 3) -> 2  (Phase 2: OZB watches RZB)

This experiment adds:
  Phase 0: All agents watch agent_4 (HQ/admin -- red enters here first)
  Phase 1: agent_4 watches agent_0 (HQ watches RZA for early warning)
  Phase 2: agent_4 watches agent_2 (HQ watches RZB for early warning)
  All phases: agent_0 watches agent_4, agent_2 watches agent_4
    (RZ agents watch HQ for initial red entry signals)
"""
from __future__ import annotations
import numpy as np
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
    _UPSTREAM,
)


_EXPANDED_UPSTREAM = {
    # Phase 0: RZ agents watch HQ (red enters through contractor/HQ)
    (0, 0): 4,  # RZA watches HQ
    (0, 1): 4,  # OZA watches HQ
    (0, 2): 4,  # RZB watches HQ
    (0, 3): 4,  # OZB watches HQ
    # Phase 1: original + HQ watches RZA
    (1, 1): 0,  # OZA watches RZA (original)
    (1, 4): 0,  # HQ watches RZA (new: early warning)
    (1, 0): 4,  # RZA watches HQ (red may still be in HQ)
    # Phase 2: original + HQ watches RZB
    (2, 3): 2,  # OZB watches RZB (original)
    (2, 4): 2,  # HQ watches RZB (new: early warning)
    (2, 2): 4,  # RZB watches HQ (red may still be in HQ)
}


class EnterpriseHeuristicAgentV10b_Exp3(EnterpriseHeuristicAgentV10b):
    """V10b with expanded upstream relationships."""

    def _read_peer_messages(self, obs, msg_start, phase):
        """Parse messages with expanded upstream map."""
        from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
            NUM_MSG_BITS, _NUM_BLUE_AGENTS, _MSG_LEN,
            _BIT_THREAT_LO, _BIT_THREAT_HI,
            _BIT_OPEN_PATHS_LO, _BIT_OPEN_PATHS_HI,
            _BIT_RED_COUNT_LO, _BIT_RED_COUNT_HI,
            _BIT_DECOYS_BYPASSED, _BIT_RESTORING,
        )
        msg_section = obs[msg_start : msg_start + NUM_MSG_BITS]

        try:
            own_idx = int(self.agent_name.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return {
                "any_real_red": False, "any_root": False,
                "upstream_threat": 0, "upstream_open_paths": 0,
                "upstream_red_count": 0, "upstream_decoys_bypassed": False,
                "upstream_restoring": False, "max_peer_red_count": 0,
            }

        peer_indices = [i for i in range(_NUM_BLUE_AGENTS) if i != own_idx]
        upstream_idx = _EXPANDED_UPSTREAM.get((phase, own_idx))

        any_real_red             = False
        any_root                 = False
        upstream_threat          = 0
        upstream_open_paths      = 0
        upstream_red_count       = 0
        upstream_decoys_bypassed = False
        upstream_restoring       = False
        max_peer_red_count       = 0

        for slot, peer_idx in enumerate(peer_indices):
            slot_start = slot * _MSG_LEN
            if slot_start + _MSG_LEN > len(msg_section):
                break
            pmsg = msg_section[slot_start : slot_start + _MSG_LEN]

            threat_level = (int(pmsg[_BIT_THREAT_HI]) << 1) | int(pmsg[_BIT_THREAT_LO])
            open_paths   = (int(pmsg[_BIT_OPEN_PATHS_HI]) << 1) | int(pmsg[_BIT_OPEN_PATHS_LO])
            red_count    = (int(pmsg[_BIT_RED_COUNT_HI]) << 1) | int(pmsg[_BIT_RED_COUNT_LO])
            decoys_byp   = bool(pmsg[_BIT_DECOYS_BYPASSED])
            restoring    = bool(pmsg[_BIT_RESTORING])

            if threat_level >= 2:
                any_real_red = True
            if threat_level == 3:
                any_root = True
            if red_count > max_peer_red_count:
                max_peer_red_count = red_count

            if peer_idx == upstream_idx:
                upstream_threat          = threat_level
                upstream_open_paths      = open_paths
                upstream_red_count       = red_count
                upstream_decoys_bypassed = decoys_byp
                upstream_restoring       = restoring

        return {
            "any_real_red":             any_real_red,
            "any_root":                 any_root,
            "upstream_threat":          upstream_threat,
            "upstream_open_paths":      upstream_open_paths,
            "upstream_red_count":       upstream_red_count,
            "upstream_decoys_bypassed": upstream_decoys_bypassed,
            "upstream_restoring":       upstream_restoring,
            "max_peer_red_count":       max_peer_red_count,
        }


def make_heuristic_agents_exp3(env):
    """Create Exp3 agents (expanded upstream map)."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_Exp3(agent_name=agent_name)
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
