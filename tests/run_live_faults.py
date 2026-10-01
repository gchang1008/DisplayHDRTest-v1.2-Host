"""Production pipe rejection, timeout, disconnection and reconnect checks."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from displayhdr_api import DisplayHDRClient
pid = int(sys.argv[1])
checks = []
def reconnect():
    with DisplayHDRClient(pid) as client:
        state = client.request()["state"]
        assert state["test"]["id"] == "ColorPatches"
        assert state["settings"]["color"] == "Blue"
        return state
with DisplayHDRClient(pid) as client:
    assert client.request("set_state", test="ColorPatches", settings={"color":"Blue", "textVisible":False})["ok"]
    client._transfer(b"{bad json}\n", False, time.monotonic()+5)
    response = json.loads(client._transfer(None, True, time.monotonic()+5))
    assert not response["ok"] and response["error"]["code"] == "invalid_json"
    assert client.request()["ok"]
checks.append("malformed JSON rejected; same connection remains usable")
with DisplayHDRClient(pid) as client:
    try:
        other = DisplayHDRClient(pid, .25)
    except TimeoutError: pass
    else:
        other.close(); raise AssertionError("Concurrent connection unexpectedly accepted")
checks.append("second connection bounded timeout; first connection survives")
for payload, name in ((b"x"*17000, "oversized"), (b'{"version":1,"settings":', "partial")):
    with DisplayHDRClient(pid) as client:
        client._transfer(payload, False, time.monotonic()+5)
    reconnect()
    checks.append(name+" request disconnect and recovery; state unchanged")
with DisplayHDRClient(pid, 2) as client:
    time.sleep(10.5)
    try: client.request()
    except (OSError, ConnectionError, TimeoutError): pass
    else: raise AssertionError("Idle connection did not expire")
reconnect()
checks.append("10 second idle expiration and recovery")
for index in range(25):
    with DisplayHDRClient(pid) as client:
        payload = json.dumps({"version":1,"id":str(index),"command":"get_state"}).encode()+b"\n"
        client._transfer(payload, False, time.monotonic()+5)
    reconnect()
checks.append("25 disconnects before receiving response; reconnect state intact")
output=Path(__file__).resolve().parents[1]/"build-output/behavior-verification/live-fault-results.json"
output.write_text(json.dumps({"passed":True,"checks":checks},indent=2), encoding="utf-8")
print(json.dumps(checks,indent=2))
