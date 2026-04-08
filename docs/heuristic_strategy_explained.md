# EnterpriseHeuristicAgent v9.1 -- Strategy Explained

**A rule-based cyber-defense agent for CAGE Challenge 4**

---

## What Is This?

CAGE Challenge 4 (CC4) is a multi-agent cyber-defense simulation. Five **blue agents**
defend a network of ~50 hosts across 9 subnets against automated **red attackers**,
while **green agents** simulate normal users doing everyday work.

The EnterpriseHeuristicAgent is a hand-crafted, rule-based blue agent that achieves
**-207.68 mean reward per agent** (100 episodes, seed 42) -- outperforming a passive
SleepAgent baseline by **95.3%**.

This document explains *how* it works, *why* each decision was made, and *what* it
sees in the environment.

---

## The Network

The CC4 network has 9 subnets connected through chokepoint servers. Red enters from
the outside (contractor/internet) and tries to reach the mission-critical operational
zones to run Impact attacks.

```
                          +------------------+
                          |    INTERNET      |
                          +--------+---------+
                                   |
                          +--------+---------+
                          |   CONTRACTOR     |
                          |   NETWORK        |
                          +--------+---------+
                                   |
                    +--------------+--------------+
                    |                             |
           +-------+--------+           +--------+-------+
           | RESTRICTED     |           | RESTRICTED     |
           | ZONE A (RZA)   |           | ZONE B (RZB)   |
           | Chokepoint:    |           | Chokepoint:    |
           | server_host_0  |           | server_host_0  |
           +-------+--------+           +--------+-------+
                   |                             |
           +-------+--------+           +--------+-------+
           | OPERATIONAL    |           | OPERATIONAL    |
           | ZONE A (OZA)   |           | ZONE B (OZB)   |
           | Impact target: |           | Impact target: |
           | server_host_0  |           | server_host_0  |
           +----------------+           +----------------+

           +----------------+    +-------+    +----------+
           |  HQ / ADMIN    |----| PAZ   |----|  OFFICE  |
           |  NETWORK       |    +-------+    +----------+
           +----------------+
```

### Which Blue Agent Guards What?

```
  Agent 0  -->  Restricted Zone A  (RZA)     -- the gateway to OZA
  Agent 1  -->  Operational Zone A (OZA)     -- Phase 1 Impact target
  Agent 2  -->  Restricted Zone B  (RZB)     -- the gateway to OZB
  Agent 3  -->  Operational Zone B (OZB)     -- Phase 2 Impact target
  Agent 4  -->  HQ + PAZ + Admin + Office    -- largest zone, 3x the hosts
```

Each agent can **only act on hosts in its assigned subnets** -- it cannot help
defend other agents' hosts directly. Agents communicate via 8-bit messages.

---

## The Three Mission Phases

The 500-step episode is divided into three phases. The phase determines which
hosts are mission-critical (highest penalty for compromise) and which network
paths should be blocked.

```
  Step:     1              167             334              500
            |--- Phase 0 ---|--- Phase 1 ---|--- Phase 2 ---|
            |  Preplanning  |   Mission A   |   Mission B   |
            |               |               |               |
  Critical: | (all equal)   | OZA (-10/evt) | OZB (-10/evt) |
  Isolated: | (nothing)     | RZA isolated  | RZB isolated  |
  Upstream: | RZA->OZA      | RZA->OZA      | RZB->OZB      |
            |               | RZB->OZB      |               |
```

### What "Isolated" Means

In Phase 1, the network policy says RZA should be cut off from outside traffic.
In Phase 2, RZB is cut off instead. The blue agent enforces these blocks by
issuing `BlockTrafficZone` actions. **Blocking is free** -- no reward cost --
and it **stops red exploits** from crossing subnet boundaries.

---

## How Red Attacks

Red uses a Finite State Machine (FSM) to progress through hosts. Each host
is tracked independently through these states:

```
  K -----> KD -----> S -----> SD -----> U -----> UD -----> R -----> RD
  Known    Known+    Scanned  Scanned+  User     User+    Root     Root+
           Decoys             Decoys    Shell    Decoys   Session  Decoys

  K  = Just discovered this host exists
  KD = K, but also detected decoys on it
  S  = Scanned for services (knows what's running)
  SD = S, but also detected decoys
  U  = Has a user-level shell (can run commands)
  UD = U, but also detected decoys
  R  = Has root access (can run Impact)
  RD = R, but also detected decoys
```

### The "D" Suffix -- Decoy Awareness

The "D" suffix means red has run `DiscoverDeception` on the host and learned
which processes are decoys. In a "D" state, red uses `PIDSelectiveExploitActionSelector`
to avoid known decoy PIDs, **bypassing the 75% trap rate**.

### Attack Chain Timing

```
                           FASTEST PATH TO IMPACT
  +--------------------------------------------------------------------------+
  |                                                                          |
  |  Starting host (already U):                                              |
  |    Step 1-2: PrivilegeEscalate (2 steps) --> Root                        |
  |    Step 3-4: Impact (2 steps) --> DAMAGE DONE                            |
  |    Total: 4 steps                                                        |
  |                                                                          |
  |  New host from scratch:                                                  |
  |    Step 1:   DiscoverRemoteServices (1 step, invisible to blue)          |
  |    Step 2:   DiscoverNetworkServices (1 step, invisible to blue)         |
  |    Step 3-6: ExploitRemoteService (4 steps, 95% visible to blue)         |
  |    Step 7-8: PrivilegeEscalate (2 steps, invisible without malfile)      |
  |    Step 9-10: Impact (2 steps, invisible to blue)                        |
  |    Total: 10 steps minimum                                               |
  |                                                                          |
  +--------------------------------------------------------------------------+
```

### What Blue Can and Cannot See

```
  +----------------------+------------------+----------------------------------+
  | Red Action           | Duration (steps) | Blue Observation                 |
  +----------------------+------------------+----------------------------------+
  | DiscoverRemote       | 1                | INVISIBLE                        |
  | DiscoverNetwork      | 1                | INVISIBLE                        |
  | DiscoverDeception    | 2                | INVISIBLE                        |
  | ExploitRemoteService | 4                | 95% proc_flag, always conn_flag  |
  |                      |                  | Always drops malfile (cmd.exe)   |
  | PrivilegeEscalate    | 2                | INVISIBLE (only malfile flag)    |
  | Impact               | 2                | INVISIBLE                        |
  | DegradeServices      | ?                | INVISIBLE                        |
  +----------------------+------------------+----------------------------------+
```

Key insight: **Blue's main detection signal is ExploitRemoteService** (95% process
creation event + 100% connection event + 100% malfile drop). Everything after that
is invisible unless you have BlueFlatWrapperV2's malfile detection.

---

## How Decoys Work

Decoys are fake vulnerable services deployed on hosts. They act as traps for red.

```
                        HOW DECOYS TRAP RED

     Red selects a process to exploit (random from available PIDs)
                              |
                    +---------+---------+
                    |                   |
              Hits real service    Hits decoy
                    |                   |
              Exploit succeeds    Exploit FAILS
              Session created     No session
              conn=1, malfile=1   conn=1, malfile=0
              proc=1 (95%)        proc=0
                    |                   |
              REAL THREAT          DECOY HIT
              Blue: Restore        Blue: Skip!
                                   (decoy did its job)
```

### Decoy Types Available

| Decoy Type | Port | Catches Which Exploits |
|------------|------|------------------------|
| Apache     | 80   | HTTPRFI (trap-only!)   |
| Tomcat     | 443  | EternalBlue variants   |
| Haraka     | 25   | HarakaRCE (trap-only!) |
| Vsftpd     | 80   | FTP exploits           |

**Critical discovery**: HTTPRFI and HarakaRCE exploits **only succeed against decoys**.
Real Apache processes lack the `rfi` vulnerability, and real SMTP has patched Haraka.
These exploits are pure traps -- they waste 4 red steps every time.

### The 75% Rule

With 3 decoys + 1 real service on a host, red picks randomly from 4 PIDs.
**75% of the time, red hits a decoy and wastes 4 steps with zero progress.**

```
  Host with 3 decoys:
  +------+------+------+------+
  | Real | Decoy| Decoy| Decoy|
  | Svc  |  #1  |  #2  |  #3  |
  +------+------+------+------+
     25%    25%    25%    25%
     |       |      |      |
   Success  FAIL   FAIL   FAIL
             \      |      /
              \     |     /
           75% chance of failure!
           Red wastes 4 steps each time.
```

### Decoy Deployment Priority

The agent deploys decoys in this order (most critical first):

```
  Priority 0:  OZB server_host_0  (Phase 2 Impact target)
  Priority 1:  OZA server_host_0  (Phase 1 Impact target)
  Priority 2-3: Other OZ servers
  Priority 4-5: RZ servers (chokepoints -- red must pass through)
  Priority 6-7: Other servers
  Priority 8-11: User hosts in mission zones
  Priority 20: Everything else
```

---

## The Priority System

The agent uses a **strict priority queue** -- it evaluates conditions from
Priority 1 (most urgent) down to Priority 8 (Sleep), and takes the first
action that matches.

```
  +----------+--------------------+------------------------------------------+
  | Priority | Action             | Trigger Condition                        |
  +----------+--------------------+------------------------------------------+
  |    1     | RESTORE            | conn + (malfile OR proc) = confirmed red |
  |    1b    | RESTORE            | conn-only + no decoy = suspicious        |
  |    1c    | RESTORE            | pure malfile = PrivilegeEscalate         |
  |    2     | ALLOW traffic      | Policy says unblock, but still blocked   |
  |    3     | BLOCK traffic      | Policy says block, but not yet blocked   |
  |    4     | REMOVE / RESTORE   | proc_flag only (may be green FP)         |
  |    5     | RESTORE            | Persistent proc_flag, no Remove tried    |
  |    6     | REDEPLOY decoys    | Restore wiped decoys, re-arm them        |
  |    7     | DEPLOY decoys      | Initial setup, fill all hosts            |
  |    8     | SLEEP              | Nothing to do                            |
  +----------+--------------------+------------------------------------------+
```

### Priority 1 -- Confirmed Red (Immediate Restore)

```
  conn_flag = 1  AND  (malfile = 1  OR  proc_flag = 1)
       |                    |                |
       |              cmd.exe dropped    process event
       |              (100% on exploit)  (95% on exploit)
       |
  Network connection
  logged by exploit
       |
       v
  CONFIRMED RED SESSION --> RESTORE immediately
  (Remove can't evict root, and we don't know if red has escalated)
```

Why Restore instead of Remove? **Remove only kills user-level sessions.**
If red has already run PrivilegeEscalate (invisible!), the root session
survives Remove. Restore reimages the host completely -- guaranteed clean.

### Priority 1b -- Connection-Only Events

```
  conn_flag = 1  AND  malfile = 0  AND  proc_flag = 0
       |
       +-- Decoy deployed on this host?
       |       |
       |      YES ---------> Is upstream reporting DECOYS_BYPASSED?
       |                         |              |
       |                        YES            NO
       |                         |              |
       |                     RESTORE        SKIP (decoy hit,
       |                     (red knows       no real threat)
       |                      our decoys!)
       |
       +-- NO decoy deployed --> RESTORE (unknown source, be safe)
```

This is the **decoy-hit detection** logic. When a decoy catches an exploit,
it produces a connection event but NO malfile and NO process event. If we
have decoys deployed, a conn-only signal is almost certainly a decoy hit --
the decoy is working! Skip the expensive Restore.

### Priority 1c -- Pure Malfile (PrivilegeEscalate Detection)

```
  malfile = 1  AND  proc = 0  AND  conn = 0
       |
  PrivilegeEscalate drops escalate.exe (density=0.9, unsigned)
  but fires NO process or connection events.
       |
  This is the ONLY way to detect PrivEsc without it being too late.
       |
       v
  ROOT SESSION PRESENT --> RESTORE immediately
  (Remove cannot evict root sessions)
```

This detection is **only available with BlueFlatWrapperV2**. Without the
malfile flags, PrivilegeEscalate is completely invisible.

### Priority 2 & 3 -- Firewall Management

```
  Phase 1 Example:
  +-----------------+     BLOCK      +-----------------+
  |  Contractor     | ----X----->    | Restricted      |
  |  Network        |               | Zone A          |
  +-----------------+               +-----------------+
                                          |
  +-----------------+     BLOCK           |
  |  Internet       | ----X------>        |
  +-----------------+                     |
                                    +-----+-----+
                                    | ALREADY   |
                                    | BLOCKED   |
                                    | by policy |
                                    +-----------+

  Priority 2 (ALLOW): Fix stale blocks that policy says should be open
  Priority 3 (BLOCK): Enforce new blocks that policy requires

  Blocking order (by source subnet priority):
    Phase 1: RZA (250) > Contractor/Internet (200) > others (10)
    Phase 2: RZB (250) > Contractor/Internet (200) > RZA (50) > others (10)
```

**Why RZA/RZB first?** By the time a phase transition happens, red may
already be inside RZA/RZB. The most critical block is cutting the
RZ-to-OZ path to protect the mission-critical Impact target.

### Priority 4 -- Process Flags (The Tricky One)

Process flags have a **33-54% false positive rate** from green agents doing
normal work. The agent uses a 2-tier escalation strategy:

```
  proc_flag = 1 (no conn, no malfile)
       |
       +-- Already tried Remove on this host?
       |       |
       |      YES --> Flag still present after Remove duration?
       |                   |
       |                  YES --> ROOT SESSION (survived Remove)
       |                          --> RESTORE
       |
       +-- Check peer messages from upstream agent:
       |
       |   Tier 3 (threshold = 0):
       |     upstream_red_count >= 3
       |     "Upstream zone is saturated with red"
       |     --> RESTORE IMMEDIATELY (skip Remove entirely)
       |
       |   Default (threshold = 1):
       |     flag_age >= 1 step
       |     "Flag persisted -- probably real, not green FP"
       |     --> RESTORE
       |
       |   flag_age = 0 (just appeared):
       |     --> REMOVE first (cheap, 3 steps, no cost)
       |         If flag persists --> Priority 4 fires again --> Restore
```

### Priority 6 & 7 -- Decoy Deployment

```
  Priority 6: REDEPLOY after Restore
  +------------------+          +------------------+
  | Host restored    |  ------> | Decoys wiped!    |
  | (clean state)    |          | Need to redeploy |
  +------------------+          +------------------+
                                        |
                                  Deploy in priority
                                  order (OT targets
                                  first)

  Priority 7: INITIAL DEPLOY
  +------------------+
  | No alerts active |  ------> Deploy decoys on all
  | Nothing to do    |          hosts (up to 3 each)
  +------------------+          instead of sleeping
```

The agent **never deploys on a host that is mid-Remove or mid-Restore**
(the `_busy()` guard). Deploying during a Restore would waste the action
because the Restore wipes the host clean at completion.

---

## Inter-Agent Messaging

Blue agents communicate using an 8-bit message sent every step. Each agent
receives messages from 4 peers (all agents except itself).

```
  8-BIT MESSAGE FORMAT
  +---+---+---+---+---+---+---+---+
  | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
  +---+---+---+---+---+---+---+---+
  |THREAT |OPEN   |RED    |BYP|RST|
  |LEVEL  |PATHS  |COUNT  |   |   |
  | 2-bit | 2-bit | 2-bit |1b |1b |
  +-------+-------+-------+---+---+

  THREAT_LEVEL (0-3):
    0 = clean (no red activity)
    1 = decoy hit (red probing but trapped)
    2 = user session (red has a foothold)
    3 = root session (red has full control)

  OPEN_PATHS (0-3):
    Count of subnet paths that policy says to block but aren't yet.
    0 = fully locked down. 3+ = multiple holes in the firewall.

  RED_HOST_COUNT (0-3):
    How many hosts have confirmed red presence.
    3+ = zone is being overrun.

  DECOYS_BYPASSED (0/1):
    Red learned which processes are decoys (via DiscoverDeception)
    and then successfully exploited a real service. The 75% trap
    rate is compromised on this agent's hosts.

  RESTORING (0/1):
    At least one Restore is currently in progress in this zone.
```

### How Messages Drive Decisions

```
                      UPSTREAM AGENT
                    (e.g., Agent 0 / RZA)
                           |
                    Sends message:
                    threat=3, red_count=3
                           |
                           v
                    DOWNSTREAM AGENT
                    (e.g., Agent 1 / OZA)
                           |
              +------------+------------+
              |                         |
       red_count >= 3              threat >= 2
       (T3 escalation)            (T2 escalation)
              |                         |
       threshold = 0              threshold = 1
       RESTORE immediately        RESTORE if flag
       on ANY proc_flag           persists 1+ step
              |                         |
       "Upstream is overrun,     "Red is advancing,
        don't waste time          be more aggressive
        with Remove"              with escalation"
```

### The Upstream Mapping

```
  Phase 1:  Agent 0 (RZA) ----upstream-of----> Agent 1 (OZA)
            Red enters RZA first, then pivots to OZA.
            If RZA is compromised, OZA is next.

  Phase 2:  Agent 2 (RZB) ----upstream-of----> Agent 3 (OZB)
            Same pattern for Zone B.
```

---

## Reward Structure

There are **no positive rewards** in CC4. The score starts at 0 and can only
go down. The goal is to minimize losses.

```
  REWARD SOURCES
  +-------------------------------+------------+
  | Source                        | Cost       |
  +-------------------------------+------------+
  | Red Impact on OZ (mission)   | -10 / step |
  | Red Impact on RZ             | -1 / step  |
  | Green service failure (LWF)  | -1 to -10  |
  | Green access failure (ASF)   | -1 to -10  |
  | Blue Restore action          | -1 (once)  |
  | Blue Remove action           | 0 (free!)  |
  | Blue BlockTrafficZone        | 0 (free!)  |
  | Blue Sleep / Monitor         | 0          |
  +-------------------------------+------------+
```

### The Key Trade-off

```
  Cost of a FALSE POSITIVE Restore:
    -1 (action cost) + decoy redeployment time
    ~= -1 to -6 total

  Cost of a MISSED Impact on OZ during mission:
    -10 per step x multiple steps
    = -20 to -100+

  CONCLUSION: Always err on the side of Restoring.
  A false alarm costs ~6. A missed attack costs 50+.
```

---

## Performance

| Version | Mean Reward/Agent | Std Dev | vs SleepAgent | Episodes |
|---------|-------------------|---------|---------------|----------|
| v7      | -221              | +/-102  | 96.6%         | 100x500  |
| v9      | -214              | +/-74   | 96.7%         | 100x500  |
| **v9.1**| **-207.68**       |**+/-110**| **95.3%**    | 100x500  |

Best single episode: **-370.0** (-74 per agent)

### Why the Ceiling Exists

The v9.1 agent is at or near the **Pareto frontier for rule-based strategies**.
12 improvement strategies were systematically tested; all either matched baseline
or caused regressions. The remaining gap is dominated by:

```
  +----------------------------------------+------------------+
  | Fundamental Constraint                 | % of Losses      |
  +----------------------------------------+------------------+
  | Phase 0 uncontested red activity       | 58%              |
  | (no blocking available in preplanning) |                  |
  +----------------------------------------+------------------+
  | Green false positives                  | 33-54%           |
  | (indistinguishable from real red)      | of all Removes   |
  +----------------------------------------+------------------+
  | Invisible red actions                  | ~5%              |
  | (Impact, PrivEsc timing windows)       |                  |
  +----------------------------------------+------------------+
```

These constraints require **learned approaches** (RL) to overcome -- a heuristic
cannot statistically distinguish green false positives from real red activity,
and the Phase 0 comms policy prevents blocking before missions begin.

---

## Quick Reference: Decision Flowchart

```
                              START
                                |
                         Read observation
                                |
                    +--------- ANY ALERTS? ---------+
                    |                               |
                   YES                             NO
                    |                               |
              +-----+-----+                   Deploy decoys
              |           |                   or Sleep
              |           |
        conn + malfile?  proc only?
        conn + proc?         |
              |         Remove first,
         RESTORE        then Restore
         immediately    if it persists
              |
        conn only?
              |
        +-----+-----+
        |           |
     Decoys      No decoys
     deployed?   deployed?
        |           |
     SKIP        RESTORE
     (decoy hit)  (unknown)
```

---

## Files

| File | Purpose |
|------|---------|
| `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgent.py` | The agent implementation |
| `CybORG/Agents/Wrappers/BlueFlatWrapperV2.py` | Extended wrapper with malfile flags |
| `CybORG/Evaluation/submission/submission.py` | Official evaluation submission adapter |
| `scripts/evaluate_heuristic.py` | Quick evaluation script |
| `scripts/evaluate_instrumented.py` | Instrumented eval with per-priority tracking |
| `docs/v9_messaging_protocol.md` | Full messaging protocol specification |
| `docs/v9_1_changes.md` | v9.1 change log |
| `docs/optimal_heuristic_strategy.md` | Comprehensive strategy analysis report |
