"""Staqtapp-TDS — Temporal Directory System.

A content-neutral, directory-first virtual storage engine with radix routing,
Swiss-table-style indexing, chunking, persistence, telemetry, admin
observability, and optional Spiral-compatible trace/provenance support.
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
from staqtapp_tds.telemetry import DirectoryTelemetry, TelemetryLevel, TelemetryMode, TELEMETRY_DTYPE, TelemetryManager, TelemetrySnapshot, TelemetryPublisherThread
from staqtapp_tds.latency import LatencyPolicy, LatencyBucket, classify_latency, latency_ratio
from staqtapp_tds.capabilities import CapabilityRegistry, ZoneCapability
from staqtapp_tds.namespaces import ReservedNamespaces
from staqtapp_tds.result import TDSResult
from staqtapp_tds.variables import VariableControl, StalkState
from staqtapp_tds.errors import ErrorTelemetry, ErrorLogMode
from staqtapp_tds.serializers import PayloadKind, CompressionPolicy, SerializerDecision, choose_variable_kind, content_hash_bytes
from staqtapp_tds.invariants import InvariantEngine, InvariantReport, InvariantViolation, InvariantCode, INVARIANT_DTYPE
from staqtapp_tds.provenance import ProvenanceTag, ProvenanceClass, PROVENANCE_DTYPE
from staqtapp_tds.cluster import TDSClusterIdentity, CLUSTER_DTYPE, query_requires_selector
from staqtapp_tds.radix import RadixDirectoryRouter
from staqtapp_tds.config import RuntimeConfig, AdminConfig, ConfigRegistry
from staqtapp_tds.secure import SecureParams
from staqtapp_tds.crypto import CryptoProvider, NoopCryptoProvider, XorCryptoProvider
from staqtapp_tds.spiral import TraceRecord, TraceSetManifest, AggregationRecord, SpiralRun, SpiralRunMetadata, create_spiral_run
from staqtapp_tds.verify import HealthCheck, HealthReport, HealthVerifier, verify
from staqtapp_tds.asi import PressureMode, VFSState, ChunkState, PressureSnapshot, estimate_pressure
from staqtapp_tds.pressure import calculate_pressure_snapshot, PressureComponent, PressureCalculationSnapshot
from staqtapp_tds.recovery import RecoveryAction, RecoveryPlan, build_recovery_plan
from staqtapp_tds.diagnostics import DiagnosticEvent, NativeDiagnosticSnapshot, native_diagnostics_available, native_diag_snapshot, native_diag_reset, native_diag_set_enabled, native_diag_mark_degraded, native_diag_emit

from staqtapp_tds.version import __version__, VERSION
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
    # semantic infrastructure
    "ManifestPolicy", "MANIFEST_FILENAME", "load_manifest", "write_default_manifest",
    "SRZMetadata", "SRZ_DTYPE", "route_id_for",
    "DirectoryTelemetry", "TelemetryLevel", "TelemetryMode", "TELEMETRY_DTYPE", "TelemetryManager", "TelemetrySnapshot", "TelemetryPublisherThread",
    "LatencyPolicy", "LatencyBucket", "classify_latency", "latency_ratio",
    "CapabilityRegistry", "ZoneCapability", "ReservedNamespaces",
    "TDSResult", "VariableControl", "StalkState", "ErrorTelemetry", "ErrorLogMode",
    "PayloadKind", "CompressionPolicy", "SerializerDecision", "choose_variable_kind", "content_hash_bytes",
    "InvariantEngine", "InvariantReport", "InvariantViolation", "InvariantCode", "INVARIANT_DTYPE",
    "ProvenanceTag", "ProvenanceClass", "PROVENANCE_DTYPE",
    "TDSClusterIdentity", "CLUSTER_DTYPE", "query_requires_selector", "RadixDirectoryRouter",
    "RuntimeConfig", "AdminConfig", "ConfigRegistry", "SecureParams", "CryptoProvider", "NoopCryptoProvider", "XorCryptoProvider",
    "TraceRecord", "TraceSetManifest", "AggregationRecord", "SpiralRun", "SpiralRunMetadata", "create_spiral_run", "HealthCheck", "HealthReport", "HealthVerifier", "verify", "VERSION", "PressureMode", "VFSState", "ChunkState", "PressureSnapshot", "estimate_pressure", "DiagnosticEvent", "NativeDiagnosticSnapshot", "native_diagnostics_available", "native_diag_snapshot", "native_diag_reset", "native_diag_set_enabled", "native_diag_mark_degraded", "native_diag_emit", "calculate_pressure_snapshot", "PressureComponent", "PressureCalculationSnapshot", "RecoveryAction", "RecoveryPlan", "build_recovery_plan",
]
