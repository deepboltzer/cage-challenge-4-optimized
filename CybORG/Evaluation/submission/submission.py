"""Official CC4 submission -- EnterpriseHeuristicAgent v9.

Compatible with CybORG/Evaluation/evaluation.py interface.
Uses BlueFlatWrapperV2 for observations (adds malicious-file flags) and
action masks.

v9 improvements over v7:
  - Inter-agent messaging: zero-redundancy 8-bit protocol (THREAT_LEVEL, OPEN_PATHS,
    RED_HOST_COUNT, DECOYS_BYPASSED, RESTORING)
  - Upstream peer escalation: proc-flag Remove→Restore threshold dynamically adjusted
    based on peer threat level, red count, and decoy-bypass signals
  - Decoy-bypass suppression: conn-only skip-Restore suppressed when upstream reports
    DECOYS_BYPASSED (red has PID knowledge of decoys)

Note on evaluation.py compatibility: evaluation.py does not pass messages to step().
HeuristicEnv.step() intercepts each call and injects stored outgoing messages so
inter-agent communication works end-to-end within the official evaluation harness.
"""
from __future__ import annotations

import numpy as np

from CybORG import CybORG
from CybORG.Agents import BaseAgent
from CybORG.Agents.Wrappers import BlueFlatWrapperV2
from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgent import EnterpriseHeuristicAgent


class HeuristicSubmissionAgent(BaseAgent):
    """Adapter: wraps EnterpriseHeuristicAgent for the evaluation.py interface.

    The evaluation calls get_action(obs, action_space).  We ignore the
    action_space argument and instead fetch the boolean action mask directly
    from the BlueFlatWrapperV2 stored in self._env.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._inner = EnterpriseHeuristicAgent(agent_name=agent_name)
        self._env: "HeuristicEnv | None" = None
        self._last_message: "np.ndarray | None" = None

    # Called by evaluation.py each step
    def get_action(self, observation, action_space=None):
        mask = None
        if self._env is not None:
            try:
                mask = np.array(self._env.action_mask(self.agent_name), dtype=bool)
            except Exception:
                pass
        action_idx, msg = self._inner.get_action(observation, mask)
        self._last_message = msg  # stored for HeuristicEnv.step() to collect
        return action_idx

    def train(self, *args, **kwargs):
        pass

    def end_episode(self):
        pass

    def set_initial_values(self, *args, **kwargs):
        pass


class HeuristicEnv(BlueFlatWrapperV2):
    """BlueFlatWrapperV2 that reinitialises heuristic agents on each reset().

    Intercepts reset() to call agent.reset() and agent.set_action_info()
    so that per-episode state (decoy tracking, remove/restore timers, etc.)
    is cleared at the start of every episode.
    """

    def __init__(self, env: CybORG, agents: dict[str, HeuristicSubmissionAgent]) -> None:
        super().__init__(env=env)
        self._heuristic_agents = agents
        for agent in agents.values():
            agent._env = self

    def reset(self, **kwargs):
        obs_dict, info = super().reset(**kwargs)
        subnet_hosts = getattr(self, "_cached_subnet_hosts", {})
        for agent_name, agent in self._heuristic_agents.items():
            agent._inner.reset()
            agent._last_message = None
            try:
                agent._inner.set_action_info(
                    self.action_labels(agent_name),
                    self.action_mask(agent_name),
                    subnet_hosts,
                )
            except Exception:
                pass
        return obs_dict, info

    def step(self, actions=None, messages=None, **kwargs):
        """Intercept step() to inject stored outgoing messages.

        evaluation.py does not pass messages, so we collect the _last_message
        stored by each HeuristicSubmissionAgent.get_action() call and forward
        them to the parent step() — enabling full v9 inter-agent messaging.
        """
        if messages is None:
            messages = {}
        for agent_name, agent in self._heuristic_agents.items():
            if agent_name not in messages and agent._last_message is not None:
                messages[agent_name] = agent._last_message
        return super().step(actions=actions, messages=messages, **kwargs)


class Submission:
    # -- Required metadata ----------------------------------------------------
    NAME: str = "EnterpriseHeuristicAgent v9"
    TEAM: str = "CC4-Optimized"
    TECHNIQUE: str = (
        "Rule-based priority heuristic with multi-decoy saturation (MAX_DECOYS=3 on all hosts) "
        "and inter-agent messaging (v9 8-bit protocol: THREAT_LEVEL, OPEN_PATHS, RED_HOST_COUNT, "
        "DECOYS_BYPASSED, RESTORING). Decoy-hit detection via BlueFlatWrapperV2 malfile flags; "
        "upstream peer escalation for Remove-to-Restore threshold; comms-policy-driven firewall management."
    )

    # One agent per blue team member (blue_agent_0 through blue_agent_4)
    AGENTS: dict[str, HeuristicSubmissionAgent] = {
        f"blue_agent_{i}": HeuristicSubmissionAgent(f"blue_agent_{i}") for i in range(5)
    }

    @staticmethod
    def wrap(env: CybORG) -> HeuristicEnv:
        """Wrap CybORG with BlueFlatWrapperV2 + heuristic agent reset logic."""
        return HeuristicEnv(env=env, agents=Submission.AGENTS)
