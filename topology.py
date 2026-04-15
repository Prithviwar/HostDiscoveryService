from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import Link
from mininet.log import setLogLevel, info
from mininet.cli import CLI
import time

def build_topology():
    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=Link,
        autoSetMacs=True,
        autoStaticArp=False,
    )
    ctrl = net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
    s1 = net.addSwitch("s1", protocols="OpenFlow13")
    s2 = net.addSwitch("s2", protocols="OpenFlow13")
    s3 = net.addSwitch("s3", protocols="OpenFlow13")
    h1 = net.addHost("h1", ip="10.0.0.1/8", mac="00:00:00:00:01:01")
    h2 = net.addHost("h2", ip="10.0.0.2/8", mac="00:00:00:00:01:02")
    h3 = net.addHost("h3", ip="10.0.0.3/8", mac="00:00:00:00:01:03")
    h4 = net.addHost("h4", ip="10.0.0.4/8", mac="00:00:00:00:02:01")
    h5 = net.addHost("h5", ip="10.0.0.5/8", mac="00:00:00:00:02:02")
    net.addLink(s1, s2)
    net.addLink(s1, s3)
    net.addLink(h1, s2)
    net.addLink(h2, s2)
    net.addLink(h3, s2)
    net.addLink(h4, s3)
    net.addLink(h5, s3)
    return net

def run_tests(net):
    info("\n=== SCENARIO 1: Full mesh ping ===\n")
    net.pingAll()
    info("\n=== SCENARIO 2: Cross-switch ping h1 to h4 ===\n")
    h1, h4 = net.get("h1", "h4")
    info(h1.cmd("ping -c4 10.0.0.4"))
    info("\n=== SCENARIO 3: Throughput h2 to h5 ===\n")
    h2, h5 = net.get("h2", "h5")
    h5.cmd("iperf -s &")
    time.sleep(1)
    info(h2.cmd("iperf -c 10.0.0.5 -t 5"))
    h5.cmd("kill %iperf")
    info("\n=== SCENARIO 4: Flow tables ===\n")
    for sw in ["s1","s2","s3"]:
        info(f"\n--- {sw} ---\n")
        info(net.get(sw).cmd(f"ovs-ofctl -O OpenFlow13 dump-flows {sw}"))

def main():
    setLogLevel("info")
    net = build_topology()
    net.start()
    time.sleep(3)
    run_tests(net)
    CLI(net)
    net.stop()

if __name__ == "__main__":
    main()
