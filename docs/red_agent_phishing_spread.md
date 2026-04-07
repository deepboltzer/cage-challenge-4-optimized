# How Red Spreads via PhishingEmail

**Red does not send the phishing email itself.** The mechanism is entirely passive from
red's perspective — it is triggered by green agent mistakes.

---

## The Trigger: Green Agent Error Rate

Every step, each green agent picks a random action: `GreenLocalWork`, `GreenAccessService`,
or `Sleep`. When a green agent executes `GreenLocalWork`, there is a **1% chance**
(`phishing_error_rate=0.01`) that it "accidentally opens a malicious email":

```
  GreenLocalWork.execute():
    1. Do normal work (use a service on own host)
    2. 1% chance: trigger PhishingEmail as a sub-action
                  ← this models "user opened a phishing email"
```

With 50 green agents across the network, each taking `GreenLocalWork` roughly 1/3 of steps:

- ~16–17 `GreenLocalWork` actions per step on average
- Expected phishing events per step: **~0.16** (roughly one every 6 steps)
- By step 30: red likely has at least one session somewhere in the network

---

## What PhishingEmail Actually Does

`PhishingEmail.execute()` (`CybORG/Simulator/Actions/ConcreteActions/PhishingEmail.py`):

```
  Step 1: Find the host the green agent is working on (from ip_address)

  Step 2: Find a red agent routable to that host
            — prefers a red already in the same subnet
            — falls back to any other physically reachable red agent
            — if no red agent is routable anywhere: action fails

  Step 3: Create a new red shell session on the green agent's host
            → RedAbstractSession at user-level privilege
            → Attributed to whichever red agent was found in Step 2
```

```
  Green agent's host              Red agent (anywhere reachable)
  ┌────────────────┐                      ┌─────────────┐
  │  green_agent   │  opens email    ←    │  red_agent  │
  │  (any subnet)  │                      │  (subnet X) │
  └───────┬────────┘                      └─────────────┘
          │
          │  PhishingEmail creates:
          ▼
  ┌────────────────┐
  │  red session   │  ← new user-level foothold
  │  on this host  │    no exploit needed, no events fired
  └────────────────┘
```

The session is created **silently** — no process event, no connection event, no malfile
flag. Blue has no direct observation of the phishing foothold itself.

---

## The Critical Firewall Bypass

`PhishingEmail` uses `check_routable()` (physical link connectivity) instead of
`blocking_host()` (firewall state):

```
  BlockTrafficZone ─────── NO effect on PhishingEmail
                           Email arrives via out-of-band SMTP relay,
                           not through the IP firewall.

  BlockTrafficZone ─────── DOES block ExploitRemoteService
                           (lateral movement after the foothold)
```

**Blue can never prevent the initial phishing foothold.** Even with all firewall rules
in place from step 1, phishing will eventually deliver a red session somewhere.

---

## After PhishingEmail: Red's Lateral Movement

The phishing email gives red only a **user-level session** on a host where a green agent
works. From there, red follows its FSM to reach the OT impact targets:

```
  Phishing foothold
  (user session, any host)
        │
        ▼  DiscoverRemoteSystems       [5 steps]  — finds IPs in subnet
        │
        ▼  AggressiveServiceDiscovery  [2 steps]  — finds open ports on target
           or StealthServiceDiscovery  [2 steps]
        │
        ▼  ExploitRemoteService        [5 steps]  ← CAN be blocked by firewall
           (drops cmd.exe/cmd.sh, density=0.9, unsigned)
           (95% fires proc_creation event + conn event)
           (5% fires only conn event — "silent exploit")
        │
        ▼  PrivilegeEscalate           [2 steps]  — needs user session
           (drops escalate.exe/escalate.sh, density=0.9, unsigned)
           (fires NO events — only detectable via malfile flag)
        │
        ▼  Impact                      [1 step]   — needs root + OTService
           (-10 reward, permanent OT damage, not undone by Restore)
```

The firewall only helps **from ExploitRemoteService onward**. Blocking `RZA → OZA`
prevents red from pivoting to the impact target via IP, but the phishing foothold in
the network already exists.

---

## Red FSM State Transitions

The `FiniteStateRedAgent` tracks each discovered host as a state in its finite state machine:

```
  State  Meaning                           Next actions available
  ─────  ───────────────────────────────   ────────────────────────────────────
  K      Known (IP discovered)             DiscoverRemoteSystems, ServiceDiscovery
  KD     Known + decoy detected            DiscoverRemoteSystems, ServiceDiscovery
  S      Scanned (services known)          DiscoverDeception, ExploitRemoteService
  SD     Scanned + decoy detected          DiscoverDeception, ExploitRemoteService
  U      Exploited (user session)          PrivilegeEscalate, Withdraw
  UD     Exploited + decoy detected        PrivilegeEscalate, Withdraw
  R      Root session (PrivEsc done)       Impact, DegradeServices, Withdraw
  RD     Root + decoy detected             Impact, DegradeServices, Withdraw
  F      Failed / evicted (blue Restored)  only DiscoverRemoteSystems (retry)
```

Transitions on success:
```
  K  ──ServiceScan──► S ──Exploit──► U ──PrivEsc──► R ──Impact──► R (stays R)
  Any state ──Blue Restore──► F ──DiscoverRemote──► K (restart)
```

---

## Implication for Blue Strategy

Because phishing bypasses all defenses and fires ~every 6 steps:

1. **Assume red will appear in any zone at any time.** Deploy decoys everywhere from
   step 1, not just after detecting red.

2. **Firewall rules limit pivot paths, not initial entry.** Block `RZA ↔ OZA` and
   `RZB ↔ OZB` as early as possible to prevent red from reaching the impact targets
   even after gaining a phishing foothold.

3. **The malfile flag is the only reliable early warning.** ExploitRemoteService always
   drops `cmd.exe`/`cmd.sh` (detectable via `BlueFlatWrapperV2`). PrivilegeEscalate
   always drops `escalate.exe`/`escalate.sh` with no other events — malfile is the
   only signal.

4. **Decoys intercept lateral movement, not the initial foothold.** Phishing lands on
   a green agent's host (user machines, contractor zone), not on servers. Decoys on
   servers and OZ hosts are what stop red from pivoting once it starts scanning.
