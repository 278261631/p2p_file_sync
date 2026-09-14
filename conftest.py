import os
import sys

# Tests drive the signaling server over plaintext loopback.
os.environ.setdefault("PFS_ALLOW_INSECURE", "1")

sys.path.insert(0, os.path.dirname(__file__))
