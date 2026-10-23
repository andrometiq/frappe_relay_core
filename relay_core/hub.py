"""Server-side client for provisioned, account-scoped Hub API tokens.

Tokens belong to Hub users, carry explicit scopes and never enter browser code.
"""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .config import load_env


class HubError(RuntimeError):
    def __init__(self, message, metadata=None):
        super().__init__(message)
        self.metadata = {}
        if not isinstance(metadata, dict) or metadata.get('provider') not in ('Telegram','WhatsApp','Hub'):
            return
        source = metadata.get('error')
        if not isinstance(source, dict):
            return
        safe = {}
        for key in ('http_status', 'code', 'retry_after', 'migrate_to_chat_id'):
            value = source.get(key)
            if type(value) is int and abs(value) < 2**52 and (key == 'migrate_to_chat_id' or value >= 0):
                safe[key] = value
        if type(source.get('outcome_unknown')) is bool:
            safe['outcome_unknown'] = source['outcome_unknown']
        if safe:
            self.metadata = {'provider': metadata['provider'], 'error': safe}


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
        if not parsed.hostname or not parsed.path.endswith("/mcp") or any(part in {".", ".."} for part in parsed.path.split("/")) or "%" in parsed.path or "//" in parsed.path:
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
            with self.opener.open(req, timeout=30) as response:
                limit = 6 * 1024 * 1024 if method == 'tools/call' and params.get('name') in ('telegram.attachment','email.attachment','whatsapp.attachment') else 3 * 1024 * 1024 if method == 'tools/call' and params.get('name') in ('telegram.media', 'whatsapp.media') else 2097152
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise HubError("Hub response exceeds size limit")
                if request_id is None:
                    return None
                if "application/json" not in response.headers.get("Content-Type", ""):
                    raise HubError("Expected stateless JSON MCP response")
                result = json.loads(raw)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401,403):
                raise HubError("Hub connection is not authorized. Update the saved Hub API credential in Relay Settings.",
                    {'provider':'Hub','error':{'http_status':code,'outcome_unknown':False}}) from None
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

    def initialize(self):
        init = self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "relay-core", "version": "0.1.0"}}, 1)
        protocol = init.get("protocolVersion")
        if protocol != "2025-06-18":
            raise HubError("Unsupported negotiated MCP version")
        self.protocol = protocol
        self._request("notifications/initialized", {})
    def execute(self, arguments):
        return self.call_tool("whatsapp.execute", arguments)

    def call_tool(self, name, arguments):
        if name not in {"account.get", "whatsapp.execute", "whatsapp.enqueue", "whatsapp.send", "whatsapp.bulk", "whatsapp.deliveries", "whatsapp.resolve", "whatsapp.media", "telegram.send", "telegram.typing", "telegram.groups", "telegram.message", "telegram.media", "email.send", "channels.deliveries", "channels.resolve", "telegram.attachment", "email.attachment", "email.mailbox", "whatsapp.attachment"}:
            raise HubError("Unsupported Hub tool")
        if not self.protocol:
            self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments}, 2)
        if result.get("isError"):
            raise HubError("Hub operation was rejected; check account capabilities and request details", result.get('structuredContent'))
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            raise HubError("Unexpected Hub response")
        return payload

    def telegram_send(self, chat_id, text, reply_to=0, message_thread_id=0, request_key=None):
        arguments = {"chat_id": chat_id, "text": text, "reply_to": reply_to}
        if message_thread_id:
            arguments['message_thread_id'] = message_thread_id
        if request_key: arguments["request_key"] = request_key
        return self.call_tool("telegram.message", dict(arguments, operation="text"))

    def telegram_groups(self, operation, **arguments):
        return self.call_tool('telegram.groups', {'operation': operation, **arguments})

    def telegram_execute(self, operation, **arguments):
        return self.telegram_groups(operation, **arguments)

    def telegram_message(self, **arguments):
        return self.call_tool('telegram.message', arguments)

    def media(self, provider, file_id):
        if provider == 'Telegram':
            return self.call_tool('telegram.media', {'file_id': file_id})
        if provider == 'WhatsApp':
            return self.call_tool('whatsapp.media', {'media_id': file_id})
        raise HubError('Unsupported media provider')

    def email_send(self, to, subject, body, cc=None, bcc=None, request_key=None):
        return self.call_tool("email.send", {"to": to, "subject": subject, "body": body, "cc": cc or [], "bcc": bcc or [], **({"request_key":request_key} if request_key else {})})

    def health(self):
        self.initialize()
        result = self._request("tools/call", {"name": "health.get", "arguments": {}}, 2)
        if result.get("isError"):
            raise HubError("Hub health check failed")
        payload = result.get("structuredContent")
        if not isinstance(payload, dict) or payload.get("status") != "ready" or payload.get("service") != "relay_hub":
            raise HubError("Unexpected Hub health response")
        return payload
