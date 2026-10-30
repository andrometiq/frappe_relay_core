import unittest
from unittest.mock import patch

from relay_core import file_limits


def use_relay_file_limit():
    """Tests run without a site, so the site file size limit is the Relay limit."""
    patcher = patch('relay_core.file_limits.get_max_bytes', return_value=file_limits.MAX_BYTES)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
