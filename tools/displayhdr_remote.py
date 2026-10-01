"""HTTP JSON client for DisplayHDR (Python standard library only)."""
import argparse
import json
import urllib.error
import urllib.request
import uuid


class DisplayHDRRemoteClient:
    def __init__(self, url, timeout=12):
        self.url = url.rstrip("/") + "/api"
        self.timeout = timeout
        # Direct LAN connections must not inherit an unrelated system proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, command="get_state", **fields):
        return self.send({"version": 1, "id": fields.pop("id", str(uuid.uuid4())),
                          "command": command, **fields})

    def send(self, request):
        data = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(data) > 16384:
            raise ValueError("Request exceeds the 16 KiB limit.")
        message = urllib.request.Request(self.url, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            response = self.opener.open(message, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("Response exceeds the client limit.")
        result = json.loads(body)
        if result.get("id") != request.get("id", ""):
            raise ValueError("Response id does not match the request.")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="http://DISPLAYHDR-PC:8765")
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--command", choices=["catalog", "get_state", "set_state"], default="get_state")
    parser.add_argument("--test")
    parser.add_argument("--settings", type=json.loads)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    fields = {key: value for key, value in (("test", args.test), ("settings", args.settings)) if value is not None}
    if args.restart:
        fields["restart"] = True
    result = DisplayHDRRemoteClient(args.url, args.timeout).request(args.command, **fields)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
