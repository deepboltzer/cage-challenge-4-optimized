"""V10b variant with partial post-Restore decoy redeployment.

Experiment 3: After Restore, deploy only 1 decoy (50% trap rate) in P6
then allow other priorities (Restore, block, etc.) to execute. Remaining
decoys deployed in P7 when idle. This improves Restore responsiveness
at the cost of temporarily lower trap rate (50% vs 75%).

Key insight: 1 decoy gives 50% trap rate (vs 75% for 3). But spending
2 fewer steps on redeploy means we can Restore 2 more hosts in that time.
"""
from __future__ import annotations

import re
import numpy as np
from typing import Optional

from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV10b import (
    EnterpriseHeuristicAgentV10b,
    MAX_DECOYS,
    RESTORE_DUR,
    _sorted_by_priority,
    _is_active_oz_server,
    _deploy_priority,
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
    _BIT_THREAT_LO,
    _BIT_THREAT_HI,
    _BIT_OPEN_PATHS_LO,
    _BIT_OPEN_PATHS_HI,
    _BIT_RED_COUNT_LO,
    _BIT_RED_COUNT_HI,
    _BIT_DECOYS_BYPASSED,
    _BIT_RESTORING,
    _AGENT_PRIMARY_SUBNET,
    _UPSTREAM,
)


# After Restore, deploy only this many decoys in P6 (high priority redeploy)
POST_RESTORE_DECOYS = 1


class EnterpriseHeuristicAgentV10b_PartialRedeploy(EnterpriseHeuristicAgentV10b):
    """V10b with partial post-Restore decoy redeployment.

    P6: After Restore completes, deploy only 1 decoy (50% trap) then yield.
    P7: Deploy remaining decoys when no higher-priority action needed.
    """

    def get_action(self, observation, action_mask=None):
        if not self._labels:
            return 0, np.zeros(8, dtype=bool)

        self._step += 1
        obs = np.asarray(observation, dtype=np.float32)
        mask = action_mask

        # Parse observation (same as parent)
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

            blocked_vec = obs[base + _OFF_BLOCKED : base + _OFF_COMMS]
            comms_policy_vec = obs[base + _OFF_COMMS : base + _OFF_PROC]
            proc_flags = obs[base + _OFF_PROC : base + off_conn]
            conn_flags = obs[base + off_conn : base + off_conn + n_hosts]

            if has_malfile:
                malfile_vec = obs[malfile_cursor : malfile_cursor + n_hosts]
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

        # Update proc flag tracker
        for h in list(self._proc_flagged_step.keys()):
            if h not in proc_alerts:
                del self._proc_flagged_step[h]
        for h in proc_alerts:
            if h not in self._proc_flagged_step:
                self._proc_flagged_step[h] = self._step

        real_red_hosts = {h for h in conn_alerts
                         if malfile_alerts.get(h) or proc_alerts.get(h)}
        real_red_hosts.update(malfile_alerts)
        real_red_hosts.update(proc_alerts)

        root_indicators = {
            h for h in malfile_alerts
            if h not in conn_alerts and h not in proc_alerts
        }

        peer_state = self._read_peer_messages(obs, base, phase)

        for h in conn_alerts:
            if (not malfile_alerts.get(h) and not proc_alerts.get(h)
                    and self._decoy_deployed.get(h, 0) > 0):
                self._decoy_hit_hosts.add(h)
        decoys_bypassed = any(
            h in self._decoy_hit_hosts
            for h in real_red_hosts
            if self._decoy_deployed.get(h, 0) > 0
        )

        open_paths_count = sum(
            1 for p in should_block
            if should_block[p] and not blocked_now.get(p, False)
        )
        open_paths_enc = min(open_paths_count, 3)
        red_count_enc = min(len(real_red_hosts), 3)

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

        # P1: Restore on confirmed red
        for hostname in _sorted_by_priority(conn_alerts, phase):
            if not (malfile_alerts.get(hostname) or proc_alerts.get(hostname)):
                continue
            if self._busy(hostname):
                continue
            idx = self._restore.get(hostname)
            if idx is not None and self._valid(idx, mask):
                self._issue_restore(hostname)
                return idx, msg

        # P1b: Restore on conn-only without decoy coverage
        upstream_decoys_compromised = peer_state.get("upstream_decoys_bypassed", False)
        for hostname in _sorted_by_priority(conn_alerts, phase):
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

        # P1c: Restore on pure malfile
        for hostname in _sorted_by_priority(malfile_alerts, phase):
            if hostname in conn_alerts or hostname in proc_alerts:
                continue
            if self._busy(hostname):
                continue
            idx = self._restore.get(hostname)
            if idx is not None and self._valid(idx, mask):
                self._issue_restore(hostname)
                return idx, msg

        # P2: Allow paths per comms_policy
        for pair, is_allowed in sorted(
            should_block.items(),
            key=lambda kv: _pair_priority(kv[0], phase)
        ):
            if not is_allowed and blocked_now.get(pair, False):
                idx = self._allow.get(pair)
                if idx is not None and self._valid(idx, mask):
                    return idx, msg

        # P3: Block paths per comms_policy
        for pair, should_be_blocked in sorted(
            should_block.items(),
            key=lambda kv: _pair_priority(kv[0], phase),
            reverse=True
        ):
            if should_be_blocked and not blocked_now.get(pair, False):
                idx = self._block.get(pair)
                if idx is not None and self._valid(idx, mask):
                    return idx, msg

        # P4: Restore on process flags
        for hostname in _sorted_by_priority(proc_alerts, phase):
            if self._busy(hostname):
                continue
            flag_age = self._step - self._proc_flagged_step.get(hostname, self._step)
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
            if flag_age >= threshold:
                idx = self._restore.get(hostname)
                if idx is not None and self._valid(idx, mask):
                    self._issue_restore(hostname)
                    return idx, msg

        # P6 MODIFIED: Re-deploy only POST_RESTORE_DECOYS (1) after Restore
        for hostname in self._deploy_hosts:
            rs = self._restore_at.get(hostname, -1)
            if rs >= 0 and self._step >= rs + RESTORE_DUR:
                if (self._decoy_deployed.get(hostname, 0) < POST_RESTORE_DECOYS
                        and hostname in self._decoy):
                    idx = self._decoy[hostname]
                    if self._valid(idx, mask):
                        self._decoy_deployed[hostname] = self._decoy_deployed.get(hostname, 0) + 1
                        return idx, msg

        # P7: Deploy remaining decoys (initial + post-restore remainder) when idle
        for hostname in self._deploy_hosts:
            if self._busy(hostname):
                continue
            if self._decoy_deployed.get(hostname, 0) < MAX_DECOYS and hostname in self._decoy:
                idx = self._decoy[hostname]
                if self._valid(idx, mask):
                    self._decoy_deployed[hostname] = self._decoy_deployed.get(hostname, 0) + 1
                    return idx, msg

        # Fallback: Sleep
        return self._sleep_idx, msg


def make_heuristic_agents_partial_redeploy(env):
    """Create V10b agents with partial post-Restore decoy redeploy."""
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    agents = {}
    for agent_name in env.possible_agents:
        ag = EnterpriseHeuristicAgentV10b_PartialRedeploy(agent_name=agent_name)
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
