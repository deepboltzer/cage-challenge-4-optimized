# CC4 Attack Chain Analysis

## 1. How the Game Works: Two Separate Attack Channels

Red has **two completely different ways** to enter a network. They operate simultaneously and independently:

```
CHANNEL A: Red's own FSM agent (FiniteStateRedAgent)
           -- Uses ExploitRemoteService to move laterally
           -- Blocked by firewalls, stopped by decoys
           -- 95% detectable via process_creation event

CHANNEL B: Green agent's 1% error rate (PhishingEmail)
           -- A GREEN agent accidentally opens a phishing email
           -- Creates a RED session on the Green agent's host
           -- Bypasses ALL firewalls, ALL decoys, ALL detection
           -- Completely silent: no events, no files, no flags
```

Blue only sees Channel A. Channel B is invisible.

---

## 2. The Full Red Attack Chain (Channel A)

The FSM agent maintains 8 internal states per host and transitions between them:

```
Host State Legend:
  K   = Known (discovered IP)
  S   = Scanned (services discovered)
  U   = User session (exploit succeeded)
  R   = Root session (privilege escalated)
  D   = Decoy suffix (e.g. KD = known + decoy detected)
  F   = Failed (blocked/dead end)
```

```
STATE MACHINE -- CHANNEL A (FiniteStateRedAgent)

Internet
  |
  |  DiscoverRemoteSystems (scans subnet)
  v
CONTRACTOR NETWORK  [State: K -> KD]
  |
  |  AggressiveServiceDiscovery  (50%)
  |  StealthServiceDiscovery     (50%)     [K/KD -> S/SD]
  v
CONTRACTOR NETWORK HOSTS [State: S/SD]
  |
  |  DiscoverDeception (25%)  -- if decoy suspected
  |  ExploitRemoteService (50%)            [S -> U]
  |    * 95% detection: process_creation event fired
  |    * 5% silent: no event, but cmd.exe/sh dropped (density=0.9)
  |    * Decoy hit: connection event + exploit fails
  v
RESTRICTED ZONE A/B [State: U]
  |
  |  DiscoverRemoteSystems (50%) -- discover oza/ozb hosts
  |  PrivilegeEscalate (50%)               [U -> R]
  |    * ALWAYS drops escalate.exe/sh (density=0.9)
  |    * NO events fired -- completely silent without malfile flag
  v
RESTRICTED ZONE A/B [State: R]
  |
  |  Impact (25%)   -- -10/step in mission-active zone
  |  DegradeServices (25%) -- permanent service degradation
  |  DiscoverRemoteSystems (50%) -- pivot to next subnet
  v
OPERATIONAL ZONE A/B [State: R]
  |
  |  Impact (50%)              -- maximum damage
  |  DegradeServices (50%)
  v
HQ NETWORK [State: R]
```

---

## 3. The PhishingEmail Attack Chain (Channel B) -- The Silent Threat

```
CHANNEL B: GreenLocalWork action (every green agent, every step)

GreenAgent on ANY host in ANY subnet
  |
  |  fp_detection_rate = 1%  -> fake process_creation event (blue sees FP)
  |  phishing_error_rate = 1% -> triggers PhishingEmail sub-action
  |
  v
PhishingEmail.execute():
  1. Finds the red agent closest/reachable to green host
  2. Uses check_routable() -- IGNORES all BlockTrafficZone rules
  3. Creates RedAbstractSession(username='user') on green host
  4. NO process_creation event
  5. NO network_connection event
  6. NO file dropped (density=0 files only)
  |
  v
Red has USER session on green host
  |
  |  Red FSM then runs PrivilegeEscalate on the session
  |    * Drops escalate.exe/sh (density=0.9) -- detectable by v6 malfile flag!
  |    * NO events
  |
  v
Red has ROOT session on green host
  |
  |  Impact -> -10/step in mission-active zone
```

---

## 4. Network Topology with Both Channels Illustrated

```
Internet ----------------------------------------------------------
    |                                                             |
    | Channel A: red_agent_0 starts here                         | Channel B: PhishingEmail
    | (blocked by firewall after blue sets up)                   | (bypasses ALL blocks via check_routable)
    v                                                             |
CONTRACTOR NETWORK --------------------------------------+        |
    |                                                   |        |
    | ExploitRemoteService                              |        |
    | (95% detect, 5% silent)                           |        |
    | Blocked if firewall in place                      |        |
    v                                                   |        |
RESTRICTED ZONE A <--------------------- blue_agent_0  |        |
    |                                                   |        |
    | PrivilegeEscalate                                 |        |
    | (SILENT: no events,                               |        |
    |  malfile detects in v6)                           |        |
    v                                                   |        |
OPERATIONAL ZONE A <--------------------- blue_agent_1 |        |
    | Impact: -10/step (Phase 1)                        |        |
    | DegradeServices: permanent                        |        |
                                                        |        |
RESTRICTED ZONE B <--------------------- blue_agent_2  |        |
    |                                                   |        |
    | PrivilegeEscalate (silent)                        |        |
    v                                                   |        |
OPERATIONAL ZONE B <--------------------- blue_agent_3 |        |
    | Impact: -10/step (Phase 2)                        |        |
    | DegradeServices: permanent                        |        |
                                                        |        |
HQ (admin/office/public) <-------------- blue_agent_4  |        |
    | Impact: -3/step                                   |        |
    | DegradeServices: permanent                        |        |
                                                        |        |
    GREEN AGENT on OZA host <-------------------------------------+
    |  (GreenLocalWork, 1% error)
    |  --> PhishingEmail --> Red session (silent, no flags)
    |  --> PrivilegeEscalate --> Root (malfile=1, detectable in v6!)
    v
    Impact: -10/step bypass complete
```

---

## 5. What Blue Can and Cannot Detect

| Attack Step | Channel | proc_flag | conn_flag | malfile_flag | Detectable? |
|-------------|---------|-----------|-----------|--------------|-------------|
| ExploitRemoteService (95%) | A | 1 | 0 | 1 | Yes (proc + malfile) |
| ExploitRemoteService (5% silent) | A | 0 | 0 | 1 | v6 only (malfile) |
| Decoy hit | A | 0 | 1 | 0 | Yes (conn flag) |
| PrivilegeEscalate | A | 0 | 0 | 1 | v6 only (malfile) |
| DegradeServices | A | 0 | 0 | 0 | Never |
| PhishingEmail entry | B | 0 | 0 | 0 | Never |
| PrivilegeEscalate after PhishingEmail | B | 0 | 0 | 1 | v6 only (malfile) |
| Impact (after root session) | A/B | 0 | 0 | 0 | Only via reward penalty |

---

## 6. Why PhishingEmail Is Architecturally Unblockable

`PhishingEmail.check_routable()` traverses the network graph using **connected components** -- it does not consult `state.blocks`. The firewall (`BlockTrafficZone`) writes to `state.blocks`, but `check_routable` completely ignores that data structure.

This means:
- Even if blue perfectly isolates RZA with 4 blocks (contractor, internet, rzb, oza), red can still PhishingEmail into OZA because green's host is already inside the zone.
- The only way to prevent PhishingEmail from being useful to red is to have no red agent reachable to any green host -- which is impossible once red is inside any subnet.

**Realism question:** In real networks, phishing emails travel via email infrastructure (SMTP), not via IP routing. A firewall blocking subnet-level IP routing would NOT prevent a phishing email from reaching an inbox. So the simulation's design choice (PhishingEmail bypasses firewall blocks) is **defensible from a realism standpoint** -- but the implementation mechanism (`check_routable` ignoring `state.blocks`) may conflate two different concepts (IP routing vs. email delivery).

---

## 7. The Remaining Noise Floor After v6

With v6, blue now catches:
- All PrivilegeEscalate (via malfile) -- previously completely silent
- 5% silent exploits (via malfile)
- 95% exploits (via proc_flag + malfile)

What remains undetectable:
- PhishingEmail entry itself (no file, no event)
- DegradeServices (no file, no event -- permanent 20% reliability reduction)
- Impact (only visible as a reward penalty)

The **minimum irreducible penalty** comes from:
1. PhishingEmail granting user access -> red runs PrivilegeEscalate (now detectable via malfile) -> blue Restores -> 5-step window of root access
2. DegradeServices silently degrading services before blue can respond
3. The 1-5 steps between PrivilegeEscalate (now detectable) and Restore completing

This is why the theoretical floor is ~-3,000 to -4,000/ep even with perfect detection of everything detectable. v6 at -1,990 mean is already inside that window, suggesting it is reacting to PrivilegeEscalate very quickly.

---

## 8. FSM State Transition Matrices (FiniteStateRedAgent)

### On Success

| State | Discover | AggScan | StealthScan | DiscoverDecoy | Exploit | PrivEsc | Impact | Degrade | Withdraw |
|-------|----------|---------|-------------|---------------|---------|---------|--------|---------|----------|
| K     | KD       | S       | S           | -             | -       | -       | -      | -       | -        |
| KD    | KD       | SD      | SD          | -             | -       | -       | -      | -       | -        |
| S     | SD       | -       | -           | S             | U       | -       | -      | -       | -        |
| SD    | SD       | -       | -           | SD            | UD      | -       | -      | -       | -        |
| U     | UD       | -       | -           | -             | -       | R       | -      | -       | S        |
| UD    | UD       | -       | -           | -             | -       | RD      | -      | -       | SD       |
| R     | RD       | -       | -           | -             | -       | -       | R      | R       | S        |
| RD    | RD       | -       | -           | -             | -       | -       | RD     | RD      | SD       |

### Action Probabilities per State

| State | Discover | AggScan | StealthScan | DiscoverDecoy | Exploit | PrivEsc | Impact | Degrade | Withdraw |
|-------|----------|---------|-------------|---------------|---------|---------|--------|---------|----------|
| K     | 0.50     | 0.25    | 0.25        | -             | -       | -       | -      | -       | -        |
| KD    | -        | 0.50    | 0.50        | -             | -       | -       | -      | -       | -        |
| S     | 0.25     | -       | -           | 0.25          | 0.50    | -       | -      | -       | -        |
| SD    | -        | -       | -           | 0.25          | 0.75    | -       | -      | -       | -        |
| U     | 0.50     | -       | -           | -             | -       | 0.50    | -      | -       | 0.0      |
| UD    | -        | -       | -           | -             | -       | 1.00    | -      | -       | 0.0      |
| R     | 0.50     | -       | -           | -             | -       | -       | 0.25   | 0.25    | 0.0      |
| RD    | -        | -       | -           | -             | -       | -       | 0.50   | 0.50    | 0.0      |

**Key insight**: Once root (R state), red splits 50/50 between Discovery (lateral movement) and Impact/Degrade. It never voluntarily withdraws from a compromised host (probability = 0.0).
