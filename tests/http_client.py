"""Independent HTTP test transport for Host contract tests."""
import http.client
import json
from urllib.parse import urlsplit
import uuid


class HttpClient:
    def __init__(self, url, timeout=12):
        self.address = urlsplit(url)
        self.timeout = timeout

    def request(self, command="get_state", **fields):
        return self.send({"version": 1, "id": fields.pop("id", str(uuid.uuid4())),
                          "command": command, **fields})

    def send(self, request):
        connection = http.client.HTTPConnection(self.address.hostname, self.address.port, timeout=self.timeout)
        try:
            connection.request("POST", "/api", json.dumps(request).encode("utf-8"), {"Content-Type": "application/json"})
            response = json.loads(connection.getresponse().read())
            if response.get("id") != request.get("id", ""):
                raise ValueError("Response id does not match request.")
            return response
        finally:
            connection.close()

    def close(self):
        pass
