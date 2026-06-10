"""MAX platform plugin for Hermes Agent.

MVP step 2: discover the plugin, validate MAX_BOT_TOKEN, run long polling.
No message dispatch to gateway (F-05b), no send (F-06).
"""

from .adapter import register

__all__ = ["register"]
