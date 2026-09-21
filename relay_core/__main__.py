import json
import sys
from .hub import HubClient, HubError

if sys.argv[1:] != ["check-hub"]:
    raise SystemExit("Usage: python3 -m relay_core check-hub")
try:
    print(json.dumps(HubClient.from_env().health()))
except (HubError, ValueError, OSError):
    raise SystemExit("Hub check failed; verify local .env and Hub availability") from None
