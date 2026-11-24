import unittest
from unittest.mock import patch

from relay_core import file_limits
from relay_core.hub import MAX_WHATSAPP_DOWNLOAD_BYTES


def use_relay_file_limit():
    """Tests run without a site, so the site file size limit is the Relay or Hub download limit."""
    for name, limit in (('get_max_bytes', file_limits.MAX_BYTES), ('get_received_max_bytes', MAX_WHATSAPP_DOWNLOAD_BYTES)):
        patcher = patch('relay_core.file_limits.' + name, return_value=limit)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)
