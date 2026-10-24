"""Readable labels and plausible, local-only identities for site simulations."""
from datetime import datetime, timezone
import hashlib
import secrets


def run_label():
    # Words distinguish reruns in the same UTC minute without timestamp-heavy names.
    words = ('cedar', 'maple', 'birch', 'willow', 'elm', 'ash', 'pine', 'oak', 'fir', 'alder', 'beech', 'olive')
    return datetime.now(timezone.utc).strftime('R%m%d-%H%M') + '-' + '-'.join(secrets.choice(words) for _ in range(3))


def phone(label):
    return '919' + str(int(hashlib.sha256(label.encode()).hexdigest()[:12], 16) % 1_000_000_000).zfill(9)
