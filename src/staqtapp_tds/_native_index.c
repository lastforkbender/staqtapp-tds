#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>

typedef struct {
    char *key;
    Py_ssize_t len;
    int64_t handle;
    uint8_t state; /* 0 empty, 1 full, 2 tombstone */
    uint8_t ctrl;  /* Swiss-table style 7-bit hash fingerprint */
    uint64_t hash;
} Slot;

typedef struct KeyNode {
    struct KeyNode *next;
} KeyNode;

typedef struct {
    KeyNode *free_list;
    Py_ssize_t block_size;
    uint64_t reuse_count;
    uint64_t allocator_calls;
    uint64_t frees_to_pool;
} TinyKeyPool;

typedef struct {
    PyObject_HEAD
    Slot *slots;
    Py_ssize_t capacity;
    Py_ssize_t size;
    Py_ssize_t tombstones;
    int64_t next_handle;
    uint64_t resize_count;
    uint64_t native_put_calls;
    uint64_t native_batch_put_calls;
    uint64_t native_lookup_calls;
    uint64_t native_batch_lookup_calls;
    uint64_t native_pop_calls;
    uint64_t native_batch_pop_calls;
    uint64_t native_stats_calls;
    uint64_t native_checksum_calls;
    uint64_t native_chunk_scan_calls;
    uint64_t gil_released_calls;
    uint64_t python_native_transitions;
    TinyKeyPool key_pool;
    pthread_rwlock_t lock;
} NativeHandleIndex;


/* =============================================================================
 * v2.7.1 Native Diagnostic Engine transition ring
 *
 * This subsystem owns no storage objects and never mutates storage state.  Hot
 * paths update only bounded atomic counters and tiny transition-event copies.
 * Snapshot assembly is performed only from module-level diagnostic state while
 * the Python caller already owns the GIL; no storage locks or Python callbacks
 * are used by diagnostic hot-path hooks.
 * ============================================================================= */

typedef enum {
    DIAG_EVENT_GIL_RELEASED = 1,
    DIAG_EVENT_GIL_REACQUIRED = 2,
    DIAG_EVENT_CHUNK_SEALED = 3,
    DIAG_EVENT_CHUNK_VERIFIED = 4,
    DIAG_EVENT_CHUNK_QUARANTINED = 5,
    DIAG_EVENT_PRESSURE_MODE_CHANGED = 6,
    DIAG_EVENT_SNAPSHOT_DROPPED = 7,
    DIAG_EVENT_RECOVERY_STARTED = 8,
    DIAG_EVENT_RECOVERY_COMPLETED = 9,
    DIAG_EVENT_NATIVE_OPERATION = 10,
    DIAG_EVENT_RING_OVERFLOW = 11,
    DIAG_EVENT_SLOT_ALLOCATED = 20,
    DIAG_EVENT_SLOT_WRITTEN = 21,
    DIAG_EVENT_SLOT_UPDATED = 22,
    DIAG_EVENT_SLOT_DELETED = 23,
    DIAG_EVENT_SLOT_VISIBLE = 24,
    DIAG_EVENT_INDEX_RESIZED = 30,
    DIAG_EVENT_INDEX_LOOKUP_HIT = 31,
    DIAG_EVENT_INDEX_LOOKUP_MISS = 32,
    DIAG_EVENT_LOCK_WAIT = 40,
    DIAG_EVENT_LOCK_ACQUIRED = 41,
    DIAG_EVENT_LOCK_RELEASED = 42,
    DIAG_EVENT_MEMORY_POOL_REUSED = 50,
    DIAG_EVENT_MEMORY_POOL_ALLOCATED = 51,
    DIAG_EVENT_MEMORY_POOL_FREED = 52,
    DIAG_EVENT_SNAPSHOT_MARKER = 60
} DiagEventCode;

typedef enum {
    DIAG_COUNTER_GIL_RELEASED_CALLS = 0,
    DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS = 1,
    DIAG_COUNTER_NATIVE_PUT_CALLS = 2,
    DIAG_COUNTER_NATIVE_BATCH_PUT_CALLS = 3,
    DIAG_COUNTER_NATIVE_LOOKUP_CALLS = 4,
    DIAG_COUNTER_NATIVE_BATCH_LOOKUP_CALLS = 5,
    DIAG_COUNTER_NATIVE_POP_CALLS = 6,
    DIAG_COUNTER_NATIVE_BATCH_POP_CALLS = 7,
    DIAG_COUNTER_NATIVE_STATS_CALLS = 8,
    DIAG_COUNTER_NATIVE_CHECKSUM_CALLS = 9,
    DIAG_COUNTER_NATIVE_CHECKSUM_BATCH_CALLS = 10,
    DIAG_COUNTER_NATIVE_CHUNK_SCAN_CALLS = 11,
    DIAG_COUNTER_SNAPSHOT_REQUESTS = 12,
    DIAG_COUNTER_SNAPSHOT_BUILT = 13,
    DIAG_COUNTER_EVENTS_EMITTED = 14,
    DIAG_COUNTER_EVENTS_DROPPED = 15,
    DIAG_COUNTER_DEGRADED = 16,
    DIAG_COUNTER_RING_CAPACITY = 17,
    DIAG_COUNTER_RING_OCCUPANCY = 18,
    DIAG_COUNTER_SLOT_TRANSITIONS = 19,
    DIAG_COUNTER_INDEX_TRANSITIONS = 20,
    DIAG_COUNTER_LOCK_TRANSITIONS = 21,
    DIAG_COUNTER_MEMORY_TRANSITIONS = 22,
    DIAG_COUNTER_SNAPSHOT_MARKERS = 23,
    DIAG_COUNTER_EVENT_RING_WRAPAROUNDS = 24,
    DIAG_COUNTER_MAX = 40
} DiagCounter;

typedef struct {
    uint64_t seq;
    uint64_t timestamp_ns;
    uint32_t code;
    uint32_t flags;
    uint32_t subsystem;
    uint32_t object_id;
    uint64_t value_a;
    uint64_t value_b;
} TDSDiagEvent;

#define TDS_DIAG_RING_CAPACITY 4096

static volatile uint64_t g_diag_enabled = 1;
static volatile uint64_t g_diag_degraded = 0;
static volatile uint64_t g_diag_sequence = 0;
static volatile uint64_t g_diag_counters[DIAG_COUNTER_MAX];
static TDSDiagEvent g_diag_ring[TDS_DIAG_RING_CAPACITY];

static uint64_t diag_now_ns(void) {
#if defined(CLOCK_MONOTONIC)
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0) {
        return ((uint64_t)ts.tv_sec * 1000000000ULL) + (uint64_t)ts.tv_nsec;
    }
#endif
    return (uint64_t)time(NULL) * 1000000000ULL;
}

static inline uint64_t diag_atomic_add(volatile uint64_t *ptr, uint64_t value) {
#if defined(__GNUC__) || defined(__clang__)
    return __sync_fetch_and_add(ptr, value);
#else
    uint64_t old = *ptr;
    *ptr += value;
    return old;
#endif
}

static inline uint64_t diag_atomic_get(volatile uint64_t *ptr) {
#if defined(__GNUC__) || defined(__clang__)
    return __sync_fetch_and_add(ptr, 0);
#else
    return *ptr;
#endif
}

static inline void diag_counter_add(DiagCounter counter, uint64_t value) {
    if (!diag_atomic_get(&g_diag_enabled)) return;
    if (counter >= 0 && counter < DIAG_COUNTER_MAX) diag_atomic_add(&g_diag_counters[counter], value);
}

static inline void diag_emit_transition(DiagEventCode code, uint32_t subsystem, uint32_t object_id, uint64_t value_a, uint64_t value_b, uint32_t flags) {
    if (!diag_atomic_get(&g_diag_enabled)) return;
    uint64_t seq = diag_atomic_add(&g_diag_sequence, 1) + 1;
    uint64_t idx = (seq - 1) % TDS_DIAG_RING_CAPACITY;
    g_diag_ring[idx].seq = seq;
    g_diag_ring[idx].timestamp_ns = diag_now_ns();
    g_diag_ring[idx].code = (uint32_t)code;
    g_diag_ring[idx].flags = flags;
    g_diag_ring[idx].subsystem = subsystem;
    g_diag_ring[idx].object_id = object_id;
    g_diag_ring[idx].value_a = value_a;
    g_diag_ring[idx].value_b = value_b;
    diag_counter_add(DIAG_COUNTER_EVENTS_EMITTED, 1);
    if (seq > TDS_DIAG_RING_CAPACITY) {
        diag_counter_add(DIAG_COUNTER_EVENTS_DROPPED, 1);
        diag_counter_add(DIAG_COUNTER_EVENT_RING_WRAPAROUNDS, 1);
    }
}

static inline void diag_emit_event(DiagEventCode code, uint64_t value_a, uint64_t value_b) {
    diag_emit_transition(code, 0, 0, value_a, value_b, 0);
}

static inline void diag_count_transition(DiagEventCode code) {
    if (code >= DIAG_EVENT_SLOT_ALLOCATED && code <= DIAG_EVENT_SLOT_VISIBLE) diag_counter_add(DIAG_COUNTER_SLOT_TRANSITIONS, 1);
    else if (code >= DIAG_EVENT_INDEX_RESIZED && code <= DIAG_EVENT_INDEX_LOOKUP_MISS) diag_counter_add(DIAG_COUNTER_INDEX_TRANSITIONS, 1);
    else if (code >= DIAG_EVENT_LOCK_WAIT && code <= DIAG_EVENT_LOCK_RELEASED) diag_counter_add(DIAG_COUNTER_LOCK_TRANSITIONS, 1);
    else if (code >= DIAG_EVENT_MEMORY_POOL_REUSED && code <= DIAG_EVENT_MEMORY_POOL_FREED) diag_counter_add(DIAG_COUNTER_MEMORY_TRANSITIONS, 1);
    else if (code == DIAG_EVENT_SNAPSHOT_MARKER) diag_counter_add(DIAG_COUNTER_SNAPSHOT_MARKERS, 1);
}

static inline void diag_note_gil_released(DiagCounter op_counter) {
    diag_counter_add(DIAG_COUNTER_GIL_RELEASED_CALLS, 1);
    diag_counter_add(DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS, 1);
    diag_counter_add(op_counter, 1);
    diag_emit_transition(DIAG_EVENT_GIL_RELEASED, 1, 0, (uint64_t)op_counter, 0, 0);
}

static PyObject *diag_counter_dict(void) {
    PyObject *d = PyDict_New();
    if (!d) return NULL;
#define SETU64(name, idx) do { PyObject *_o = PyLong_FromUnsignedLongLong((unsigned long long)diag_atomic_get(&g_diag_counters[(idx)])); if (!_o || PyDict_SetItemString(d, (name), _o) < 0) { Py_XDECREF(_o); Py_DECREF(d); return NULL; } Py_DECREF(_o); } while(0)
    SETU64("gil_released_calls", DIAG_COUNTER_GIL_RELEASED_CALLS);
    SETU64("python_native_transitions", DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS);
    SETU64("native_put_calls", DIAG_COUNTER_NATIVE_PUT_CALLS);
    SETU64("native_batch_put_calls", DIAG_COUNTER_NATIVE_BATCH_PUT_CALLS);
    SETU64("native_lookup_calls", DIAG_COUNTER_NATIVE_LOOKUP_CALLS);
    SETU64("native_batch_lookup_calls", DIAG_COUNTER_NATIVE_BATCH_LOOKUP_CALLS);
    SETU64("native_pop_calls", DIAG_COUNTER_NATIVE_POP_CALLS);
    SETU64("native_batch_pop_calls", DIAG_COUNTER_NATIVE_BATCH_POP_CALLS);
    SETU64("native_stats_calls", DIAG_COUNTER_NATIVE_STATS_CALLS);
    SETU64("native_checksum_calls", DIAG_COUNTER_NATIVE_CHECKSUM_CALLS);
    SETU64("native_checksum_batch_calls", DIAG_COUNTER_NATIVE_CHECKSUM_BATCH_CALLS);
    SETU64("native_chunk_scan_calls", DIAG_COUNTER_NATIVE_CHUNK_SCAN_CALLS);
    SETU64("snapshot_requests", DIAG_COUNTER_SNAPSHOT_REQUESTS);
    SETU64("snapshot_built", DIAG_COUNTER_SNAPSHOT_BUILT);
    SETU64("events_emitted", DIAG_COUNTER_EVENTS_EMITTED);
    SETU64("events_dropped", DIAG_COUNTER_EVENTS_DROPPED);
    SETU64("degraded_count", DIAG_COUNTER_DEGRADED);
    SETU64("ring_capacity", DIAG_COUNTER_RING_CAPACITY);
    SETU64("ring_occupancy", DIAG_COUNTER_RING_OCCUPANCY);
    SETU64("slot_transitions", DIAG_COUNTER_SLOT_TRANSITIONS);
    SETU64("index_transitions", DIAG_COUNTER_INDEX_TRANSITIONS);
    SETU64("lock_transitions", DIAG_COUNTER_LOCK_TRANSITIONS);
    SETU64("memory_transitions", DIAG_COUNTER_MEMORY_TRANSITIONS);
    SETU64("snapshot_markers", DIAG_COUNTER_SNAPSHOT_MARKERS);
    SETU64("event_ring_wraparounds", DIAG_COUNTER_EVENT_RING_WRAPAROUNDS);
#undef SETU64
    return d;
}

static PyObject *diag_event_list(Py_ssize_t limit) {
    uint64_t seq = diag_atomic_get(&g_diag_sequence);
    Py_ssize_t available = (Py_ssize_t)((seq < TDS_DIAG_RING_CAPACITY) ? seq : TDS_DIAG_RING_CAPACITY);
    if (limit < 0 || limit > available) limit = available;
    PyObject *list = PyList_New(0);
    if (!list) return NULL;
    uint64_t start = seq >= (uint64_t)limit ? seq - (uint64_t)limit + 1 : 1;
    for (Py_ssize_t i = 0; i < limit; ++i) {
        uint64_t wanted = start + (uint64_t)i;
        TDSDiagEvent ev = g_diag_ring[(wanted - 1) % TDS_DIAG_RING_CAPACITY];
        if (ev.seq != wanted) continue;
        PyObject *d = Py_BuildValue("{s:K,s:K,s:I,s:I,s:I,s:I,s:K,s:K}",
                                    "seq", (unsigned long long)ev.seq,
                                    "timestamp_ns", (unsigned long long)ev.timestamp_ns,
                                    "code", (unsigned int)ev.code,
                                    "flags", (unsigned int)ev.flags,
                                    "subsystem", (unsigned int)ev.subsystem,
                                    "object_id", (unsigned int)ev.object_id,
                                    "value_a", (unsigned long long)ev.value_a,
                                    "value_b", (unsigned long long)ev.value_b);
        if (!d) { Py_DECREF(list); return NULL; }
        if (PyList_Append(list, d) < 0) { Py_DECREF(d); Py_DECREF(list); return NULL; }
        Py_DECREF(d);
    }
    return list;
}

static PyObject *module_diag_snapshot(PyObject *self, PyObject *args, PyObject *kwargs) {
    Py_ssize_t event_limit = 32;
    static char *kwlist[] = {"event_limit", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|n", kwlist, &event_limit)) return NULL;
    if (event_limit < 0) event_limit = 0;
    if (event_limit > TDS_DIAG_RING_CAPACITY) event_limit = TDS_DIAG_RING_CAPACITY;
    diag_counter_add(DIAG_COUNTER_SNAPSHOT_REQUESTS, 1);
    uint64_t started = diag_now_ns();
    uint64_t seq_for_occ = diag_atomic_get(&g_diag_sequence);
    g_diag_counters[DIAG_COUNTER_RING_CAPACITY] = TDS_DIAG_RING_CAPACITY;
    g_diag_counters[DIAG_COUNTER_RING_OCCUPANCY] = seq_for_occ < TDS_DIAG_RING_CAPACITY ? seq_for_occ : TDS_DIAG_RING_CAPACITY;
    PyObject *counters = diag_counter_dict();
    if (!counters) return NULL;
    PyObject *events = diag_event_list(event_limit);
    if (!events) { Py_DECREF(counters); return NULL; }
    diag_counter_add(DIAG_COUNTER_SNAPSHOT_BUILT, 1);
    if ((diag_atomic_get(&g_diag_counters[DIAG_COUNTER_SNAPSHOT_BUILT]) % 8ULL) == 0ULL) diag_emit_transition(DIAG_EVENT_SNAPSHOT_MARKER, 6, 0, seq_for_occ, (uint64_t)event_limit, 0);
    uint64_t elapsed = diag_now_ns() - started;
    PyObject *d = Py_BuildValue("{s:i,s:s,s:O,s:O,s:K,s:K,s:O,s:O}",
                                "schema_version", 1,
                                "subsystem", "native_diagnostics",
                                "enabled", diag_atomic_get(&g_diag_enabled) ? Py_True : Py_False,
                                "degraded", diag_atomic_get(&g_diag_degraded) ? Py_True : Py_False,
                                "sequence", (unsigned long long)diag_atomic_get(&g_diag_sequence),
                                "snapshot_build_ns", (unsigned long long)elapsed,
                                "counters", counters,
                                "recent_events", events);
    Py_DECREF(counters);
    Py_DECREF(events);
    return d;
}

static PyObject *module_diag_reset(PyObject *self, PyObject *Py_UNUSED(ignored)) {
    for (int i = 0; i < DIAG_COUNTER_MAX; ++i) g_diag_counters[i] = 0;
    g_diag_sequence = 0;
    g_diag_degraded = 0;
    memset(g_diag_ring, 0, sizeof(g_diag_ring));
    g_diag_counters[DIAG_COUNTER_RING_CAPACITY] = TDS_DIAG_RING_CAPACITY;
    Py_RETURN_NONE;
}

static PyObject *module_diag_set_enabled(PyObject *self, PyObject *args) {
    int enabled = 1;
    if (!PyArg_ParseTuple(args, "p", &enabled)) return NULL;
    g_diag_enabled = enabled ? 1 : 0;
    Py_RETURN_NONE;
}

static PyObject *module_diag_mark_degraded(PyObject *self, PyObject *args) {
    int degraded = 1;
    if (!PyArg_ParseTuple(args, "|p", &degraded)) return NULL;
    g_diag_degraded = degraded ? 1 : 0;
    if (degraded) diag_counter_add(DIAG_COUNTER_DEGRADED, 1);
    Py_RETURN_NONE;
}

static PyObject *module_diag_emit(PyObject *self, PyObject *args) {
    unsigned int code; unsigned long long a = 0, b = 0;
    if (!PyArg_ParseTuple(args, "I|KK", &code, &a, &b)) return NULL;
    diag_count_transition((DiagEventCode)code);
    diag_emit_transition((DiagEventCode)code, 0, 0, (uint64_t)a, (uint64_t)b, 0);
    Py_RETURN_NONE;
}


static uint64_t fnv1a64(const char *data, Py_ssize_t len) {
    uint64_t h = 1469598103934665603ULL;
    for (Py_ssize_t i = 0; i < len; ++i) {
        h ^= (unsigned char)data[i];
        h *= 1099511628211ULL;
    }
    return h ? h : 1;
}

static uint32_t fnv1a32(const char *data, Py_ssize_t len) {
    uint32_t h = 2166136261u;
    for (Py_ssize_t i = 0; i < len; ++i) {
        h ^= (unsigned char)data[i];
        h *= 16777619u;
    }
    return h ? h : 1u;
}

static Py_ssize_t round_pow2(Py_ssize_t n) {
    Py_ssize_t p = 16;
    while (p < n) p <<= 1;
    return p;
}

static inline uint8_t ctrl_from_hash(uint64_t hash) {
    uint8_t c = (uint8_t)((hash >> 57) & 0x7F);
    return c ? c : 1;
}

static inline void bump_u64(uint64_t *ptr) {
#if defined(__GNUC__) || defined(__clang__)
    __sync_fetch_and_add(ptr, 1);
#else
    (*ptr)++;
#endif
}

static void key_pool_init(TinyKeyPool *pool, Py_ssize_t block_size) {
    pool->free_list = NULL;
    pool->block_size = block_size;
    pool->reuse_count = 0;
    pool->allocator_calls = 0;
    pool->frees_to_pool = 0;
}

static char *key_alloc(NativeHandleIndex *self, Py_ssize_t len) {
    TinyKeyPool *pool = &self->key_pool;
    if (len > 0 && len <= pool->block_size && pool->free_list) {
        KeyNode *n = pool->free_list;
        pool->free_list = n->next;
        pool->reuse_count++;
        return (char*)n;
    }
    pool->allocator_calls++;
    return (char*)malloc((size_t)len);
}

static void key_free(NativeHandleIndex *self, char *ptr, Py_ssize_t len) {
    if (!ptr) return;
    TinyKeyPool *pool = &self->key_pool;
    if (len >= (Py_ssize_t)sizeof(KeyNode) && len <= pool->block_size) {
        KeyNode *n = (KeyNode*)ptr;
        n->next = pool->free_list;
        pool->free_list = n;
        pool->frees_to_pool++;
    } else {
        free(ptr);
    }
}

static void key_pool_destroy(TinyKeyPool *pool) {
    KeyNode *n = pool->free_list;
    while (n) {
        KeyNode *next = n->next;
        free(n);
        n = next;
    }
    pool->free_list = NULL;
}

static Py_ssize_t find_slot(Slot *slots, Py_ssize_t cap, const char *key, Py_ssize_t len, uint64_t hash, int *found) {
    Py_ssize_t mask = cap - 1;
    Py_ssize_t first_tomb = -1;
    Py_ssize_t idx = (Py_ssize_t)(hash & (uint64_t)mask);
    uint8_t ctrl = ctrl_from_hash(hash);
    for (Py_ssize_t probe = 0; probe < cap; ++probe) {
        Slot *s = &slots[idx];
        if (s->state == 0) {
            *found = 0;
            return first_tomb >= 0 ? first_tomb : idx;
        }
        if (s->state == 2) {
            if (first_tomb < 0) first_tomb = idx;
        } else if (s->ctrl == ctrl && s->hash == hash && s->len == len && memcmp(s->key, key, (size_t)len) == 0) {
            *found = 1;
            return idx;
        }
        idx = (idx + probe + 1) & mask;
    }
    *found = 0;
    return first_tomb >= 0 ? first_tomb : -1;
}

static Py_ssize_t probe_length_for_slot(Slot *slots, Py_ssize_t cap, Slot *target) {
    Py_ssize_t mask = cap - 1;
    Py_ssize_t idx = (Py_ssize_t)(target->hash & (uint64_t)mask);
    for (Py_ssize_t probe = 0; probe < cap; ++probe) {
        Slot *s = &slots[idx];
        if (s == target) return probe + 1;
        if (s->state == 0) return probe + 1;
        idx = (idx + probe + 1) & mask;
    }
    return cap;
}

static void free_slots(NativeHandleIndex *self, Slot *slots, Py_ssize_t cap) {
    if (!slots) return;
    for (Py_ssize_t i = 0; i < cap; ++i) {
        if (slots[i].state == 1 && slots[i].key) key_free(self, slots[i].key, slots[i].len);
    }
    free(slots);
}

static int resize_index(NativeHandleIndex *self, Py_ssize_t newcap) {
    newcap = round_pow2(newcap);
    Slot *newslots = (Slot*)calloc((size_t)newcap, sizeof(Slot));
    if (!newslots) return -1;
    for (Py_ssize_t i = 0; i < self->capacity; ++i) {
        Slot *old = &self->slots[i];
        if (old->state != 1) continue;
        int found = 0;
        Py_ssize_t idx = find_slot(newslots, newcap, old->key, old->len, old->hash, &found);
        if (idx < 0) { free(newslots); return -1; }
        newslots[idx] = *old;
        old->key = NULL;
        old->state = 0;
    }
    free_slots(self, self->slots, self->capacity);
    self->slots = newslots;
    self->capacity = newcap;
    self->tombstones = 0;
    self->resize_count++;
    diag_count_transition(DIAG_EVENT_INDEX_RESIZED);
    diag_emit_transition(DIAG_EVENT_INDEX_RESIZED, 3, 0, (uint64_t)newcap, self->resize_count, 0);
    return 0;
}

static int maybe_resize(NativeHandleIndex *self) {
    if ((self->size + self->tombstones) * 10 >= self->capacity * 7) {
        return resize_index(self, self->capacity * 2);
    }
    return 0;
}

static int put_handle_locked(NativeHandleIndex *self, const char *key, Py_ssize_t len, int64_t requested_handle, int64_t *out_handle) {
    if (maybe_resize(self) < 0) return -1;
    uint64_t hash = fnv1a64(key, len);
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    if (idx < 0) return -2;
    int64_t handle = requested_handle;
    if (found) {
        if (handle > 0) self->slots[idx].handle = handle;
        *out_handle = self->slots[idx].handle;
        diag_count_transition(DIAG_EVENT_SLOT_UPDATED);
        diag_emit_transition(DIAG_EVENT_SLOT_UPDATED, 2, (uint32_t)(idx & 0xffffffffU), (uint64_t)*out_handle, (uint64_t)len, 0);
        return 0;
    }
    char *copy = key_alloc(self, len);
    if (!copy) return -1;
    memcpy(copy, key, (size_t)len);
    if (handle <= 0) handle = self->next_handle++;
    self->slots[idx].key = copy;
    self->slots[idx].len = len;
    self->slots[idx].handle = handle;
    self->slots[idx].hash = hash;
    self->slots[idx].ctrl = ctrl_from_hash(hash);
    if (self->slots[idx].state == 2) self->tombstones--;
    self->slots[idx].state = 1;
    self->size++;
    *out_handle = handle;
    diag_count_transition(DIAG_EVENT_SLOT_ALLOCATED);
    diag_emit_transition(DIAG_EVENT_SLOT_ALLOCATED, 2, (uint32_t)(idx & 0xffffffffU), (uint64_t)handle, (uint64_t)len, 0);
    diag_count_transition(DIAG_EVENT_SLOT_WRITTEN);
    diag_emit_transition(DIAG_EVENT_SLOT_WRITTEN, 2, (uint32_t)(idx & 0xffffffffU), (uint64_t)handle, (uint64_t)self->size, 0);
    diag_count_transition(DIAG_EVENT_SLOT_VISIBLE);
    diag_emit_transition(DIAG_EVENT_SLOT_VISIBLE, 2, (uint32_t)(idx & 0xffffffffU), (uint64_t)handle, (uint64_t)self->size, 0);
    return 0;
}

static int put_handle_nogil(NativeHandleIndex *self, const char *key, Py_ssize_t len, int64_t requested_handle, int64_t *out_handle) {
    int rc;
    pthread_rwlock_wrlock(&self->lock);
    rc = put_handle_locked(self, key, len, requested_handle, out_handle);
    pthread_rwlock_unlock(&self->lock);
    return rc;
}

static int put_handles_nogil(NativeHandleIndex *self, const char **keys, Py_ssize_t *lens, Py_ssize_t n, int64_t *out) {
    int rc = 0;
    pthread_rwlock_wrlock(&self->lock);
    for (Py_ssize_t i = 0; i < n; ++i) {
        rc = put_handle_locked(self, keys[i], lens[i], 0, &out[i]);
        if (rc < 0) break;
    }
    pthread_rwlock_unlock(&self->lock);
    return rc;
}

static int64_t lookup_handle_locked(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    uint64_t hash = fnv1a64(key, len);
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    int64_t result = (idx >= 0 && found) ? self->slots[idx].handle : -1;
    diag_count_transition(result >= 0 ? DIAG_EVENT_INDEX_LOOKUP_HIT : DIAG_EVENT_INDEX_LOOKUP_MISS);
    diag_emit_transition(result >= 0 ? DIAG_EVENT_INDEX_LOOKUP_HIT : DIAG_EVENT_INDEX_LOOKUP_MISS, 3, (uint32_t)((idx >= 0 ? idx : 0) & 0xffffffffU), (uint64_t)(result >= 0 ? result : 0), (uint64_t)len, 0);
    return result;
}

static int64_t lookup_handle_nogil(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    int64_t out;
    pthread_rwlock_rdlock(&self->lock);
    out = lookup_handle_locked(self, key, len);
    pthread_rwlock_unlock(&self->lock);
    return out;
}

static void lookup_handles_nogil(NativeHandleIndex *self, const char **keys, Py_ssize_t *lens, Py_ssize_t n, int64_t *out) {
    pthread_rwlock_rdlock(&self->lock);
    for (Py_ssize_t i = 0; i < n; ++i) out[i] = lookup_handle_locked(self, keys[i], lens[i]);
    pthread_rwlock_unlock(&self->lock);
}

static int64_t pop_handle_locked(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    uint64_t hash = fnv1a64(key, len);
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    if (idx < 0 || !found) return -1;
    int64_t out = self->slots[idx].handle;
    key_free(self, self->slots[idx].key, self->slots[idx].len);
    self->slots[idx].key = NULL;
    self->slots[idx].len = 0;
    self->slots[idx].handle = 0;
    self->slots[idx].hash = 0;
    self->slots[idx].ctrl = 0;
    self->slots[idx].state = 2;
    self->size--;
    self->tombstones++;
    diag_count_transition(DIAG_EVENT_SLOT_DELETED);
    diag_emit_transition(DIAG_EVENT_SLOT_DELETED, 2, (uint32_t)(idx & 0xffffffffU), (uint64_t)out, (uint64_t)self->tombstones, 0);
    return out;
}

static int64_t pop_handle_nogil(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    int64_t out;
    pthread_rwlock_wrlock(&self->lock);
    out = pop_handle_locked(self, key, len);
    pthread_rwlock_unlock(&self->lock);
    return out;
}

static void pop_handles_nogil(NativeHandleIndex *self, const char **keys, Py_ssize_t *lens, Py_ssize_t n, int64_t *out) {
    pthread_rwlock_wrlock(&self->lock);
    for (Py_ssize_t i = 0; i < n; ++i) out[i] = pop_handle_locked(self, keys[i], lens[i]);
    pthread_rwlock_unlock(&self->lock);
}

static PyObject *NativeHandleIndex_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    NativeHandleIndex *self = (NativeHandleIndex*)type->tp_alloc(type, 0);
    if (!self) return NULL;
    memset((char*)self + sizeof(PyObject), 0, sizeof(NativeHandleIndex) - sizeof(PyObject));
    self->next_handle = 1;
    key_pool_init(&self->key_pool, 128);
    pthread_rwlock_init(&self->lock, NULL);
    return (PyObject*)self;
}

static int NativeHandleIndex_init(NativeHandleIndex *self, PyObject *args, PyObject *kwds) {
    Py_ssize_t capacity = 1024;
    static char *kwlist[] = {"capacity", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|n", kwlist, &capacity)) return -1;
    self->capacity = round_pow2(capacity);
    self->slots = (Slot*)calloc((size_t)self->capacity, sizeof(Slot));
    if (!self->slots) { PyErr_NoMemory(); return -1; }
    return 0;
}

static void NativeHandleIndex_dealloc(NativeHandleIndex *self) {
    pthread_rwlock_wrlock(&self->lock);
    free_slots(self, self->slots, self->capacity);
    self->slots = NULL;
    key_pool_destroy(&self->key_pool);
    pthread_rwlock_unlock(&self->lock);
    pthread_rwlock_destroy(&self->lock);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *NativeHandleIndex_put(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len; int64_t handle = 0;
    if (!PyArg_ParseTuple(args, "s#|L", &key, &len, &handle)) return NULL;
    if (len <= 0) { PyErr_SetString(PyExc_ValueError, "key must be non-empty bytes/str"); return NULL; }
    int rc; int64_t out_handle = -1;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_PUT_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_put_calls);
    Py_BEGIN_ALLOW_THREADS
    rc = put_handle_nogil(self, key, len, handle, &out_handle);
    Py_END_ALLOW_THREADS
    if (rc == -1) { PyErr_NoMemory(); return NULL; }
    if (rc == -2) { PyErr_SetString(PyExc_RuntimeError, "native index is full"); return NULL; }
    return PyLong_FromLongLong(out_handle);
}

static int extract_key_sequence(PyObject *seq, PyObject **fast_out, const char ***keys_out, Py_ssize_t **lens_out, Py_ssize_t *n_out) {
    PyObject *fast = PySequence_Fast(seq, "expected a sequence of bytes/str keys");
    if (!fast) return -1;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
    const char **keys = (const char**)calloc((size_t)n, sizeof(char*));
    Py_ssize_t *lens = (Py_ssize_t*)calloc((size_t)n, sizeof(Py_ssize_t));
    if (!keys || !lens) { free(keys); free(lens); Py_DECREF(fast); PyErr_NoMemory(); return -1; }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *item = PySequence_Fast_GET_ITEM(fast, i);
        if (PyBytes_Check(item)) {
            if (PyBytes_AsStringAndSize(item, (char**)&keys[i], &lens[i]) < 0) { free(keys); free(lens); Py_DECREF(fast); return -1; }
        } else if (PyUnicode_Check(item)) {
            keys[i] = PyUnicode_AsUTF8AndSize(item, &lens[i]);
            if (!keys[i]) { free(keys); free(lens); Py_DECREF(fast); return -1; }
        } else {
            free(keys); free(lens); Py_DECREF(fast);
            PyErr_SetString(PyExc_TypeError, "keys must be bytes or str");
            return -1;
        }
        if (lens[i] <= 0) { free(keys); free(lens); Py_DECREF(fast); PyErr_SetString(PyExc_ValueError, "keys must be non-empty"); return -1; }
    }
    *fast_out = fast; *keys_out = keys; *lens_out = lens; *n_out = n; return 0;
}

static PyObject *int64_list_from_array(int64_t *out, Py_ssize_t n) {
    PyObject *list = PyList_New(n);
    if (!list) return NULL;
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *v = PyLong_FromLongLong(out[i]);
        if (!v) { Py_DECREF(list); return NULL; }
        PyList_SET_ITEM(list, i, v);
    }
    return list;
}

static PyObject *NativeHandleIndex_put_many(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    PyObject *fast = NULL; const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &fast, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free((void*)keys); free(lens); Py_DECREF(fast); PyErr_NoMemory(); return NULL; }
    int rc;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_BATCH_PUT_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_put_calls);
    Py_BEGIN_ALLOW_THREADS
    rc = put_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    free((void*)keys); free(lens); Py_DECREF(fast);
    if (rc == -1) { free(out); PyErr_NoMemory(); return NULL; }
    if (rc == -2) { free(out); PyErr_SetString(PyExc_RuntimeError, "native index is full"); return NULL; }
    PyObject *list = int64_list_from_array(out, n);
    free(out);
    return list;
}

static PyObject *NativeHandleIndex_get_handle(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_LOOKUP_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_lookup_calls);
    Py_BEGIN_ALLOW_THREADS
    out = lookup_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_contains(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_LOOKUP_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_lookup_calls);
    Py_BEGIN_ALLOW_THREADS
    out = lookup_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    if (out >= 0) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *NativeHandleIndex_pop(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_POP_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_pop_calls);
    Py_BEGIN_ALLOW_THREADS
    out = pop_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_get_handles(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    PyObject *fast = NULL; const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &fast, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free((void*)keys); free(lens); Py_DECREF(fast); PyErr_NoMemory(); return NULL; }
    diag_note_gil_released(DIAG_COUNTER_NATIVE_BATCH_LOOKUP_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_lookup_calls);
    Py_BEGIN_ALLOW_THREADS
    lookup_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    PyObject *list = int64_list_from_array(out, n);
    free((void*)keys); free(lens); free(out); Py_DECREF(fast);
    return list;
}

static PyObject *NativeHandleIndex_pop_many(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    PyObject *fast = NULL; const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &fast, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free((void*)keys); free(lens); Py_DECREF(fast); PyErr_NoMemory(); return NULL; }
    diag_note_gil_released(DIAG_COUNTER_NATIVE_BATCH_POP_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_pop_calls);
    Py_BEGIN_ALLOW_THREADS
    pop_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    PyObject *list = int64_list_from_array(out, n);
    free((void*)keys); free(lens); free(out); Py_DECREF(fast);
    return list;
}

static PyObject *NativeHandleIndex_size(NativeHandleIndex *self, PyObject *Py_UNUSED(ignored)) {
    Py_ssize_t size;
    pthread_rwlock_rdlock(&self->lock);
    size = self->size;
    pthread_rwlock_unlock(&self->lock);
    return PyLong_FromSsize_t(size);
}

static void stats_scan_nogil(NativeHandleIndex *self, Py_ssize_t *size, Py_ssize_t *capacity,
                             Py_ssize_t *tombstones, int64_t *next_handle,
                             Py_ssize_t *max_probe, double *avg_probe) {
    pthread_rwlock_rdlock(&self->lock);
    *size = self->size; *capacity = self->capacity; *tombstones = self->tombstones; *next_handle = self->next_handle;
    *max_probe = 0; *avg_probe = 0.0;
    for (Py_ssize_t i = 0; i < self->capacity; ++i) {
        if (self->slots[i].state == 1) {
            Py_ssize_t p = probe_length_for_slot(self->slots, self->capacity, &self->slots[i]);
            if (p > *max_probe) *max_probe = p;
            *avg_probe += (double)p;
        }
    }
    if (*size > 0) *avg_probe /= (double)*size;
    pthread_rwlock_unlock(&self->lock);
}

static PyObject *NativeHandleIndex_stats(NativeHandleIndex *self, PyObject *Py_UNUSED(ignored)) {
    Py_ssize_t size = 0, capacity = 0, tombstones = 0, max_probe = 0;
    int64_t next_handle = 0;
    double avg_probe = 0.0;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_STATS_CALLS); bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_stats_calls);
    Py_BEGIN_ALLOW_THREADS
    stats_scan_nogil(self, &size, &capacity, &tombstones, &next_handle, &max_probe, &avg_probe);
    Py_END_ALLOW_THREADS
    PyObject *d = PyDict_New(); if (!d) return NULL;
#define SETOBJ(name, obj) do { PyObject *_o = (obj); if (!_o || PyDict_SetItemString(d, (name), _o) < 0) { Py_XDECREF(_o); Py_DECREF(d); return NULL; } Py_DECREF(_o); } while(0)
    SETOBJ("backend", PyUnicode_FromString("native-c-swiss-entryindex"));
    SETOBJ("size", PyLong_FromSsize_t(size));
    SETOBJ("capacity", PyLong_FromSsize_t(capacity));
    SETOBJ("tombstones", PyLong_FromSsize_t(tombstones));
    SETOBJ("load_factor", PyFloat_FromDouble(capacity ? ((double)size / (double)capacity) : 0.0));
    SETOBJ("max_probe", PyLong_FromSsize_t(max_probe));
    SETOBJ("avg_probe", PyFloat_FromDouble(avg_probe));
    SETOBJ("next_handle", PyLong_FromLongLong(next_handle));
    SETOBJ("resize_count", PyLong_FromUnsignedLongLong(self->resize_count));
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_get_handle", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_get_handles", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_pop_lookup", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_stats_scan", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_put", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_put_many", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "gil_released_pop_many", Py_True); Py_DECREF(Py_True);
    Py_INCREF(Py_True); PyDict_SetItemString(d, "swiss_control_bytes", Py_True); Py_DECREF(Py_True);
    SETOBJ("probing", PyUnicode_FromString("triangular"));
    SETOBJ("native_put_calls", PyLong_FromUnsignedLongLong(self->native_put_calls));
    SETOBJ("native_batch_put_calls", PyLong_FromUnsignedLongLong(self->native_batch_put_calls));
    SETOBJ("native_lookup_calls", PyLong_FromUnsignedLongLong(self->native_lookup_calls));
    SETOBJ("native_batch_lookup_calls", PyLong_FromUnsignedLongLong(self->native_batch_lookup_calls));
    SETOBJ("native_pop_calls", PyLong_FromUnsignedLongLong(self->native_pop_calls));
    SETOBJ("native_batch_pop_calls", PyLong_FromUnsignedLongLong(self->native_batch_pop_calls));
    SETOBJ("native_stats_calls", PyLong_FromUnsignedLongLong(self->native_stats_calls));
    SETOBJ("native_checksum_calls", PyLong_FromUnsignedLongLong(self->native_checksum_calls));
    SETOBJ("native_chunk_scan_calls", PyLong_FromUnsignedLongLong(self->native_chunk_scan_calls));
    SETOBJ("gil_released_calls", PyLong_FromUnsignedLongLong(self->gil_released_calls));
    SETOBJ("python_native_transitions", PyLong_FromUnsignedLongLong(self->python_native_transitions));
    SETOBJ("pool_block_size", PyLong_FromSsize_t(self->key_pool.block_size));
    SETOBJ("pool_reuse_count", PyLong_FromUnsignedLongLong(self->key_pool.reuse_count));
    SETOBJ("pool_allocator_calls", PyLong_FromUnsignedLongLong(self->key_pool.allocator_calls));
    SETOBJ("pool_frees", PyLong_FromUnsignedLongLong(self->key_pool.frees_to_pool));
#undef SETOBJ
    return d;
}

static uint32_t checksum32_nogil(const char *data, Py_ssize_t len) { return fnv1a32(data, len); }


/* =============================================================================
 * v2.8.9 Native Spiral Rank scoring engine
 *
 * The rank engine is intentionally isolated from NativeHandleIndex. It consumes
 * caller-supplied numeric metadata, releases the GIL for the scoring loop, and
 * returns copied score values to Python. It never reads storage payloads, never
 * controls storage locks, and never mutates trace/run directories.
 * ============================================================================= */
static inline double tds_clamp01(double x) {
    if (x < 0.0) return 0.0;
    if (x > 1.0) return 1.0;
    return x;
}

static PyObject *module_spiral_rank_scores(PyObject *self, PyObject *args, PyObject *kwargs) {
    PyObject *scores_obj = NULL;
    PyObject *conf_obj = Py_None;
    PyObject *depth_obj = Py_None;
    PyObject *age_obj = Py_None;
    double score_weight = 0.72;
    double confidence_weight = 0.18;
    double depth_penalty = 0.035;
    double age_penalty = 0.000001;
    static char *kwlist[] = {"scores", "confidences", "depths", "ages_ns", "score_weight", "confidence_weight", "depth_penalty", "age_penalty", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|OOOdddd", kwlist,
                                     &scores_obj, &conf_obj, &depth_obj, &age_obj,
                                     &score_weight, &confidence_weight, &depth_penalty, &age_penalty)) return NULL;

    PyObject *scores_fast = PySequence_Fast(scores_obj, "scores must be a sequence");
    if (!scores_fast) return NULL;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(scores_fast);
    PyObject **score_items = PySequence_Fast_ITEMS(scores_fast);

    PyObject *conf_fast = NULL, *depth_fast = NULL, *age_fast = NULL;
    PyObject **conf_items = NULL, **depth_items = NULL, **age_items = NULL;
    if (conf_obj != Py_None) {
        conf_fast = PySequence_Fast(conf_obj, "confidences must be a sequence");
        if (!conf_fast) { Py_DECREF(scores_fast); return NULL; }
        if (PySequence_Fast_GET_SIZE(conf_fast) != n) { Py_DECREF(scores_fast); Py_DECREF(conf_fast); PyErr_SetString(PyExc_ValueError, "confidences length must match scores length"); return NULL; }
        conf_items = PySequence_Fast_ITEMS(conf_fast);
    }
    if (depth_obj != Py_None) {
        depth_fast = PySequence_Fast(depth_obj, "depths must be a sequence");
        if (!depth_fast) { Py_DECREF(scores_fast); Py_XDECREF(conf_fast); return NULL; }
        if (PySequence_Fast_GET_SIZE(depth_fast) != n) { Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_DECREF(depth_fast); PyErr_SetString(PyExc_ValueError, "depths length must match scores length"); return NULL; }
        depth_items = PySequence_Fast_ITEMS(depth_fast);
    }
    if (age_obj != Py_None) {
        age_fast = PySequence_Fast(age_obj, "ages_ns must be a sequence");
        if (!age_fast) { Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_XDECREF(depth_fast); return NULL; }
        if (PySequence_Fast_GET_SIZE(age_fast) != n) { Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_XDECREF(depth_fast); Py_DECREF(age_fast); PyErr_SetString(PyExc_ValueError, "ages_ns length must match scores length"); return NULL; }
        age_items = PySequence_Fast_ITEMS(age_fast);
    }

    double *scores = (double*)calloc((size_t)n, sizeof(double));
    double *conf = (double*)calloc((size_t)n, sizeof(double));
    double *depth = (double*)calloc((size_t)n, sizeof(double));
    double *age = (double*)calloc((size_t)n, sizeof(double));
    double *out = (double*)calloc((size_t)n, sizeof(double));
    if (!scores || !conf || !depth || !age || !out) {
        Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_XDECREF(depth_fast); Py_XDECREF(age_fast);
        free(scores); free(conf); free(depth); free(age); free(out); PyErr_NoMemory(); return NULL;
    }
    for (Py_ssize_t i = 0; i < n; ++i) {
        scores[i] = PyFloat_AsDouble(score_items[i]);
        if (PyErr_Occurred()) goto parse_error;
        conf[i] = conf_items ? PyFloat_AsDouble(conf_items[i]) : 1.0;
        if (PyErr_Occurred()) goto parse_error;
        depth[i] = depth_items ? PyFloat_AsDouble(depth_items[i]) : 0.0;
        if (PyErr_Occurred()) goto parse_error;
        age[i] = age_items ? PyFloat_AsDouble(age_items[i]) : 0.0;
        if (PyErr_Occurred()) goto parse_error;
        if (depth[i] < 0.0) depth[i] = 0.0;
        if (age[i] < 0.0) age[i] = 0.0;
    }

    diag_counter_add(DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS, 1);
    diag_emit_transition(DIAG_EVENT_NATIVE_OPERATION, 7, 288, (uint64_t)n, 0, 0);
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t i = 0; i < n; ++i) {
        double base = tds_clamp01(scores[i]);
        double c = tds_clamp01(conf[i]);
        double d_pen = depth_penalty * depth[i];
        double a_pen = age_penalty * age[i];
        out[i] = (base * score_weight) + (c * confidence_weight) - d_pen - a_pen;
    }
    Py_END_ALLOW_THREADS

    PyObject *list = PyList_New(n);
    if (!list) goto fail;
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *v = PyFloat_FromDouble(out[i]);
        if (!v) { Py_DECREF(list); list = NULL; goto fail; }
        PyList_SET_ITEM(list, i, v);
    }
    Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_XDECREF(depth_fast); Py_XDECREF(age_fast);
    free(scores); free(conf); free(depth); free(age); free(out);
    return list;
parse_error:
fail:
    Py_DECREF(scores_fast); Py_XDECREF(conf_fast); Py_XDECREF(depth_fast); Py_XDECREF(age_fast);
    free(scores); free(conf); free(depth); free(age); free(out);
    return NULL;
}

static PyObject *module_checksum32(PyObject *self, PyObject *args) {
    const char *data; Py_ssize_t len; uint32_t out;
    if (!PyArg_ParseTuple(args, "y#", &data, &len)) return NULL;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHECKSUM_CALLS);
    Py_BEGIN_ALLOW_THREADS
    out = checksum32_nogil(data, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromUnsignedLong((unsigned long)out);
}

static PyObject *module_checksum32_many(PyObject *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHECKSUM_BATCH_CALLS);
    PyObject *fast = PySequence_Fast(seq, "checksum32_many expects an iterable of bytes-like objects");
    if (!fast) return NULL;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
    PyObject **items = PySequence_Fast_ITEMS(fast);
    const char **ptrs = (const char**)calloc((size_t)n, sizeof(char*));
    Py_ssize_t *lens = (Py_ssize_t*)calloc((size_t)n, sizeof(Py_ssize_t));
    uint32_t *outs = (uint32_t*)calloc((size_t)n, sizeof(uint32_t));
    if (!ptrs || !lens || !outs) {
        Py_DECREF(fast); free(ptrs); free(lens); free(outs); PyErr_NoMemory(); return NULL;
    }
    /* Acquire stable buffers before releasing the GIL. */
    Py_buffer *views = (Py_buffer*)calloc((size_t)n, sizeof(Py_buffer));
    if (!views) { Py_DECREF(fast); free(ptrs); free(lens); free(outs); PyErr_NoMemory(); return NULL; }
    for (Py_ssize_t i = 0; i < n; ++i) {
        if (PyObject_GetBuffer(items[i], &views[i], PyBUF_SIMPLE) < 0) {
            for (Py_ssize_t j = 0; j < i; ++j) PyBuffer_Release(&views[j]);
            Py_DECREF(fast); free(ptrs); free(lens); free(outs); free(views); return NULL;
        }
        ptrs[i] = (const char*)views[i].buf;
        lens[i] = views[i].len;
    }
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t i = 0; i < n; ++i) outs[i] = checksum32_nogil(ptrs[i], lens[i]);
    Py_END_ALLOW_THREADS
    PyObject *list = PyList_New(n);
    if (!list) {
        for (Py_ssize_t i = 0; i < n; ++i) PyBuffer_Release(&views[i]);
        Py_DECREF(fast); free(ptrs); free(lens); free(outs); free(views); return NULL;
    }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *v = PyLong_FromUnsignedLong((unsigned long)outs[i]);
        if (!v) { Py_DECREF(list); list = NULL; break; }
        PyList_SET_ITEM(list, i, v);
    }
    for (Py_ssize_t i = 0; i < n; ++i) PyBuffer_Release(&views[i]);
    Py_DECREF(fast); free(ptrs); free(lens); free(outs); free(views);
    return list;
}

static Py_ssize_t utf8_safe_cut_nogil(const unsigned char *buf, Py_ssize_t n, Py_ssize_t limit) {
    if (limit >= n) return n;
    if (limit <= 0) return 0;
    Py_ssize_t cut = limit;
    while (cut > 0 && (buf[cut] & 0xC0) == 0x80) cut--;
    if (cut == 0) return limit;
    unsigned char lead = buf[cut];
    Py_ssize_t need = 1;
    if ((lead & 0x80) == 0) need = 1;
    else if ((lead & 0xE0) == 0xC0) need = 2;
    else if ((lead & 0xF0) == 0xE0) need = 3;
    else if ((lead & 0xF8) == 0xF0) need = 4;
    else return cut;
    return (cut + need <= limit) ? limit : cut;
}

static PyObject *module_utf8_chunk_bounds(PyObject *self, PyObject *args) {
    const char *data; Py_ssize_t len; Py_ssize_t chunk;
    if (!PyArg_ParseTuple(args, "y#n", &data, &len, &chunk)) return NULL;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHUNK_SCAN_CALLS);
    if (chunk <= 0) { PyErr_SetString(PyExc_ValueError, "chunk size must be positive"); return NULL; }
    Py_ssize_t cap = (len / chunk) + 2;
    Py_ssize_t *bounds = (Py_ssize_t*)calloc((size_t)cap, sizeof(Py_ssize_t));
    if (!bounds) { PyErr_NoMemory(); return NULL; }
    Py_ssize_t count = 0;
    Py_BEGIN_ALLOW_THREADS
    Py_ssize_t pos = 0;
    while (pos < len) {
        Py_ssize_t limit = pos + chunk;
        Py_ssize_t next = utf8_safe_cut_nogil((const unsigned char*)data + pos, len - pos, chunk) + pos;
        if (next <= pos) next = (limit < len) ? limit : len;
        bounds[count++] = next;
        if (count >= cap) break;
        pos = next;
    }
    Py_END_ALLOW_THREADS
    PyObject *list = PyList_New(count);
    if (!list) { free(bounds); return NULL; }
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *v = PyLong_FromSsize_t(bounds[i]);
        if (!v) { Py_DECREF(list); free(bounds); return NULL; }
        PyList_SET_ITEM(list, i, v);
    }
    free(bounds);
    return list;
}

static PyMethodDef NativeHandleIndex_methods[] = {
    {"put", (PyCFunction)NativeHandleIndex_put, METH_VARARGS, "Insert key and return stable int64 handle."},
    {"put_many", (PyCFunction)NativeHandleIndex_put_many, METH_VARARGS, "Insert keys in one native batch."},
    {"get_handle", (PyCFunction)NativeHandleIndex_get_handle, METH_VARARGS, "Get handle for key. Releases the GIL."},
    {"get_handles", (PyCFunction)NativeHandleIndex_get_handles, METH_VARARGS, "Get handles for keys in one GIL-released native batch."},
    {"contains", (PyCFunction)NativeHandleIndex_contains, METH_VARARGS, "Return whether key exists."},
    {"pop", (PyCFunction)NativeHandleIndex_pop, METH_VARARGS, "Remove key and return its handle or -1."},
    {"pop_many", (PyCFunction)NativeHandleIndex_pop_many, METH_VARARGS, "Remove keys in one GIL-released native batch."},
    {"size", (PyCFunction)NativeHandleIndex_size, METH_NOARGS, "Return size."},
    {"stats", (PyCFunction)NativeHandleIndex_stats, METH_NOARGS, "Return native index stats."},
    {NULL}
};

static PyTypeObject NativeHandleIndexType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "staqtapp_tds._native_index.NativeHandleIndex",
    .tp_doc = "Native Swiss-table-inspired bytes->int64 handle index with GIL-released operations.",
    .tp_basicsize = sizeof(NativeHandleIndex),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = NativeHandleIndex_new,
    .tp_init = (initproc)NativeHandleIndex_init,
    .tp_dealloc = (destructor)NativeHandleIndex_dealloc,
    .tp_methods = NativeHandleIndex_methods,
};

static PyMethodDef module_methods[] = {
    {"checksum32", module_checksum32, METH_VARARGS, "FNV-1a 32-bit checksum with GIL released."},
    {"checksum32_many", module_checksum32_many, METH_VARARGS, "Batch FNV-1a 32-bit checksums with the GIL released."},
    {"spiral_rank_scores", (PyCFunction)module_spiral_rank_scores, METH_VARARGS | METH_KEYWORDS, "Native Spiral rank scoring loop with released GIL."},
    {"utf8_chunk_bounds", module_utf8_chunk_bounds, METH_VARARGS, "Return UTF-8 safe chunk end offsets with GIL released."},
    {"diag_snapshot", (PyCFunction)module_diag_snapshot, METH_VARARGS | METH_KEYWORDS, "Return immutable native diagnostic snapshot."},
    {"diag_reset", module_diag_reset, METH_NOARGS, "Reset native diagnostic counters and event ring."},
    {"diag_set_enabled", module_diag_set_enabled, METH_VARARGS, "Enable or disable native diagnostics."},
    {"diag_mark_degraded", module_diag_mark_degraded, METH_VARARGS, "Mark native diagnostics degraded without affecting storage."},
    {"diag_emit", module_diag_emit, METH_VARARGS, "Emit a tiny diagnostic transition event."},
    {NULL, NULL, 0, NULL}
};

static PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_native_index",
    .m_doc = "Staqtapp-TDS native execution primitives.",
    .m_size = -1,
    .m_methods = module_methods,
};

PyMODINIT_FUNC PyInit__native_index(void) {
    PyObject *m;
    if (PyType_Ready(&NativeHandleIndexType) < 0) return NULL;
    m = PyModule_Create(&moduledef);
    if (!m) return NULL;
    Py_INCREF(&NativeHandleIndexType);
    if (PyModule_AddObject(m, "NativeHandleIndex", (PyObject*)&NativeHandleIndexType) < 0) {
        Py_DECREF(&NativeHandleIndexType);
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
