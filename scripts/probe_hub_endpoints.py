#!/usr/bin/env python3
"""Probe a Norman hub for undocumented **read-only** endpoints.

The hub's local API has no authentication and no discovery mechanism, so the only way to
find an endpoint is to ask for it by name. This script asks for a list of plausible names
and reports which ones answer, so the protocol reference can be extended without guessing.

**It is read-only by construction.** Every request body carries only ``ThingName``,
``TaskID`` and ``Timestamp`` -- never a control verb, a position, or any field that would
write to the hub. Names that look like writes (Add/Set/Update/Delete/Clean/Control/...) are
refused before a request is made, so a typo cannot turn into a command. Nothing here can
move a blind; the worst case is an unknown endpoint returning an error.

Usage:

    python3 scripts/probe_hub_endpoints.py 192.168.0.22
    python3 scripts/probe_hub_endpoints.py 192.168.0.22 --extra GetAllZone,GetTimer
    python3 scripts/probe_hub_endpoints.py 192.168.0.22 --json > hub-endpoints.json

Findings worth acting on are endpoints that answer with ``status.code: 0`` (or ``Error: 0``)
and a payload the integration does not already model. Please attach the output to an issue.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 10123
TIMEOUT = 5.0

# Endpoints the integration already knows about (documented in docs/NORMAN_API.md). They are
# probed too so the output shows what a known-good reply looks like next to the unknown ones.
KNOWN = (
    "registration",
    "GetAllPeripheral",
    "status",
    "GetAllSchedule",
    "GetDeviceInfo",
)

# Names to try. Built from three sources: the plural of every noun the hub's payloads use
# (Scene, SceneGroup, Room, Group, Peripheral), the naming style the app's own endpoints
# follow (GetAllX / GetX), and features the app has that we have not seen an endpoint for.
CANDIDATES = (
    # scenes: SceneList and SceneGroupList appear in GetAllPeripheral but are always empty
    "GetAllScene",
    "GetAllSceneGroup",
    "GetScene",
    "GetSceneGroup",
    # rooms and groups as their own reads
    "GetAllRoom",
    "GetAllGroup",
    "GetRoom",
    "GetGroup",
    "GetAllPeripheralInfo",
    "GetPeripheral",
    # hub-level information
    "GetHubInfo",
    "GetDeviceStatus",
    "GetNetworkInfo",
    "GetWiFiInfo",
    "GetTimeZone",
    "GetGeoLoc",
    "GetVersion",
    "GetFirmwareInfo",
    "GetOTAStatus",
    "GetLog",
    "GetErrorCode",
    "GetStatistics",
    # scheduling and automation
    "GetSchedule",
    "GetAllTimer",
    "GetAllScenario",
    "GetAllRule",
    "GetSunriseSunset",
    # pairing and diagnostics (read side only)
    "GetPairingMode",
    "GetAllPairedDevice",
    "GetModuleInfo",
    "GetBatteryLevel",
    "GetRssi",
    "GetSignal",
    # generic shapes seen in similar Dexatek firmware
    "GetAll",
    "GetInfo",
    "GetConfig",
    "GetSetting",
    "GetAllSetting",
)

# A name *starting* with any of these is a write (or a command) and is never sent. The check
# is anchored on purpose: matching anywhere would reject read-only names that merely contain
# a write-ish word ("GetPairingMode", "GetAllSetting", "GetOTAStatus"), while a real write
# always leads with its verb ("SetTopLimit", "AddSchedule", "DeleteSchedule", "control").
FORBIDDEN_PREFIXES = (
    "add",
    "set",
    "update",
    "delete",
    "remove",
    "clean",
    "clear",
    "reset",
    "control",
    "start",
    "stop",
    "pair",
    "unpair",
    "reboot",
    "restart",
    "factory",
    "erase",
    "write",
    "put",
    "post",
    "enable",
    "disable",
    "toggle",
    "move",
    "open",
    "close",
    "calibrat",
    "ota",
    "upgrade",
)

# The only names that are ever sent: reads, plus the two lowercase endpoints the hub
# happens to expose (registration echoes identity, status reads positions).
ALLOWED_PREFIXES = ("get", "registration", "status")


def is_read_only(name: str) -> bool:
    """Whether ``name`` is safe to probe: a read, by its name, and nothing else."""
    lowered = name.lower()
    if lowered.startswith(FORBIDDEN_PREFIXES):
        return False
    # Anything that does not announce itself as a read is treated as unsafe.
    return lowered.startswith(ALLOWED_PREFIXES)


def probe(host: str, port: int, name: str, thing_name: str | None) -> dict:
    """POST an identity-only body to one endpoint and summarise the reply."""
    url = f"http://{host}:{port}/NM/v1/{name}"
    body: dict[str, object] = {"Timestamp": int(time.time()), "TaskID": 1}
    if thing_name:
        body["ThingName"] = thing_name
    request = urllib.request.Request(  # noqa: S310 - fixed http scheme, host from argv
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as err:
        raw, status = err.read().decode("utf-8", "replace"), err.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        return {"endpoint": name, "error": str(err)}

    result: dict[str, object] = {
        "endpoint": name,
        "http": status,
        "ms": round((time.monotonic() - started) * 1000),
    }
    try:
        data = json.loads(raw)
    except ValueError:
        result["body"] = raw[:200]
        result["ok"] = False
        return result

    # The hub reports failure two ways: a top-level Error, or status.code for the
    # GetAll-style endpoints (see docs/NORMAN_API.md, "Error conventions").
    code = data.get("Error") if isinstance(data, dict) else None
    inner = data.get("status") if isinstance(data, dict) else None
    if isinstance(inner, dict):
        code = inner.get("code", code)
    result["code"] = code
    result["ok"] = code in (0, "0", None) or str(code).lower().startswith("succ")
    payload = data.get("results", data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        result["keys"] = sorted(k for k in payload if k not in ("TaskID", "RequestTimestamp"))
    result["sample"] = json.dumps(data)[:400]
    # The parsed reply, kept whole: "sample" is truncated for display and cannot be re-parsed.
    result["data"] = data
    return result


def main() -> int:
    """Probe every candidate endpoint and print what answered."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="hub IP address or hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--extra", default="", help="comma-separated extra names to try")
    parser.add_argument("--json", action="store_true", help="emit raw JSON results")
    args = parser.parse_args()

    names = list(dict.fromkeys((*KNOWN, *CANDIDATES, *filter(None, args.extra.split(",")))))
    unsafe = [name for name in names if not is_read_only(name)]
    if unsafe:
        print(f"refusing to probe non-read endpoints: {', '.join(unsafe)}", file=sys.stderr)
        return 2

    # ThingName is required by the GetAll-style endpoints; read it from registration first.
    registration = probe(args.host, args.port, "registration", None)
    reply = registration.get("data")
    thing_name = reply.get("ThingName") if isinstance(reply, dict) else None
    if thing_name is None:
        print(
            "warning: no ThingName from registration; identity-scoped reads will fail",
            file=sys.stderr,
        )

    results = [probe(args.host, args.port, name, thing_name) for name in names]

    for result in results:
        result.pop("data", None)  # display/JSON output keeps the truncated sample only

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    answered = [r for r in results if r.get("ok")]
    print(f"{len(answered)} of {len(results)} endpoints answered on {args.host}:{args.port}\n")
    for result in results:
        if not result.get("ok"):
            continue
        known = " (known)" if result["endpoint"] in KNOWN else " *** UNDOCUMENTED ***"
        print(f"{result['endpoint']}{known}")
        print(f"    keys: {', '.join(result.get('keys', [])) or '-'}")
        print(f"    {result['sample'][:200]}")
    silent = []
    for result in results:
        if result.get("ok"):
            continue
        why = result.get("error") or result.get("code") or f"HTTP {result.get('http')}"
        silent.append(f"{result['endpoint']} ({why})")
    print("\nno answer / error:\n  " + "\n  ".join(silent))
    print("\nAnything marked UNDOCUMENTED is worth an issue at")
    print("https://github.com/kedube/ha-norman/issues with this output attached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
