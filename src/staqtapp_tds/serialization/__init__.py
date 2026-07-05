"""First-class Serialization Manager for Staqtapp-TDS.

The storage engine stores bytes.  This subsystem owns the policy that turns
Python values into bytes and back again for addvar/loadvar/read paths.
"""

from staqtapp_tds.serialization.manager import (
    EncodedPayload,
    SerializationCodec,
    CodecRegistry,
    SerializationManager,
    get_default_serialization_manager,
)

__all__ = [
    "EncodedPayload",
    "SerializationCodec",
    "CodecRegistry",
    "SerializationManager",
    "get_default_serialization_manager",
]
