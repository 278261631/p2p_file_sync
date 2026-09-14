"""TLS context for the signaling WebSocket client.

Verification uses certifi's CA bundle rather than the operating system trust
store.  System stores can contain expired or stale intermediates that OpenSSL
prefers over the valid ones a server sends, which surfaces as a spurious
``certificate has expired`` error (seen on Windows).  ``PFS_TLS_CA`` overrides
the bundle with a custom CA file, e.g. for an internal or self-signed CA.
"""

from __future__ import annotations

import os
import ssl


def build_client_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that verifies against certifi (or ``PFS_TLS_CA``)."""
    ca_file = os.environ.get("PFS_TLS_CA")
    if not ca_file:
        try:
            import certifi

            ca_file = certifi.where()
        except ImportError:
            ca_file = None

    if ca_file:
        # Passing cafile makes OpenSSL load *only* that bundle, bypassing the
        # system store entirely.
        return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()
