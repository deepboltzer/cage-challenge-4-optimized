"""Parameterized V10b variants for priority ordering and threshold experiments.

Each variant is a full copy of V10b's get_action with specific modifications,
controlled by config dict passed at construction time.

Config keys:
  - p4_threshold: int or 'tiered' or 'default'
      int: use this threshold for ALL hosts
      'tiered': 0 for OZ/RZ, 2 for HQ/admin/office
      'default': original V10b logic (peer-escalation + OZ server_host_0 special case)
  - p1b_placement: 'default' | 'after_p3' | 'removed'
  - block_before_allow: bool (False = default P2-Allow/P3-Block; True = swap)
  - host_priority_override: None or dict mapping zone substrings to priorities
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    _SORTED_SUBNETS, NUM_SUBNETS, NUM_MSG_BITS,
    _OFF_BLOCKED, _OFF_COMMS, _OFF_PROC, RESTORE_DUR, MAX_DECOYS,
    _MSG_LEN, _NUM_BLUE_AGENTS, _UPSTREAM,
    _BIT_THREAT_LO, _BIT_THREAT_HI, _BIT_OPEN_PATHS_LO, _BIT_OPEN_PATHS_HI,
    _BIT_RED_COUNT_LO, _BIT_RED_COUNT_HI, _BIT_DECOYS_BYPASSED, _BIT_RESTORING,
    _is_active_oz_server, _sorted_by_priority, _deploy_priority, _pair_priority,
    EnterpriseHeuristicAgentV10b,
)


def _host_priority_custom(hostname: str, phase: int,
                          overrides: Optional[dict] = None) -> int:
    """Host priority with optional zone overrides."""
    if overrides:
        for zone_str, prio in overrides.items():
            if zone_str in hostname:
                # Phase-aware: boost active OZ
                if phase == 1 and "operational_zone_a" in hostname:
                    return max(prio, 100)
                if phase == 2 and "operational_zone_b" in hostname:
                    return max(prio, 100)
                return prio

    # Default V10b logic
    if phase == 1:
        if "operational_zone_a" in hostname: return 100
        if "restricted_zone_a" in hostname: return 70
        if "operational_zone_b" in hostname: return 40
    elif phase == 2:
        if "operational_zone_b" in hostname: return 100
        if "restricted_zone_b" in hostname: return 70
        if "operational_zone_a" in hostname: return 40
    elif phase == 0:
        if "operational_zone_b" in hostname: return 40
        if "operational_zone_a" in hostname: return 40
        if "restricted_zone_b" in hostname: return 30
        if "restricted_zone_a" in hostname: return 30
    if any(s in hostname for s in ("admin_network", "office_network", "public_access")):
        return 50
    return 20


def _sorted_by_priority_custom(hosts: dict, phase: int,
                                overrides: Optional[dict] = None) -> list[str]:
    return sorted(hosts,
                  key=lambda h: _host_priority_custom(h, phase, overrides),
                  reverse=True)


class ConfigurableAgentV10b(EnterpriseHeuristicAgentV10b):
    """V10b with configurable priority ordering and thresholds."""

    def __init__(self, agent_name: str = "blue_agent_0", config: Optional[dict] = None):
        super().__init__(agent_name)
        self.config = config or {}

    def get_action(self, observation, action_mask=None):
        if not self._labels:
            return 0, np.zeros(8, dtype=bool)

        self._step += 1
        obs = np.asarray(observation, dtype=np.float32)
        mask = action_mask
        cfg = self.config

        host_prio_overrides = cfg.get("host_priority_override", None)

        # -- Detect malfile section
        n_malfile_hosts = sum(
            len(self._subnet_host_list.get(sn, []))
            for sn in self._subnets_in_obs
        )
        base_subnet_len = sum(
            27 + 2 * len(self._subnet_host_list.get(sn, []))
            for sn in self._subnets_in_obs
        )
        expected_base_len = 1 + base_subnet_len + NUM_MSG_BITS
        has_malfile = (n_malfile_hosts > 0 and
                       len(obs) == expected_base_len + n_malfile_hosts)
        malfile_start = expected_base_len if has_malfile else len(obs)

        # -- Parse per-subnet obs
        phase = int(obs[0])
        conn_alerts = {}
        proc_alerts = {}
        malfile_alerts = {}
        blocked_now = {}
        should_block = {}

        base = 1
        malfile_cursor = malfile_start
        for sn in self._subnets_in_obs:
            hosts = self._subnet_host_list.get(sn, [])
            n_hosts = len(hosts)
            off_conn = _OFF_PROC + n_hosts

            blocked_vec = obs[base + _OFF_BLOCKED: base + _OFF_COMMS]
            comms_policy_vec = obs[base + _OFF_COMMS: base + _OFF_PROC]
            proc_flags = obs[base + _OFF_PROC: base + off_conn]
            conn_flags = obs[base + off_conn: base + off_conn + n_hosts]

            if has_malfile:
                malfile_vec = obs[malfile_cursor: malfile_cursor + n_hosts]
                malfile_cursor += n_hosts
            else:
                malfile_vec = []

            for i, src in enumerate(_SORTED_SUBNETS):
                if src == sn:
                    continue
                pair = (src, sn)
                blocked_now[pair] = bool(blocked_vec[i])
                should_block[pair] = bool(comms_policy_vec[i])

            for hi, hostname in enumerate(hosts):
                if conn_flags[hi]:
                    conn_alerts[hostname] = True
                if proc_flags[hi]:
                    proc_alerts[hostname] = True
                if has_malfile and hi < len(malfile_vec) and malfile_vec[hi]:
                    malfile_alerts[hostname] = True

            base += 27 + 2 * n_hosts

        # -- Update process-flag tracker
        for h in list(self._proc_flagged_step.keys()):
            if h not in proc_alerts:
                del self._proc_flagged_step[h]
        for h in proc_alerts:
            if h not in self._proc_flagged_step:
                self._proc_flagged_step[h] = self._step

        # -- Derived alert sets
        real_red_hosts = {h for h in conn_alerts
                         if malfile_alerts.get(h) or proc_alerts.get(h)}
        real_red_hosts.update(malfile_alerts)
        real_red_hosts.update(proc_alerts)

        root_indicators = {
            h for h in malfile_alerts
            if h not in conn_alerts and h not in proc_alerts
        }

        # -- Read peer messages
        peer_state = self._read_peer_messages(obs, base, phase)

        # -- Track decoy-hit history
        for h in conn_alerts:
            if (not malfile_alerts.get(h) and not proc_alerts.get(h)
                    and self._decoy_deployed.get(h, 0) > 0):
                self._decoy_hit_hosts.add(h)
        decoys_bypassed = any(
            h in self._decoy_hit_hosts
            for h in real_red_hosts
            if self._decoy_deployed.get(h, 0) > 0
        )

        # -- Compute open comms paths and red host counts
        open_paths_count = sum(
            1 for p in should_block
            if should_block[p] and not blocked_now.get(p, False)
        )
        open_paths_enc = min(open_paths_count, 3)
        red_count_enc = min(len(real_red_hosts), 3)

        # -- Build outbound message
        msg = np.zeros(8, dtype=bool)

        if root_indicators:
            out_threat = 3
        elif real_red_hosts:
            out_threat = 2
        elif any(
            conn_alerts.get(h) and not malfile_alerts.get(h)
            and not proc_alerts.get(h) and self._decoy_deployed.get(h, 0) > 0
            for h in conn_alerts
        ):
            out_threat = 1
        else:
            out_threat = 0
        msg[_BIT_THREAT_LO] = bool(out_threat & 1)
        msg[_BIT_THREAT_HI] = bool((out_threat >> 1) & 1)
        msg[_BIT_OPEN_PATHS_LO] = bool(open_paths_enc & 1)
        msg[_BIT_OPEN_PATHS_HI] = bool((open_paths_enc >> 1) & 1)
        msg[_BIT_RED_COUNT_LO] = bool(red_count_enc & 1)
        msg[_BIT_RED_COUNT_HI] = bool((red_count_enc >> 1) & 1)
        msg[_BIT_DECOYS_BYPASSED] = decoys_bypassed
        msg[_BIT_RESTORING] = any(
            self._step <= self._restore_at[h] + RESTORE_DUR - 1
            for h in self._restore_at
        )

        # ================================================================
        # PRIORITY DISPATCH — configurable ordering
        # ================================================================

        sort_fn = (lambda hosts: _sorted_by_priority_custom(hosts, phase, host_prio_overrides)
                   if host_prio_overrides
                   else _sorted_by_priority(hosts, phase))

        # -- P1: Restore on confirmed red (conn + malfile/proc) — always first
        for hostname in sort_fn(conn_alerts):
            if not (malfile_alerts.get(hostname) or proc_alerts.get(hostname)):
                continue
            if self._busy(hostname):
                continue
            idx = self._restore.get(hostname)
            if idx is not None and self._valid(idx, mask):
                self._issue_restore(hostname)
                return idx, msg

        # -- P1b: Restore on conn-only without decoy coverage
        p1b_placement = cfg.get("p1b_placement", "default")

        if p1b_placement == "default":
            act = self._try_p1b(conn_alerts, malfile_alerts, proc_alerts,
                                peer_state, mask, msg, sort_fn)
            if act is not None:
                return act

        # -- P1c: Restore on pure malfile (PrivEsc signature)
        for hostname in sort_fn(malfile_alerts):
            if hostname in conn_alerts or hostname in proc_alerts:
                continue
            if self._busy(hostname):
                continue
            idx = self._restore.get(hostname)
            if idx is not None and self._valid(idx, mask):
                self._issue_restore(hostname)
                return idx, msg

        # -- P2/P3: Allow and Block (configurable order)
        block_first = cfg.get("block_before_allow", False)

        if block_first:
            act = self._try_block(should_block, blocked_now, mask, msg, phase)
            if act is not None:
                return act
            act = self._try_allow(should_block, blocked_now, mask, msg, phase)
            if act is not None:
                return act
        else:
            act = self._try_allow(should_block, blocked_now, mask, msg, phase)
            if act is not None:
                return act
            act = self._try_block(should_block, blocked_now, mask, msg, phase)
            if act is not None:
                return act

        # -- P1b after P3 (if configured)
        if p1b_placement == "after_p3":
            act = self._try_p1b(conn_alerts, malfile_alerts, proc_alerts,
                                peer_state, mask, msg, sort_fn)
            if act is not None:
                return act

        # -- P4: Restore on process flags (configurable threshold)
        p4_threshold_cfg = cfg.get("p4_threshold", "default")

        for hostname in sort_fn(proc_alerts):
            if self._busy(hostname):
                continue

            flag_age = self._step - self._proc_flagged_step.get(hostname, self._step)

            if p4_threshold_cfg == "default":
                # Original V10b logic
                peer_escalate_t3 = peer_state.get("upstream_red_count", 0) >= 3
                peer_escalate_t2 = (
                    peer_state.get("any_root", False)
                    or peer_state.get("upstream_threat", 0) >= 2
                )
                peer_escalate_compound = (
                    peer_state.get("upstream_threat", 0) >= 1
                    and peer_state.get("upstream_open_paths", 0) > 0
                    and peer_state.get("upstream_decoys_bypassed", False)
                )
                is_critical_oz = _is_active_oz_server(hostname, phase)

                if peer_escalate_t3 or is_critical_oz:
                    threshold = 0
                elif peer_escalate_t2 or peer_escalate_compound:
                    threshold = 1
                else:
                    threshold = 1
            elif p4_threshold_cfg == "tiered":
                if any(s in hostname for s in ("operational_zone", "restricted_zone")):
                    threshold = 0
                else:
                    threshold = 2
            else:
                threshold = int(p4_threshold_cfg)

            if flag_age >= threshold:
                idx = self._restore.get(hostname)
                if idx is not None and self._valid(idx, mask):
                    self._issue_restore(hostname)
                    return idx, msg

        # -- P6: Re-deploy decoys after Restore
        for hostname in self._deploy_hosts:
            rs = self._restore_at.get(hostname, -1)
            if rs >= 0 and self._step >= rs + RESTORE_DUR:
                if (self._decoy_deployed.get(hostname, 0) < MAX_DECOYS
                        and hostname in self._decoy):
                    idx = self._decoy[hostname]
                    if self._valid(idx, mask):
                        self._decoy_deployed[hostname] = \
                            self._decoy_deployed.get(hostname, 0) + 1
                        return idx, msg

        # -- P7: Deploy decoys
        for hostname in self._deploy_hosts:
            if self._busy(hostname):
                continue
            if (self._decoy_deployed.get(hostname, 0) < MAX_DECOYS
                    and hostname in self._decoy):
                idx = self._decoy[hostname]
                if self._valid(idx, mask):
                    self._decoy_deployed[hostname] = \
                        self._decoy_deployed.get(hostname, 0) + 1
                    return idx, msg

        # -- Fallback: Sleep
        return self._sleep_idx, msg

    # -- Sub-priority helpers ------------------------------------------------

    def _try_p1b(self, conn_alerts, malfile_alerts, proc_alerts,
                 peer_state, mask, msg, sort_fn):
        """P1b: Restore on conn-only without decoy coverage. Returns (idx, msg) or None."""
        upstream_decoys_compromised = peer_state.get("upstream_decoys_bypassed", False)
        for hostname in sort_fn(conn_alerts):
            if malfile_alerts.get(hostname) or proc_alerts.get(hostname):
                continue
            if (self._decoy_deployed.get(hostname, 0) > 0
                    and not upstream_decoys_compromised):
                continue
            if self._busy(hostname):
                continue
            idx = self._restore.get(hostname)
            if idx is not None and self._valid(idx, mask):
                self._issue_restore(hostname)
                return idx, msg
        return None

    def _try_allow(self, should_block, blocked_now, mask, msg, phase):
        """P2: Allow paths per comms_policy."""
        for pair, is_allowed in sorted(
            should_block.items(),
            key=lambda kv: _pair_priority(kv[0], phase)
        ):
            if not is_allowed and blocked_now.get(pair, False):
                idx = self._allow.get(pair)
                if idx is not None and self._valid(idx, mask):
                    return idx, msg
        return None

    def _try_block(self, should_block, blocked_now, mask, msg, phase):
        """P3: Block paths per comms_policy."""
        for pair, should_be_blocked in sorted(
            should_block.items(),
            key=lambda kv: _pair_priority(kv[0], phase),
            reverse=True
        ):
            if should_be_blocked and not blocked_now.get(pair, False):
                idx = self._block.get(pair)
                if idx is not None and self._valid(idx, mask):
                    return idx, msg
        return None


def make_configurable_agents(env, config: dict):
    """Factory: create ConfigurableAgentV10b agents with given config."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = ConfigurableAgentV10b(agent_name=agent_name, config=config)
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
