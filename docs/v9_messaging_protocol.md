# v9 Inter-Agent Messaging Protocol — EnterpriseHeuristicAgent

**Applies to:** `EnterpriseHeuristicAgent` v9+  
**File:** `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgent.py`  
**Supersedes:** v8 protocol (25% bit utilisation, 6 of 8 bits partially or fully redundant)

---

## The problem this solves

In CAGE Challenge 4, five blue agents defend a segmented enterprise network against a
single red attacker that moves from zone to zone. Each agent only sees the subnets it
controls — agent_0 watches Restricted Zone A, agent_1 watches Operational Zone A, and
so on. This means each agent is working with **incomplete information**: it cannot see
what is happening in zones it does not own.

```
  CC4 Network — Blue agent assignments
  ══════════════════════════════════════════════════════════════════

   [ Contractor ]  [ Internet ]        External entry points
        │                │             (PhishingEmail bypasses firewall)
        └───────┬─────────┘
                ▼
   ┌────────────────────────┐   ┌────────────────────────┐
   │  Restricted Zone A     │   │  Restricted Zone B     │
   │  (RZA)  agent_0 👁     │   │  (RZB)  agent_2 👁     │
   │  servers + user hosts  │   │  servers + user hosts  │
   └──────────┬─────────────┘   └──────────┬─────────────┘
              │  red pivots here            │  red pivots here
              ▼  (Phase 1)                  ▼  (Phase 2)
   ┌────────────────────────┐   ┌────────────────────────┐
   │  Operational Zone A    │   │  Operational Zone B    │
   │  (OZA)  agent_1 👁  ★  │   │  (OZB)  agent_3 👁  ★  │
   │  OTService  ← TARGET   │   │  OTService  ← TARGET   │
   └────────────────────────┘   └────────────────────────┘

   ┌───────────────────────────────────────┐
   │  HQ Network          agent_4 👁        │
   │  Admin + Office + Public Access Zone  │
   └───────────────────────────────────────┘

   ★ = red's Impact target   👁 = blue agent's visibility boundary

   Each agent sees ONLY its own zone. Zones to the left/right are blind spots.
```

The environment already provides a communication channel: every step, each agent can
broadcast 8 bits to its four peers. Those 8 bits arrive in the peer's observation
vector alongside everything else the peer sees. The question is what to put in those
8 bits and what to do with them when received.

Before v9, the agents were effectively **deaf and mute in practice**:
- The evaluation script discarded the message return value and never forwarded it to
  the environment, so every agent broadcast all-zeros regardless of what the code computed.
- Even if messages had been forwarded, the receiving code path did not exist — agents
  read their observation but never parsed the 32-bit message section.
- The v8 bit design also wasted half the available bandwidth on redundant flags
  (two bits that could each be derived from another bit in the same message).

v9 fixes all three problems.

## Why it matters — a concrete example

Red in CC4 must travel through Restricted Zone A before reaching Operational Zone A
(the high-value Impact target in Phase 1). Agent_0 watches RZA; agent_1 watches OZA.
Without messaging, agent_1 has no warning that red is advancing through RZA until red
actually arrives in OZA. By then red may already have a root session, and agent_1's
default strategy of issuing `Remove` first (3 steps) then waiting to see if the flag
clears (2 more steps) means **5 steps of inaction** before a `Restore` is triggered.

With v9 messaging, agent_0 broadcasts its `THREAT_LEVEL` and `RED_HOST_COUNT` every
step. When agent_1 sees that its upstream peer (agent_0) has `RED_HOST_COUNT = 3`
(three hosts compromised in RZA), it immediately skips `Remove` and issues `Restore`
on the first process flag it receives — red is clearly past the decoy layer and
advancing fast. This is the **T3 escalation** described below.

```
  Phase 1 attack timeline — WITHOUT messaging (v8 / broken)
  ──────────────────────────────────────────────────────────
  Step  Red action           agent_0 sees        agent_1 sees
   10   exploit RZA host_1   conn+malfile ⚠       (nothing)
   11   exploit RZA host_2   conn+malfile ⚠       (nothing)
   12   exploit RZA host_3   conn+malfile ⚠       (nothing)
   13   pivot → OZA          (nothing)             conn+malfile ⚠
   14   PrivEsc OZA server   (nothing)             malfile only ⚠
   15   n/a                  (nothing)             agent_1 issues Remove ← 3 steps
   16   n/a                  (nothing)             Remove in progress
   17   n/a                  (nothing)             Remove done; flag gone?
   18   Impact OTService     (nothing)             malfile back → now Restore ← TOO LATE

  Phase 1 attack timeline — WITH messaging (v9)
  ──────────────────────────────────────────────────────────
  Step  Red action           agent_0 broadcasts   agent_1 receives & acts
   10   exploit RZA host_1   THREAT=2 COUNT=1      (threshold still default=2)
   11   exploit RZA host_2   THREAT=2 COUNT=2      (threshold lowers to 1)
   12   exploit RZA host_3   THREAT=3 COUNT=3 ←    threshold drops to 0 (T3!)
   13   pivot → OZA          THREAT=3 COUNT=3      first proc_flag → Restore immediately ✓
   14   PrivEsc OZA server   THREAT=3 COUNT=3      Restore in progress (blocks Impact)
```

## What each bit communicates

Think of the 8-bit message as a compact status report that an agent sends to its
colleagues every step:

```
  One agent's 8-bit outbound message (sent every step)
  ═════════════════════════════════════════════════════

  Bit  7        6             5   4         3   2         1   0
  ┌─────────┬──────────────┬───────────────┬───────────────────┐
  │RESTORING│DECOYS_BYPASS │  RED_HOST_COUNT  │    OPEN_PATHS  │   THREAT_LEVEL   │
  │  (bool) │   (bool)     │   (2 bits)    │   (2 bits)    │   (2 bits)    │
  └─────────┴──────────────┴───────────────┴───────────────────┘
       │           │               │               │               │
       │           │               │               │               └─ 00=clean
       │           │               │               │                  01=decoy hit
       │           │               │               │                  10=user session
       │           │               │               │                  11=root session
       │           │               │               │
       │           │               │               └─ 00=all blocked (fully safe)
       │           │               │                  01=1 path open
       │           │               │                  10=2 paths open
       │           │               │                  11=3+ paths open (danger)
       │           │               │
       │           │               └─ 00=no hosts compromised
       │           │                  01=1 host
       │           │                  10=2 hosts
       │           │                  11=3+ hosts (T3 escalation triggers)
       │           │
       │           └─ 1 = red ran DiscoverDeception in my zone;
       │                    decoy PIDs are known, decoys no longer effective
       │
       └─ 1 = a Restore action is currently running in my zone
```

- **"How bad is it in my zone right now?"** — `THREAT_LEVEL`: clean / decoy hit /
  real exploit / root session. Two bits, four states.
- **"Is my firewall fully configured?"** — `OPEN_PATHS`: how many required
  communication paths I haven't blocked yet. Zero means fully locked down.
- **"How many hosts has red touched?"** — `RED_HOST_COUNT`: a count of compromised
  hosts. Saturates at 3 so it fits in two bits.
- **"Have red's decoys been bypassed?"** — `DECOYS_BYPASSED`: red ran
  `DiscoverDeception` and now knows which processes are fake. Decoys in my zone are
  no longer effective.
- **"Am I busy restoring right now?"** — `RESTORING`: at least one host in my zone is
  being reimaged. My capacity to handle new alerts is reduced.

Every bit is information a peer cannot see from its own observation. Nothing is
duplicated. This is why v9 achieves 100% utilisation where v8 achieved 25%.

## How the heuristic agent uses incoming messages

The agent's decision logic has two places where peer messages change behaviour:

**1. Should I skip Restore on a connection-only alert?**  
When a host gets a network connection event but no malware file and no process event,
it is almost certainly a decoy hit (red hit a fake service and wasted 4 steps). The
agent normally skips `Restore` in this case to save the 5-step cost.  
But if the upstream peer has set `DECOYS_BYPASSED`, red may be using PID knowledge
from the adjacent zone to avoid decoys entirely. In that case the agent stops skipping
Restore and treats the conn-only alert as a real threat.

```
  Decoy-hit decision: should I Restore or ignore?
  ════════════════════════════════════════════════

  Observation: conn_flag=1, malfile=0, proc_flag=0   (connection but no malware)

                        Is a decoy deployed on this host?
                               /            \
                             YES             NO
                              │               │
                              ▼               ▼
          Did upstream peer report         Restore
          DECOYS_BYPASSED = 1?            (unknown source,
               /       \                   play it safe)
             YES         NO
              │           │
              ▼           ▼
           Restore      Skip Restore
        (real threat —  (decoy hit —
         PID intel       red wasted
         leaked from     4 steps,
         adj. zone)      no session)
```

**2. How quickly should I escalate from Remove to Restore?**  
When a host shows a process flag, the default flow is: issue `Remove` first (cheap,
3 steps, clears user sessions), then wait to see if the flag reappears (root session
survived). The waiting time before escalating to `Restore` is controlled by a
threshold. Peer messages tighten that threshold based on urgency:

| What peers are saying | Threshold | Effect |
|-----------------------|-----------|--------|
| Upstream has 3+ compromised hosts | 0 steps | Restore immediately — no Remove at all |
| Upstream has root sessions or real exploits | 1 step | Restore if flag persists one step |
| Upstream has activity + open paths + decoys bypassed | 1 step | Same — compound advance signal |
| Nothing alarming | 2 steps | Normal flow |

```
  Remove → Restore escalation decision tree
  ══════════════════════════════════════════

  proc_flag detected on a host
           │
           ▼
   upstream_red_count >= 3?
      YES ──────────────────────────────► Restore immediately  (T3)
      │                                   (zone saturated, no time for Remove)
      NO
      │
      ▼
   any_root  OR  upstream_threat >= 2?
      YES ──────────────────────────────► flag_age threshold = 1  (T2a)
      │                                   (root/exploit in upstream zone)
      NO
      │
      ▼
   upstream_threat >= 1  AND
   upstream_open_paths > 0  AND
   upstream_decoys_bypassed?
      YES ──────────────────────────────► flag_age threshold = 1  (T2b)
      │                                   (red advancing through misconfigured,
      │                                    decoy-blind upstream zone)
      NO
      │
      ▼
   Default threshold = 2  ────────────► Remove first, wait 2 steps, then Restore

  ─────────────────────────────────────────────────────────────────
  threshold = 0 → skip Remove entirely, Restore on step 0
  threshold = 1 → Remove first, Restore if flag reappears after 1 step
  threshold = 2 → Remove first, Restore if flag reappears after 2 steps
```

---

## Overview

CC4 provides a 32-bit inter-agent communication channel: each of the 5 blue agents
broadcasts an 8-bit message per step; each agent receives the 4 messages from its
peers in ascending agent-index order (excluding self). The channel is wired through
`BlueFlatWrapperV2` and carried in the observation vector at
`obs[base : base+32]` where `base = 1 + sum(27 + 2*n_hosts_i)`.

The v9 protocol redesigns the 8 outgoing bits from scratch to achieve **zero
redundancy and 100% bit utilisation**: every bit encodes independent information
that a peer cannot infer from its own observation.

```
  Message flow — every step, all 5 agents broadcast simultaneously
  ════════════════════════════════════════════════════════════════

   agent_0 (RZA) ──msg[0]──┐                    ┌── msg[0] ──► agent_1 (OZA)
                             │                    │
   agent_1 (OZA) ──msg[1]──┤                    ├── msg[1] ──► agent_2 (RZB)
                             │                    │
   agent_2 (RZB) ──msg[2]──┼─── environment ────┼── msg[2] ──► agent_3 (OZB)
                             │  (BlueFlatWrapper) │
   agent_3 (OZB) ──msg[3]──┤                    ├── msg[3] ──► agent_4 (HQ)
                             │                    │
   agent_4 (HQ)  ──msg[4]──┘                    └── msg[4] ──► agent_0 (RZA)

   Each agent receives the 4 messages from all peers, ordered by agent index
   (self excluded). Slots of isolated agents are zero-padded.

  Observation vector layout (BlueFlatWrapperV2)
  ─────────────────────────────────────────────
  ┌───────┬──────────────────────────────┬──────────────┬────────────────┐
  │ phase │  per-subnet blocks           │ messages     │ malfile flags  │
  │ (1)   │  (27 + 2*n_hosts each)       │ (4 × 8 = 32) │ (sum n_hosts)  │
  └───────┴──────────────────────────────┴──────────────┴────────────────┘
   obs[0]  obs[1 .. base-1]               obs[base..     obs[base+32 ..]
                                           base+31]
```

---

## Bit Layout

```
Bit  7   6   5   4   3   2   1   0
     |   |   |   |   |   |   |   |
     R   D   C1  C0  P1  P0  T1  T0
```

| Bits | Name              | Encoding | Meaning |
|------|-------------------|----------|---------|
| 0–1  | `THREAT_LEVEL`    | 2-bit unsigned | Worst active threat in sender's zone |
| 2–3  | `OPEN_PATHS`      | 2-bit unsigned | Unblocked required comms paths in sender's zone |
| 4–5  | `RED_HOST_COUNT`  | 2-bit unsigned | Hosts with confirmed red presence |
| 6    | `DECOYS_BYPASSED` | 1-bit boolean  | Red has PID knowledge of sender's decoys |
| 7    | `RESTORING`       | 1-bit boolean  | At least one Restore in progress |

### THREAT_LEVEL encoding (bits 0–1)

| Value | Meaning |
|-------|---------|
| `00` (0) | Clean — no red signals this step |
| `01` (1) | Decoy hit — conn-only, decoy deployed, no malfile |
| `10` (2) | User session — confirmed real exploit (conn + malfile or proc) |
| `11` (3) | Root session — PrivEsc signature (malfile-only) or proc survived Remove |

### OPEN_PATHS encoding (bits 2–3)

Count of required comms pairs in `comms_policy` that are not yet blocked,
saturating at 3.

| Value | Meaning |
|-------|---------|
| `00` (0) | All required paths blocked — firewall fully configured |
| `01` (1) | One path still open |
| `10` (2) | Two paths still open |
| `11` (3) | Three or more paths open — critical misconfiguration |

### RED_HOST_COUNT encoding (bits 4–5)

Count of hosts in sender's zone with any confirmed red presence (`conn+malfile`,
`proc`, or `malfile`-only), saturating at 3.

| Value | Meaning |
|-------|---------|
| `00` (0) | No compromised hosts |
| `01` (1) | One host compromised |
| `10` (2) | Two hosts compromised |
| `11` (3) | Three or more hosts compromised |

---

## Why v8 Was Suboptimal (25% Utilisation)

The v8 protocol allocated 8 named bits as single flags:

```
  v8 bit layout — before redesign
  ─────────────────────────────────────────────────────────────────────
  Bit 7   6      5        4           3           2         1       0
  ┌──────┬──────┬─────────┬───────────┬───────────┬─────────┬───────┐
  │THREAT│THREAT│ EVICTED │DECOYS_DONE│BLOCKS_DONE│RESTORE_ │ROOT_  │REAL_
  │ _HI  │ _LO  │         │           │           │ BUSY    │SUSP   │RED
  └──────┴──────┴─────────┴───────────┴───────────┴─────────┴───────┘
    kept   kept   REMOVED    REMOVED     REPLACED    kept    REMOVED  REMOVED

  ✗ REAL_RED    = (THREAT_HI | THREAT_LO) != 00  → derivable from same message
  ✗ ROOT_SUSP   = THREAT == 11             → derivable from same message
  ✗ DECOYS_DONE = receiver-local state     → peer cannot act on it
  ✗ EVICTED     = one-step transient flag  → receiver sees the gap anyway
  ✓ RESTORE_BUSY → preserved as RESTORING (bit 7)
  ✓ BLOCKS_DONE  → inverted and expanded to OPEN_PATHS 2-bit field
  ✓ THREAT_HI/LO → retained, promoted to primary field

  v8 effective bandwidth: 2 useful bits out of 8 = 25%

  v9 bit layout — after redesign (zero redundancy)
  ─────────────────────────────────────────────────────────────────────
  Bit 7      6              5    4          3    2          1    0
  ┌──────────┬──────────────┬──────────────┬──────────────┬──────────┐
  │RESTORING │DECOYS_BYPASS │  RED_HOST_   │   OPEN_      │ THREAT_  │
  │          │              │    COUNT     │   PATHS      │  LEVEL   │
  │  1 bit   │    1 bit     │   2 bits     │   2 bits     │  2 bits  │
  └──────────┴──────────────┴──────────────┴──────────────┴──────────┘
   cross-zone  cross-zone    cross-zone      cross-zone     cross-zone
   state       state         state           state          state

  v9 effective bandwidth: 8 useful bits out of 8 = 100%
  Freed 4 bits used for: OPEN_PATHS (2 bits) + RED_HOST_COUNT (2 bits)
```

Bits 0, 1, 4, 5 were either redundant, unactionable, or too transient to matter.
The 4 bits freed by removing them were reused for `OPEN_PATHS` (2 bits) and
`RED_HOST_COUNT` (2 bits), both of which carry cross-subnet state that receivers
cannot observe directly.

---

## How Receivers Use the Messages

### Priority 1b — conn-only Restore skip condition

When a conn-only hit (no malfile, no proc) occurs on a host with a deployed decoy,
the default is to skip Restore (likely a decoy hit). The skip is suppressed when the
upstream peer reports `DECOYS_BYPASSED=1`: red may have PID knowledge from the
adjacent zone and may be selectively targeting real services.

```python
upstream_decoys_compromised = peer_state.get("upstream_decoys_bypassed", False)
if (self._decoy_deployed.get(hostname, 0) > 0
        and not upstream_decoys_compromised):
    continue  # decoy hit — skip Restore
```

### Priority 4 — 3-tier escalation threshold

The flag-age threshold controlling when the agent escalates from `Remove` to
`Restore` is dynamically adjusted based on peer messages:

| Tier | Condition | Threshold | Behaviour |
|------|-----------|-----------|-----------|
| T3 | `upstream_red_count >= 3` | `0` | Direct Restore on first proc_flag |
| T2a | `any_root OR upstream_threat >= 2` | `1` | Restore if flag persists ≥ 1 step |
| T2b | `upstream_threat >= 1 AND open_paths > 0 AND decoys_bypassed` | `1` | Compound: red advancing through open/bypassed zone |
| Default | none of the above | `2` | Normal Remove-first flow |

```python
if upstream_red_count >= 3:
    threshold = 0          # T3: saturated zone, skip Remove entirely
elif any_root or upstream_threat >= 2:
    threshold = 1          # T2a: root or user session in upstream zone
elif upstream_threat >= 1 and open_paths > 0 and decoys_bypassed:
    threshold = 1          # T2b: compound advance signal
else:
    threshold = 2          # default
```

### Upstream agent mapping

The `_UPSTREAM` dict defines which peer is "upstream" for each agent in each phase:

```python
_UPSTREAM = {
    (1, 1): 0,   # Phase 1: RZA (agent_0) upstream of OZA (agent_1)
    (2, 3): 2,   # Phase 2: RZB (agent_2) upstream of OZB (agent_3)
}
```

Only `upstream_*` fields apply directional logic. `any_real_red` and `any_root`
aggregate across all peers and trigger escalation regardless of source.

---

## Isolation Behaviour

Once Phase 1 blocks are applied, OZA (agent_1) is fully network-isolated from all
other subnets. Its message slot in peer observations becomes all-zeros (padded by
`BlueFlatWrapperV2`). The receiver treats all-zeros as "clean/no-threat" — a safe
default since an isolated OZA cannot see cross-zone data anyway.

The same applies to OZB (agent_3) in Phase 2.

The slot-shift risk (CybORG skips the isolated agent's slot, shifting subsequent
indices) is currently benign because the only agents with `_UPSTREAM` entries
(agent_1 and agent_3) are the ones being isolated, and their slots arrive as
all-zeros regardless of the shift.

---

## Implementation Files

| File | Change |
|------|--------|
| `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgent.py` | v9 bit constants, message encoding, `_read_peer_messages()`, Priority 1b, Priority 4 escalation, `reset()` |
| `CybORG/Agents/Wrappers/BlueFlatWrapper.py` | Padding fix: `(messages_raw + [EMPTY_MESSAGE]*N)[:N]` prevents crash when isolated agents reduce message count |
| `scripts/evaluate_heuristic.py` | Message forwarding fix: capture `msg` from `get_action()` and pass `messages=` to `env.step()` |
