# SDN Host Discovery Service
**Course:** UE24CS252B – Computer Networks  
**Project:** Orange Problem – Host Discovery Service  
**Controller:** Ryu (OpenFlow 1.3)  
**Topology Tool:** Mininet  

---

## Problem Statement

In a traditional network, host tracking is passive and manual. In an SDN environment, the controller has a global view of the network. This project implements an **automatic Host Discovery Service** that:

- Detects when a new host joins the network (via `PacketIn` events)
- Maintains a live host database (MAC, IP, switch DPID, port, timestamps, packet count)
- Exposes a REST API for external consumption
- Provides a real-time HTML dashboard showing all discovered hosts

---

## Topology

```
           [Ryu Controller]
                 |
             [s1] (core switch)
            /       \
         [s2]       [s3]
        /  |  \     /   \
      h1  h2  h3  h4    h5
  10.0.1.x         10.0.2.x
```

- 3 switches (1 core + 2 edge), 5 hosts across 2 subnets
- OpenFlow 1.3, 100 Mbps host links, 1 Gbps inter-switch links

---

## Files

| File | Purpose |
|---|---|
| `controller.py` | Ryu application – PacketIn handler, host DB, REST API |
| `topology.py` | Mininet topology + automated test scenarios |
| `dashboard.html` | Live browser dashboard (polls REST API) |

---

## Setup & Execution

### Prerequisites

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install mininet -y
pip3 install ryu --break-system-packages   # or: pip3 install ryu
```

> **WSL users:** Mininet works on WSL2 with the `--switch ovsbr` flag if OVS kernel module is unavailable. Run `sudo mn --switch ovsbr` to verify.

### Step 1 – Start the Ryu controller

```bash
ryu-manager --ofp-tcp-listen-port 6633 --wsapi-port 8080 controller.py
```

You should see:
```
Host Discovery Controller started – REST API at /hostdiscovery
```

### Step 2 – Start the Mininet topology

Open a **second terminal**:

```bash
sudo python3 topology.py
```

The script will:
1. Build the topology
2. Connect all switches to Ryu
3. Run 4 automated test scenarios
4. Drop into the Mininet CLI

### Step 3 – Open the Dashboard

Open `dashboard.html` in any browser. It polls `http://localhost:8080/hostdiscovery` every 3 seconds and shows all discovered hosts live.

> If the controller is not reachable, the dashboard shows **DEMO MODE** with static example data so the UI is always visible.

### Step 4 – REST API

| Endpoint | Description |
|---|---|
| `GET /hostdiscovery/hosts` | All discovered hosts (JSON) |
| `GET /hostdiscovery/stats` | Summary stats |
| `GET /hostdiscovery/hosts/{mac}` | Single host detail |

```bash
curl http://localhost:8080/hostdiscovery/hosts | python3 -m json.tool
curl http://localhost:8080/hostdiscovery/stats
```

---

## Test Scenarios

### Scenario 1 – Full mesh ping (host join detection)
```
mininet> pingall
```
Expected: 0% packet loss. All 5 hosts are discovered by the controller.

### Scenario 2 – Cross-switch forwarding (h1 → h4)
```
mininet> h1 ping -c 4 10.0.2.1
```
Expected: Packets route through s1 (core). First packet triggers PacketIn; subsequent packets use installed flow rules.

### Scenario 3 – Throughput (iperf)
```
mininet> h5 iperf -s &
mininet> h2 iperf -c 10.0.2.2 -t 5
```
Expected: ~90–95 Mbps (limited by 100 Mbps link).

### Scenario 4 – Flow table inspection
```
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s2
```
Expected: Unicast forwarding rules installed after first PacketIn per pair.

### Regression / Validation
```
mininet> h1 ping -c 2 10.0.1.2   # intra-switch
mininet> h3 ping -c 2 10.0.2.2   # cross-switch
mininet> net                       # verify topology wiring
mininet> dump                      # verify all nodes running
```

---

## Expected Output (screenshots location)

Add your screenshots to a `screenshots/` folder in the repo:

- `screenshots/pingall.png` – pingall 0% loss

<img width="664" height="285" alt="image" src="https://github.com/user-attachments/assets/ffb9b1a6-39d2-48e4-8681-83baa34bd651" />

- `screenshots/dumplflows.png` – ovs-ofctl dump after learning

<img width="1189" height="209" alt="image" src="https://github.com/user-attachments/assets/434423e7-5b39-4116-aa91-4e95c1abf8e7" />

- `screenshots/iperf.png` – iperf throughput

<img width="1116" height="280" alt="image" src="https://github.com/user-attachments/assets/53f32df6-fb0f-4c60-9913-9c8f037e3ac7" />

- `screenshots/newhost.png` – HTML dashboard with hosts

<img width="1059" height="403" alt="image" src="https://github.com/user-attachments/assets/02affbfb-657d-40b4-a94e-a0c864b7d486" />

- `screenshots/controlswitch.png` – Control Switch demonstration

<img width="847" height="295" alt="image" src="https://github.com/user-attachments/assets/c9ec683f-58b7-4a5b-af9d-7f15638b2d26" />

---

## Cleanup

```bash
sudo mn -c
```

---

## SDN Concepts Demonstrated

| Concept | Where |
|---|---|
| PacketIn events | `packet_in_handler` in `controller.py` |
| Match–Action rules | `_add_flow()` – match on `eth_dst`, install unicast output action |
| Table-miss rule | Priority 0, installed on `switch_features_handler` |
| MAC learning | `mac_to_port` dict per DPID |
| Flow timeouts | `idle_timeout=30, hard_timeout=120` on learned rules |
| REST API | Ryu WSGI routes in `HostDiscoveryREST` |
| Multi-switch topology | Two edge switches under one core |

---

## References

1. Ryu SDN Framework – https://ryu.readthedocs.io/
2. OpenFlow 1.3 Specification – https://opennetworking.org/
3. Mininet Walkthrough – https://mininet.org/walkthrough/
4. Mininet GitHub – https://github.com/mininet/mininet
5. OVS OpenFlow – http://www.openvswitch.org/
