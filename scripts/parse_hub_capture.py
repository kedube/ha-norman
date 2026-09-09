#!/usr/bin/env python3
"""Reassemble the Norman hub's HTTP traffic from a packet capture.

The hub speaks plain HTTP on port 10123, so a capture of the Norman app talking to it is the
only way to learn verbs the app uses but the integration does not know about. This script
turns a pcap into readable request/response pairs, with no third-party dependencies.

Capture (macOS, app on the same machine or the same LAN):

    sudo tcpdump -i en0 -w ~/Downloads/norman-app.pcap 'tcp port 10123'

then use the app, and Ctrl-C the capture. Read it back with:

    python3 scripts/parse_hub_capture.py ~/Downloads/norman-app.pcap

Note: when running tcpdump in *read* mode, always pass -n. Without it tcpdump tries a reverse
DNS lookup per address and appears to hang.

A capture contains your hub's identity (ThingName) and blind names; scrub before attaching to
an issue. See docs/NORMAN_API.md, "Capturing traffic".
"""

from collections import defaultdict
import datetime
import re
import struct
import sys

path = sys.argv[1]
with open(path, "rb") as fh:
    data = fh.read()
magic = data[:4]
if magic == b"\xd4\xc3\xb2\xa1":
    endian = "<"
elif magic == b"\xa1\xb2\xc3\xd4":
    endian = ">"
elif magic == b"\x4d\x3c\xb2\xa1":
    endian = "<"  # nanosecond
else:
    sys.exit(f"not a pcap: {magic!r}")
linktype = struct.unpack(endian + "I", data[20:24])[0]
off = 24
streams = defaultdict(list)  # (src,sport,dst,dport) -> [(ts, seq, payload)]
while off + 16 <= len(data):
    ts_sec, ts_usec, incl, orig = struct.unpack(endian + "IIII", data[off : off + 16])
    off += 16
    pkt = data[off : off + incl]
    off += incl
    ts = ts_sec + ts_usec / 1e6
    if linktype == 1:  # Ethernet
        ethertype = struct.unpack("!H", pkt[12:14])[0]
        if ethertype != 0x0800:
            continue
        ip = pkt[14:]
    elif linktype == 0:  # loopback/NULL
        ip = pkt[4:]
    elif linktype == 101:  # raw IP
        ip = pkt
    else:
        continue
    if ip[0] >> 4 != 4:
        continue
    ihl = (ip[0] & 0xF) * 4
    total = struct.unpack("!H", ip[2:4])[0]
    proto = ip[9]
    if proto != 6:
        continue
    src = ".".join(map(str, ip[12:16]))
    dst = ".".join(map(str, ip[16:20]))
    tcp = ip[ihl:total]
    sport, dport, seq, ack, doff = struct.unpack("!HHIIB", tcp[:13])
    doff = (doff >> 4) * 4
    payload = tcp[doff:]
    if payload:
        streams[(src, sport, dst, dport)].append((ts, seq, payload))


def reassemble(segs):
    segs.sort(key=lambda s: (s[1], s[0]))
    out = b""
    seen = set()
    first_ts = None
    for ts, seq, p in segs:
        if seq in seen:
            continue
        seen.add(seq)
        out += p
        first_ts = first_ts or ts
    return out


def split_http(buf):
    """Yield (headers, body) messages from a byte buffer."""
    msgs = []
    while buf:
        m = re.search(rb"\r\n\r\n", buf)
        if not m:
            break
        head = buf[: m.start()].decode("latin1")
        buf = buf[m.end() :]
        cl = re.search(r"(?i)content-length:\s*(\d+)", head)
        if cl:
            n = int(cl.group(1))
            body = buf[:n]
            buf = buf[n:]
        elif re.search(r"(?i)transfer-encoding:\s*chunked", head):
            body = b""
            while True:
                m2 = re.match(rb"([0-9a-fA-F]+)[^\r\n]*\r\n", buf)
                if not m2:
                    break
                n = int(m2.group(1), 16)
                buf = buf[m2.end() :]
                if n == 0:
                    buf = buf[2:]
                    break
                body += buf[:n]
                buf = buf[n + 2 :]
        else:
            body = buf
            buf = b""
        msgs.append((head, body))
    return msgs


# pair client->server and server->client by 4-tuple
events = []
for key, segs in streams.items():
    src, sport, dst, dport = key
    if dport != 10123:
        continue
    req_buf = reassemble(segs)
    resp_segs = streams.get((dst, dport, src, sport), [])
    resp_buf = reassemble(resp_segs)
    ts0 = min(s[0] for s in segs)
    reqs = split_http(req_buf)
    resps = split_http(resp_buf)
    for i, (h, b) in enumerate(reqs):
        rh, rb = resps[i] if i < len(resps) else ("", b"")
        events.append((ts0, sport, h, b, rh, rb))
events.sort()

for ts, sport, h, b, rh, rb in events:
    t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
    line = h.split("\r\n")[0]
    print(f"\n### {t} port {sport}  {line}")
    hdrs = [
        line
        for line in h.split("\r\n")[1:]
        if line
        and not line.lower().startswith(("host", "content-length", "accept-encoding", "connection"))
    ]
    if hdrs:
        print("   " + " | ".join(hdrs))
    print("   >>", b.decode("utf8", "replace")[:40000])
    print(
        "   <<",
        (rh.split("\r\n")[0] if rh else "(no response)"),
        rb.decode("utf8", "replace")[:40000],
    )
