"""Project-local configuration, parsed literally; never executed as shell code."""
from pathlib import Path
import os

KEYS = {"RELAY_HUB_URL", "RELAY_HUB_TOKEN"}


def load_env(path: str | Path = ".env") -> dict[str, str]:
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in KEYS or key in values:
            raise ValueError(f"Invalid .env key at line {number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed .env quote at line {number}")
            value = value[1:-1]
        if "\x00" in value:
            raise ValueError(f"Invalid .env value at line {number}")
        values[key] = value
    return {key: os.environ.get(key, values.get(key, "")) for key in KEYS}
