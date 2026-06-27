"""
Staqtapp-TDS — Temporal Directory System
VFS for ASI-scale computation. v1.7.1

New in v1.7.1: src-layout repo, EntryIndex facade, backend package, native-extension seam, and arena module split.

Performance uplift over v1.2.0 (all v1.2.0 bug fixes retained)
──────────────────────────────────────────────────────────────────
  NEW NUMBA KERNELS
  - _compute_entry_score_bulk    fused decay score; no temp allocation
  - _batch_adler32_seed          vectorised Adler-32 over key batches
  - _slot_offsets_cumsum         prefix-sum for slot index serialisation
  - _bloom_bits_add              JIT Bloom add (eliminates Python loop)
  - _bloom_bits_query            JIT Bloom query (eliminates Python loop)
  - _pack_slot_fixed_batch       JIT 24-byte slot header packer
  PARALLELISED EXISTING KERNELS
  - _probability_decay           prange (was sequential range)
  - _matrix_symbol_swap          prange (was sequential range)

  REGISTRY (HybridRegistry)
  - Score arrays cached; rebuilt only on structural change (dirty flag)
  - Eviction calls fused JIT kernel; no per-eviction allocation

  LOOP CACHE
  - Power-of-two cycle → bitwise AND instead of modulo (zero-branch path)

  BLOOM FILTER
  - add() / __contains__() delegate to JIT kernels
  - bits stored as np.ndarray (JIT-compatible; no Python list)

  COMPRESSOR REGISTRY
  - Direct fn refs cached; eliminates dict lookup on every call

  DIRECTORY I/O
  - to_bytes() parallelises entry serialisation via thread pool
  - read() registry check moved outside the lock (lock-free hot path)
  - parallel_read_all() pre-sizes result dict

  PERSISTENCE
  - SlotIndex.to_bytes() uses JIT kernel for fixed 24-byte headers
  - SlotIndex.from_bytes() uses memoryview; no redundant byte copies
  - TDSWriter._finalise(): single pre-allocated bytearray + one os.write()
  - TDSWriter.write_parallel(): ordered futures; result list preserves order
  - TDSPersistence.flush(): BFS deque (no recursion depth risk)
  - TDSPersistence.load_node(): direct record iteration (half the dict ops)
"""

from staqtapp_tds.tds_filesystem import (
    TDSFileSystem,
    TDSDirectory,
    TDSEntry,
    FmtID,
    DirFlags,
    HybridRegistry,
    REGISTRY_DTYPE,
    SharedMemoryArena,
    EntryIndex,
    LoopCacheManager,
    LoopCacheSlot,
    ConcurrencyPool,
    SymbolTable,
    BloomFilter,
    CompressorRegistry,
    EntrySchema,
    WriteAheadLog,
    encode_header,
    decode_header,
    HEADER_SIZE,
    TDS_MAGIC,
)

from staqtapp_tds.tds_persistence import (
    TDSReader,
    TDSWriter,
    TDSPersistence,
    ParallelFlusher,
    SlotIndex,
    SlotRecord,
    FILE_HDR_SIZE,
    FILE_MAGIC,
)

from staqtapp_tds.manifest import (
    ManifestPolicy, MANIFEST_FILENAME, load_manifest, write_default_manifest,
)
from staqtapp_tds.srz import SRZMetadata, SRZ_DTYPE, route_id_for
from staqtapp_tds.telemetry import DirectoryTelemetry, TelemetryMode, TELEMETRY_DTYPE
from staqtapp_tds.latency import LatencyPolicy, LatencyBucket, classify_latency, latency_ratio
from staqtapp_tds.capabilities import CapabilityRegistry, ZoneCapability
from staqtapp_tds.namespaces import ReservedNamespaces

__version__ = "1.7.1"
__all__ = [
    # filesystem
    "TDSFileSystem", "TDSDirectory", "TDSEntry",
    "FmtID", "DirFlags",
    "HybridRegistry", "REGISTRY_DTYPE", "SharedMemoryArena", "EntryIndex", "LoopCacheManager", "LoopCacheSlot",
    "ConcurrencyPool", "SymbolTable",
    "BloomFilter", "CompressorRegistry", "EntrySchema", "WriteAheadLog",
    "encode_header", "decode_header",
    "HEADER_SIZE", "TDS_MAGIC",
    # persistence
    "TDSReader", "TDSWriter", "TDSPersistence", "ParallelFlusher",
    "SlotIndex", "SlotRecord",
    "FILE_HDR_SIZE", "FILE_MAGIC",
    # v1.7 semantic infrastructure
    "ManifestPolicy", "MANIFEST_FILENAME", "load_manifest", "write_default_manifest",
    "SRZMetadata", "SRZ_DTYPE", "route_id_for",
    "DirectoryTelemetry", "TelemetryMode", "TELEMETRY_DTYPE",
    "LatencyPolicy", "LatencyBucket", "classify_latency", "latency_ratio",
    "CapabilityRegistry", "ZoneCapability", "ReservedNamespaces",
]
