"""Small server-side MCP health client for the initial stateless Hub contract.

Not a general MCP SDK: streaming, business tools and tenant credentials follow
in later iterations. No token is exposed to frontend code.
"""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .config import load_env


class HubError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HubError("Hub redirects are not allowed")


class HubClient:
    def __init__(self, url: str, token: str):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid Hub endpoint")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}
        ):
            raise ValueError("Hub requires HTTPS outside loopback")
        if not parsed.hostname or parsed.path != "/mcp":
            raise ValueError("Hub endpoint must end in /mcp")
        if len(token) < 32 or "\n" in token or "\r" in token:
            raise ValueError("A Hub token of at least 32 characters is required")
        self.url, self.token = url, token
        self.protocol = None
        self.opener = build_opener(NoRedirect)

    @classmethod
    def from_env(cls, path=".env"):
        config = load_env(path)
        return cls(config["RELAY_HUB_URL"], config["RELAY_HUB_TOKEN"])

    def _request(self, method, params, request_id=None):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        headers = {"Authorization": f"Bearer {self.token}",
                   "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        req = Request(self.url, data=json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(req, timeout=5) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise HubError("Hub response exceeds size limit")
                if request_id is None:
                    return None
                if "application/json" not in response.headers.get("Content-Type", ""):
                    raise HubError("Expected stateless JSON MCP response")
                result = json.loads(raw)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise HubError(f"Hub HTTP request rejected ({code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise HubError("Hub returned an invalid response or is unavailable") from None
        if not isinstance(result, dict) or result.get("id") != request_id or result.get("jsonrpc") != "2.0":
            raise HubError("Invalid MCP response envelope")
        if "error" in result:
            raise HubError("Hub rejected the MCP operation")
        if not isinstance(result.get("result"), dict):
            raise HubError("Missing MCP result")
        return result["result"]

    def health(self):
        init = self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "relay-core", "version": "0.1.0"}}, 1)
        protocol = init.get("protocolVersion")
        if protocol != "2025-06-18":
            raise HubError("Unsupported negotiated MCP version")
        self.protocol = protocol
        self._request("notifications/initialized", {})
        result = self._request("tools/call", {"name": "health.get", "arguments": {}}, 2)
        if result.get("isError"):
            raise HubError("Hub health check failed")
        payload = result.get("structuredContent")
        if not isinstance(payload, dict) or payload.get("status") != "ready" or payload.get("service") != "relay_hub":
            raise HubError("Unexpected Hub health response")
        return payload
