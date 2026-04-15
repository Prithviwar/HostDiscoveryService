"""
Host Discovery Service - Ryu SDN Controller
============================================
Detects host join events via PacketIn, maintains a host database,
and exposes a REST API for the dashboard.

Author  : (your name)
Course  : UE24CS252B – Computer Networks
Project : SDN Host Discovery Service
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, ipv6, arp
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.lib import hub

import json
import time
import logging

LOG = logging.getLogger("host_discovery")

# ──────────────────────────────────────────────────────────────────────────────
# REST API URL base
# ──────────────────────────────────────────────────────────────────────────────
HOST_DISCOVERY_API_INSTANCE_NAME = "host_discovery_api_app"
URL_BASE = "/hostdiscovery"


# ──────────────────────────────────────────────────────────────────────────────
# Main Ryu Application
# ──────────────────────────────────────────────────────────────────────────────
class HostDiscoveryController(app_manager.RyuApp):
    """
    Ryu application that:
      1. Installs a table-miss flow rule so all unknown packets reach
         the controller (PacketIn).
      2. Learns host MAC → IP → switch DPID → port mappings.
      3. Installs unicast forwarding rules once both endpoints are known.
      4. Exposes a REST API so the HTML dashboard can poll live data.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ── Host database ──────────────────────────────────────────────────
        # key  : MAC address (str)
        # value: dict { mac, ip, dpid, port, first_seen, last_seen, pkt_count }
        self.host_db: dict = {}

        # MAC-to-port table per switch   { dpid: { mac: port } }
        self.mac_to_port: dict = {}

        # Flow statistics snapshot       { dpid: [flow_stats, …] }
        self.flow_stats: dict = {}

        # WSGI registration
        wsgi = kwargs["wsgi"]
        wsgi.register(HostDiscoveryREST,
                      {HOST_DISCOVERY_API_INSTANCE_NAME: self})

        LOG.info("Host Discovery Controller started – REST API at %s", URL_BASE)

    # ── Switch handshake ─────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss rule: send all unmatched packets to controller."""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        # Table-miss: priority 0, no match → send to controller
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        LOG.info("Switch %016x connected – table-miss rule installed", datapath.id)

    # ── Packet-In handler ────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id
        in_port  = msg.match["in_port"]

        pkt      = packet.Packet(msg.data)
        eth_pkt  = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return

        src_mac  = eth_pkt.src
        dst_mac  = eth_pkt.dst

        # Ignore LLDP / spanning-tree frames
        if eth_pkt.ethertype in (0x88CC, 0x8100):
            return

        # ── Resolve IP address from packet ──────────────────────────────
        src_ip = None
        ip4 = pkt.get_protocol(ipv4.ipv4)
        ip6 = pkt.get_protocol(ipv6.ipv6)
        arp_pkt = pkt.get_protocol(arp.arp)

        if ip4:
            src_ip = ip4.src
        elif ip6:
            src_ip = ip6.src
        elif arp_pkt:
            src_ip = arp_pkt.src_ip

        # ── Update host database ──────────────────────────────────────────
        now = time.time()
        if src_mac not in self.host_db:
            self.host_db[src_mac] = {
                "mac":        src_mac,
                "ip":         src_ip or "unknown",
                "dpid":       f"{dpid:016x}",
                "port":       in_port,
                "first_seen": now,
                "last_seen":  now,
                "pkt_count":  1,
            }
            LOG.info("[NEW HOST] MAC=%s  IP=%s  DPID=%016x  Port=%d",
                     src_mac, src_ip or "?", dpid, in_port)
        else:
            entry = self.host_db[src_mac]
            entry["last_seen"]  = now
            entry["pkt_count"] += 1
            if src_ip and entry["ip"] == "unknown":
                entry["ip"] = src_ip
                LOG.info("[IP RESOLVED] MAC=%s → IP=%s", src_mac, src_ip)

        # ── MAC learning & forwarding ─────────────────────────────────────
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install a proactive rule if we know the destination port
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac,
                                    eth_src=src_mac)
            self._add_flow(datapath, priority=1, match=match,
                           actions=actions, idle_timeout=30, hard_timeout=120)

        # Send the current packet out
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=data
        )
        datapath.send_msg(out)

    # ── Helper: install flow rule ─────────────────────────────────────────────
    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst    = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                                actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    # ── Public helpers used by REST layer ─────────────────────────────────────
    def get_all_hosts(self):
        """Return serialisable snapshot of the host database."""
        now   = time.time()
        hosts = []
        for mac, h in self.host_db.items():
            entry = dict(h)
            entry["online_duration"] = round(now - h["first_seen"], 1)
            entry["last_seen_ago"]   = round(now - h["last_seen"],  1)
            entry["first_seen_ts"]   = time.strftime(
                "%H:%M:%S", time.localtime(h["first_seen"]))
            entry["last_seen_ts"]    = time.strftime(
                "%H:%M:%S", time.localtime(h["last_seen"]))
            hosts.append(entry)
        return hosts

    def get_stats(self):
        total     = len(self.host_db)
        online    = sum(1 for h in self.host_db.values()
                        if time.time() - h["last_seen"] < 10)
        switches  = len(self.mac_to_port)
        pkt_total = sum(h["pkt_count"] for h in self.host_db.values())
        return {
            "total_hosts":   total,
            "online_hosts":  online,
            "switches":      switches,
            "total_packets": pkt_total,
        }


# ──────────────────────────────────────────────────────────────────────────────
# REST API Controller (Ryu WSGI)
# ──────────────────────────────────────────────────────────────────────────────
class HostDiscoveryREST(ControllerBase):
    """Exposes GET endpoints consumed by the HTML dashboard."""

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.app: HostDiscoveryController = \
            data[HOST_DISCOVERY_API_INSTANCE_NAME]

    @route("hosts", URL_BASE + "/hosts", methods=["GET"])
    def get_hosts(self, req, **kwargs):
        hosts = self.app.get_all_hosts()
        body  = json.dumps({"hosts": hosts}, indent=2)
        return self._json_response(body)

    @route("stats", URL_BASE + "/stats", methods=["GET"])
    def get_stats(self, req, **kwargs):
        body = json.dumps(self.app.get_stats(), indent=2)
        return self._json_response(body)

    @route("host_detail", URL_BASE + "/hosts/{mac}", methods=["GET"])
    def get_host_detail(self, req, mac, **kwargs):
        # URL encoding replaces ':' with %3A sometimes
        mac   = mac.replace("%3A", ":")
        entry = self.app.host_db.get(mac)
        if entry is None:
            body = json.dumps({"error": "host not found"})
            return self._json_response(body, status=404)
        body = json.dumps(entry, indent=2)
        return self._json_response(body)

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _json_response(body, status=200):
        from webob import Response
        res = Response(content_type="application/json",
                       charset="utf-8",
                       status=status,
                       body=body.encode())
        res.headers["Access-Control-Allow-Origin"] = "*"
        return res
