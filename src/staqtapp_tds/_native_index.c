#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
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
    DIAG_COUNTER_EVENT_ATTEMPTS = 25,
    DIAG_COUNTER_EVENTS_SAMPLED_OUT = 26,
    DIAG_COUNTER_EVENTS_SLOT_BUSY = 27,
    DIAG_COUNTER_AUTOMATIC_EVENT_ATTEMPTS = 28,
    DIAG_COUNTER_MANUAL_EVENT_ATTEMPTS = 29,
    DIAG_COUNTER_RESET_REQUESTS = 30,
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

typedef struct {
    _Atomic uint64_t version;
    _Atomic uint64_t seq;
    _Atomic uint64_t timestamp_ns;
    _Atomic uint32_t code;
    _Atomic uint32_t flags;
    _Atomic uint32_t subsystem;
    _Atomic uint32_t object_id;
    _Atomic uint64_t value_a;
    _Atomic uint64_t value_b;
} TDSDiagSlot;

#define TDS_DIAG_RING_CAPACITY 4096
#define TDS_DIAG_DEFAULT_SAMPLE_BURST 64ULL
#define TDS_DIAG_DEFAULT_SAMPLE_INTERVAL 1024ULL
#define TDS_DIAG_SNAPSHOT_RETRIES 4

static _Atomic uint64_t g_diag_enabled = 1;
static _Atomic uint64_t g_diag_degraded = 0;
static _Atomic uint64_t g_diag_sequence = 0;
static _Atomic uint64_t g_diag_counters[DIAG_COUNTER_MAX];
static _Atomic uint64_t g_diag_sample_burst = TDS_DIAG_DEFAULT_SAMPLE_BURST;
static _Atomic uint64_t g_diag_sample_interval = TDS_DIAG_DEFAULT_SAMPLE_INTERVAL;
static _Atomic uint64_t g_diag_automatic_attempts = 0;
static _Atomic uint64_t g_diag_active_event_writers = 0;
static _Atomic uint64_t g_diag_resetting = 0;
static TDSDiagSlot g_diag_ring[TDS_DIAG_RING_CAPACITY];

static uint64_t diag_now_ns(void) {
#if defined(CLOCK_MONOTONIC)
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0) {
        return ((uint64_t)ts.tv_sec * 1000000000ULL) + (uint64_t)ts.tv_nsec;
    }
#endif
    return (uint64_t)time(NULL) * 1000000000ULL;
}

static uint64_t diag_atomic_increment_saturating(_Atomic uint64_t *ptr) {
    uint64_t current = atomic_load_explicit(ptr, memory_order_relaxed);
    for (;;) {
        uint64_t next = current == UINT64_MAX ? UINT64_MAX : current + 1ULL;
        if (atomic_compare_exchange_weak_explicit(
                ptr,
                &current,
                next,
                memory_order_relaxed,
                memory_order_relaxed)) {
            return next;
        }
    }
}

static void diag_atomic_add_saturating(_Atomic uint64_t *ptr, uint64_t value) {
    uint64_t current = atomic_load_explicit(ptr, memory_order_relaxed);
    for (;;) {
        uint64_t next = current > UINT64_MAX - value ? UINT64_MAX : current + value;
        if (atomic_compare_exchange_weak_explicit(
                ptr,
                &current,
                next,
                memory_order_relaxed,
                memory_order_relaxed)) {
            return;
        }
    }
}

static inline uint64_t diag_atomic_get(const _Atomic uint64_t *ptr) {
    return atomic_load_explicit(ptr, memory_order_acquire);
}

static inline void diag_counter_add_raw(DiagCounter counter, uint64_t value) {
    if (counter >= 0 && counter < DIAG_COUNTER_MAX) {
        diag_atomic_add_saturating(&g_diag_counters[counter], value);
    }
}

static inline void diag_counter_add(DiagCounter counter, uint64_t value) {
    if (!diag_atomic_get(&g_diag_enabled)) return;
    if (diag_atomic_get(&g_diag_resetting)) return;
    diag_counter_add_raw(counter, value);
}

static int diag_event_writer_enter(void) {
    if (diag_atomic_get(&g_diag_resetting)) return 0;
    atomic_fetch_add_explicit(
        &g_diag_active_event_writers,
        1ULL,
        memory_order_acq_rel
    );
    if (diag_atomic_get(&g_diag_resetting)) {
        atomic_fetch_sub_explicit(
            &g_diag_active_event_writers,
            1ULL,
            memory_order_release
        );
        return 0;
    }
    return 1;
}

static void diag_event_writer_exit(void) {
    atomic_fetch_sub_explicit(
        &g_diag_active_event_writers,
        1ULL,
        memory_order_release
    );
}

static int diag_reserve_sequence(uint64_t *sequence) {
    uint64_t current = atomic_load_explicit(&g_diag_sequence, memory_order_relaxed);
    for (;;) {
        if (current == UINT64_MAX) return 0;
        if (atomic_compare_exchange_weak_explicit(
                &g_diag_sequence,
                &current,
                current + 1ULL,
                memory_order_acq_rel,
                memory_order_relaxed)) {
            *sequence = current + 1ULL;
            return 1;
        }
    }
}

static int diag_should_publish_automatic(void) {
    uint64_t attempt = diag_atomic_increment_saturating(&g_diag_automatic_attempts);
    uint64_t burst = diag_atomic_get(&g_diag_sample_burst);
    uint64_t interval = diag_atomic_get(&g_diag_sample_interval);

    diag_counter_add_raw(DIAG_COUNTER_EVENT_ATTEMPTS, 1);
    diag_counter_add_raw(DIAG_COUNTER_AUTOMATIC_EVENT_ATTEMPTS, 1);
    if (attempt <= burst || interval == 1ULL) return 1;
    if (((attempt - burst) % interval) == 0ULL) return 1;
    diag_counter_add_raw(DIAG_COUNTER_EVENTS_SAMPLED_OUT, 1);
    return 0;
}

static int diag_slot_claim(TDSDiagSlot *slot, uint64_t *claimed_version) {
    uint64_t version = atomic_load_explicit(&slot->version, memory_order_acquire);
    if ((version & 1ULL) != 0ULL) return 0;
    if (!atomic_compare_exchange_strong_explicit(
            &slot->version,
            &version,
            version + 1ULL,
            memory_order_acq_rel,
            memory_order_acquire)) {
        return 0;
    }
    *claimed_version = version;
    return 1;
}

static void diag_slot_publish(
    TDSDiagSlot *slot,
    uint64_t claimed_version,
    uint64_t sequence,
    uint64_t timestamp_ns,
    uint32_t code,
    uint32_t flags,
    uint32_t subsystem,
    uint32_t object_id,
    uint64_t value_a,
    uint64_t value_b
) {
    atomic_store_explicit(&slot->seq, sequence, memory_order_relaxed);
    atomic_store_explicit(&slot->timestamp_ns, timestamp_ns, memory_order_relaxed);
    atomic_store_explicit(&slot->code, code, memory_order_relaxed);
    atomic_store_explicit(&slot->flags, flags, memory_order_relaxed);
    atomic_store_explicit(&slot->subsystem, subsystem, memory_order_relaxed);
    atomic_store_explicit(&slot->object_id, object_id, memory_order_relaxed);
    atomic_store_explicit(&slot->value_a, value_a, memory_order_relaxed);
    atomic_store_explicit(&slot->value_b, value_b, memory_order_relaxed);
    atomic_store_explicit(
        &slot->version,
        claimed_version + 2ULL,
        memory_order_release
    );
}

static int diag_slot_snapshot(
    const TDSDiagSlot *slot,
    uint64_t wanted_sequence,
    TDSDiagEvent *event
) {
    int attempt;
    for (attempt = 0; attempt < TDS_DIAG_SNAPSHOT_RETRIES; ++attempt) {
        uint64_t before = atomic_load_explicit(&slot->version, memory_order_acquire);
        uint64_t after;
        if ((before & 1ULL) != 0ULL) continue;

        event->seq = atomic_load_explicit(&slot->seq, memory_order_relaxed);
        event->timestamp_ns = atomic_load_explicit(
            &slot->timestamp_ns,
            memory_order_relaxed
        );
        event->code = atomic_load_explicit(&slot->code, memory_order_relaxed);
        event->flags = atomic_load_explicit(&slot->flags, memory_order_relaxed);
        event->subsystem = atomic_load_explicit(
            &slot->subsystem,
            memory_order_relaxed
        );
        event->object_id = atomic_load_explicit(
            &slot->object_id,
            memory_order_relaxed
        );
        event->value_a = atomic_load_explicit(&slot->value_a, memory_order_relaxed);
        event->value_b = atomic_load_explicit(&slot->value_b, memory_order_relaxed);
        after = atomic_load_explicit(&slot->version, memory_order_acquire);
        if (before == after
                && (after & 1ULL) == 0ULL
                && event->seq == wanted_sequence) {
            return 1;
        }
    }
    return 0;
}

static void diag_emit_transition_impl(
    DiagEventCode code,
    uint32_t subsystem,
    uint32_t object_id,
    uint64_t value_a,
    uint64_t value_b,
    uint32_t flags,
    int manual
) {
    uint64_t sequence;
    uint64_t index;
    uint64_t claimed_version;
    TDSDiagSlot *slot;

    if (!diag_atomic_get(&g_diag_enabled)) return;
    if (manual) {
        diag_counter_add_raw(DIAG_COUNTER_EVENT_ATTEMPTS, 1);
        diag_counter_add_raw(DIAG_COUNTER_MANUAL_EVENT_ATTEMPTS, 1);
    } else if (!diag_should_publish_automatic()) {
        return;
    }

    if (!diag_event_writer_enter()) {
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_DROPPED, 1);
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_SLOT_BUSY, 1);
        return;
    }
    if (!diag_reserve_sequence(&sequence)) {
        atomic_store_explicit(&g_diag_degraded, 1ULL, memory_order_release);
        diag_counter_add_raw(DIAG_COUNTER_DEGRADED, 1);
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_DROPPED, 1);
        diag_event_writer_exit();
        return;
    }

    index = (sequence - 1ULL) % TDS_DIAG_RING_CAPACITY;
    slot = &g_diag_ring[index];
    if (!diag_slot_claim(slot, &claimed_version)) {
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_DROPPED, 1);
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_SLOT_BUSY, 1);
        diag_event_writer_exit();
        return;
    }
    diag_slot_publish(
        slot,
        claimed_version,
        sequence,
        diag_now_ns(),
        (uint32_t)code,
        flags,
        subsystem,
        object_id,
        value_a,
        value_b
    );
    diag_counter_add_raw(DIAG_COUNTER_EVENTS_EMITTED, 1);
    if (sequence > TDS_DIAG_RING_CAPACITY) {
        diag_counter_add_raw(DIAG_COUNTER_EVENTS_DROPPED, 1);
        diag_counter_add_raw(DIAG_COUNTER_EVENT_RING_WRAPAROUNDS, 1);
    }
    diag_event_writer_exit();
}

static inline void diag_emit_transition(
    DiagEventCode code,
    uint32_t subsystem,
    uint32_t object_id,
    uint64_t value_a,
    uint64_t value_b,
    uint32_t flags
) {
    diag_emit_transition_impl(
        code,
        subsystem,
        object_id,
        value_a,
        value_b,
        flags,
        0
    );
}

static inline void diag_emit_event(
    DiagEventCode code,
    uint64_t value_a,
    uint64_t value_b
) {
    diag_emit_transition(code, 0, 0, value_a, value_b, 0);
}

static inline void diag_count_transition(DiagEventCode code) {
    if (code >= DIAG_EVENT_SLOT_ALLOCATED && code <= DIAG_EVENT_SLOT_VISIBLE) {
        diag_counter_add(DIAG_COUNTER_SLOT_TRANSITIONS, 1);
    } else if (code >= DIAG_EVENT_INDEX_RESIZED
            && code <= DIAG_EVENT_INDEX_LOOKUP_MISS) {
        diag_counter_add(DIAG_COUNTER_INDEX_TRANSITIONS, 1);
    } else if (code >= DIAG_EVENT_LOCK_WAIT && code <= DIAG_EVENT_LOCK_RELEASED) {
        diag_counter_add(DIAG_COUNTER_LOCK_TRANSITIONS, 1);
    } else if (code >= DIAG_EVENT_MEMORY_POOL_REUSED
            && code <= DIAG_EVENT_MEMORY_POOL_FREED) {
        diag_counter_add(DIAG_COUNTER_MEMORY_TRANSITIONS, 1);
    } else if (code == DIAG_EVENT_SNAPSHOT_MARKER) {
        diag_counter_add(DIAG_COUNTER_SNAPSHOT_MARKERS, 1);
    }
}

static inline void diag_note_gil_released(DiagCounter op_counter) {
    diag_counter_add(DIAG_COUNTER_GIL_RELEASED_CALLS, 1);
    diag_counter_add(DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS, 1);
    diag_counter_add(op_counter, 1);
    diag_emit_transition(
        DIAG_EVENT_GIL_RELEASED,
        1,
        0,
        (uint64_t)op_counter,
        0,
        0
    );
}

static int diag_dict_set_u64(PyObject *dict, const char *name, uint64_t value) {
    PyObject *item = PyLong_FromUnsignedLongLong((unsigned long long)value);
    int status;
    if (item == NULL) return -1;
    status = PyDict_SetItemString(dict, name, item);
    Py_DECREF(item);
    return status;
}

static PyObject *diag_counter_dict(void) {
    PyObject *dict = PyDict_New();
    uint64_t emitted;
    uint64_t occupancy;
    if (dict == NULL) return NULL;

#define SET_COUNTER(name, index) \
    do { \
        if (diag_dict_set_u64( \
                dict, \
                (name), \
                diag_atomic_get(&g_diag_counters[(index)])) < 0) { \
            Py_DECREF(dict); \
            return NULL; \
        } \
    } while (0)

    SET_COUNTER("gil_released_calls", DIAG_COUNTER_GIL_RELEASED_CALLS);
    SET_COUNTER("python_native_transitions", DIAG_COUNTER_PYTHON_NATIVE_TRANSITIONS);
    SET_COUNTER("native_put_calls", DIAG_COUNTER_NATIVE_PUT_CALLS);
    SET_COUNTER("native_batch_put_calls", DIAG_COUNTER_NATIVE_BATCH_PUT_CALLS);
    SET_COUNTER("native_lookup_calls", DIAG_COUNTER_NATIVE_LOOKUP_CALLS);
    SET_COUNTER("native_batch_lookup_calls", DIAG_COUNTER_NATIVE_BATCH_LOOKUP_CALLS);
    SET_COUNTER("native_pop_calls", DIAG_COUNTER_NATIVE_POP_CALLS);
    SET_COUNTER("native_batch_pop_calls", DIAG_COUNTER_NATIVE_BATCH_POP_CALLS);
    SET_COUNTER("native_stats_calls", DIAG_COUNTER_NATIVE_STATS_CALLS);
    SET_COUNTER("native_checksum_calls", DIAG_COUNTER_NATIVE_CHECKSUM_CALLS);
    SET_COUNTER("native_checksum_batch_calls", DIAG_COUNTER_NATIVE_CHECKSUM_BATCH_CALLS);
    SET_COUNTER("native_chunk_scan_calls", DIAG_COUNTER_NATIVE_CHUNK_SCAN_CALLS);
    SET_COUNTER("snapshot_requests", DIAG_COUNTER_SNAPSHOT_REQUESTS);
    SET_COUNTER("snapshot_built", DIAG_COUNTER_SNAPSHOT_BUILT);
    SET_COUNTER("events_emitted", DIAG_COUNTER_EVENTS_EMITTED);
    SET_COUNTER("events_dropped", DIAG_COUNTER_EVENTS_DROPPED);
    SET_COUNTER("degraded_count", DIAG_COUNTER_DEGRADED);
    SET_COUNTER("slot_transitions", DIAG_COUNTER_SLOT_TRANSITIONS);
    SET_COUNTER("index_transitions", DIAG_COUNTER_INDEX_TRANSITIONS);
    SET_COUNTER("lock_transitions", DIAG_COUNTER_LOCK_TRANSITIONS);
    SET_COUNTER("memory_transitions", DIAG_COUNTER_MEMORY_TRANSITIONS);
    SET_COUNTER("snapshot_markers", DIAG_COUNTER_SNAPSHOT_MARKERS);
    SET_COUNTER("event_ring_wraparounds", DIAG_COUNTER_EVENT_RING_WRAPAROUNDS);
    SET_COUNTER("event_attempts", DIAG_COUNTER_EVENT_ATTEMPTS);
    SET_COUNTER("events_sampled_out", DIAG_COUNTER_EVENTS_SAMPLED_OUT);
    SET_COUNTER("events_slot_busy", DIAG_COUNTER_EVENTS_SLOT_BUSY);
    SET_COUNTER(
        "automatic_event_attempts",
        DIAG_COUNTER_AUTOMATIC_EVENT_ATTEMPTS
    );
    SET_COUNTER("manual_event_attempts", DIAG_COUNTER_MANUAL_EVENT_ATTEMPTS);
    SET_COUNTER("reset_requests", DIAG_COUNTER_RESET_REQUESTS);
#undef SET_COUNTER

    emitted = diag_atomic_get(&g_diag_counters[DIAG_COUNTER_EVENTS_EMITTED]);
    occupancy = emitted < TDS_DIAG_RING_CAPACITY
        ? emitted
        : TDS_DIAG_RING_CAPACITY;
    if (diag_dict_set_u64(dict, "ring_capacity", TDS_DIAG_RING_CAPACITY) < 0
            || diag_dict_set_u64(dict, "ring_occupancy", occupancy) < 0
            || diag_dict_set_u64(
                dict,
                "sampling_interval",
                diag_atomic_get(&g_diag_sample_interval)) < 0
            || diag_dict_set_u64(
                dict,
                "sampling_burst",
                diag_atomic_get(&g_diag_sample_burst)) < 0
            || diag_dict_set_u64(
                dict,
                "active_event_writers",
                diag_atomic_get(&g_diag_active_event_writers)) < 0
            || diag_dict_set_u64(
                dict,
                "resetting",
                diag_atomic_get(&g_diag_resetting)) < 0) {
        Py_DECREF(dict);
        return NULL;
    }
    return dict;
}

static PyObject *diag_event_list(Py_ssize_t limit) {
    uint64_t sequence = diag_atomic_get(&g_diag_sequence);
    Py_ssize_t available = (Py_ssize_t)(
        sequence < TDS_DIAG_RING_CAPACITY
            ? sequence
            : TDS_DIAG_RING_CAPACITY
    );
    uint64_t start;
    PyObject *list;

    if (limit < 0 || limit > available) limit = available;
    list = PyList_New(0);
    if (list == NULL) return NULL;
    start = sequence >= (uint64_t)limit
        ? sequence - (uint64_t)limit + 1ULL
        : 1ULL;
    for (Py_ssize_t index = 0; index < limit; ++index) {
        uint64_t wanted = start + (uint64_t)index;
        TDSDiagEvent event;
        PyObject *item;
        if (!diag_slot_snapshot(
                &g_diag_ring[(wanted - 1ULL) % TDS_DIAG_RING_CAPACITY],
                wanted,
                &event)) {
            continue;
        }
        item = Py_BuildValue(
            "{s:K,s:K,s:I,s:I,s:I,s:I,s:K,s:K}",
            "seq", (unsigned long long)event.seq,
            "timestamp_ns", (unsigned long long)event.timestamp_ns,
            "code", (unsigned int)event.code,
            "flags", (unsigned int)event.flags,
            "subsystem", (unsigned int)event.subsystem,
            "object_id", (unsigned int)event.object_id,
            "value_a", (unsigned long long)event.value_a,
            "value_b", (unsigned long long)event.value_b
        );
        if (item == NULL) {
            Py_DECREF(list);
            return NULL;
        }
        if (PyList_Append(list, item) < 0) {
            Py_DECREF(item);
            Py_DECREF(list);
            return NULL;
        }
        Py_DECREF(item);
    }
    return list;
}

static PyObject *module_diag_snapshot(
    PyObject *self,
    PyObject *args,
    PyObject *kwargs
) {
    Py_ssize_t event_limit = 32;
    uint64_t started;
    uint64_t built;
    uint64_t elapsed;
    PyObject *counters;
    PyObject *events;
    PyObject *result;
    static char *kwlist[] = {"event_limit", NULL};
    (void)self;

    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "|n",
            kwlist,
            &event_limit)) {
        return NULL;
    }
    if (event_limit < 0) event_limit = 0;
    if (event_limit > TDS_DIAG_RING_CAPACITY) {
        event_limit = TDS_DIAG_RING_CAPACITY;
    }
    diag_counter_add(DIAG_COUNTER_SNAPSHOT_REQUESTS, 1);
    started = diag_now_ns();
    built = diag_atomic_increment_saturating(
        &g_diag_counters[DIAG_COUNTER_SNAPSHOT_BUILT]
    );
    if (diag_atomic_get(&g_diag_enabled) && (built % 8ULL) == 0ULL) {
        diag_count_transition(DIAG_EVENT_SNAPSHOT_MARKER);
        diag_emit_transition(
            DIAG_EVENT_SNAPSHOT_MARKER,
            6,
            0,
            diag_atomic_get(&g_diag_sequence),
            (uint64_t)event_limit,
            0
        );
    }
    counters = diag_counter_dict();
    if (counters == NULL) return NULL;
    events = diag_event_list(event_limit);
    if (events == NULL) {
        Py_DECREF(counters);
        return NULL;
    }
    elapsed = diag_now_ns() - started;
    result = Py_BuildValue(
        "{s:i,s:s,s:O,s:O,s:K,s:K,s:O,s:O}",
        "schema_version", 2,
        "subsystem", "native_diagnostics",
        "enabled", diag_atomic_get(&g_diag_enabled) ? Py_True : Py_False,
        "degraded", diag_atomic_get(&g_diag_degraded) ? Py_True : Py_False,
        "sequence", (unsigned long long)diag_atomic_get(&g_diag_sequence),
        "snapshot_build_ns", (unsigned long long)elapsed,
        "counters", counters,
        "recent_events", events
    );
    Py_DECREF(counters);
    Py_DECREF(events);
    return result;
}

static void diag_slot_clear(TDSDiagSlot *slot) {
    atomic_store_explicit(&slot->version, 0ULL, memory_order_relaxed);
    atomic_store_explicit(&slot->seq, 0ULL, memory_order_relaxed);
    atomic_store_explicit(&slot->timestamp_ns, 0ULL, memory_order_relaxed);
    atomic_store_explicit(&slot->code, 0U, memory_order_relaxed);
    atomic_store_explicit(&slot->flags, 0U, memory_order_relaxed);
    atomic_store_explicit(&slot->subsystem, 0U, memory_order_relaxed);
    atomic_store_explicit(&slot->object_id, 0U, memory_order_relaxed);
    atomic_store_explicit(&slot->value_a, 0ULL, memory_order_relaxed);
    atomic_store_explicit(&slot->value_b, 0ULL, memory_order_relaxed);
}

static PyObject *module_diag_reset(
    PyObject *self,
    PyObject *Py_UNUSED(ignored)
) {
    uint64_t reset_count;
    int index;
    (void)self;

    atomic_store_explicit(&g_diag_resetting, 1ULL, memory_order_release);
    while (diag_atomic_get(&g_diag_active_event_writers) != 0ULL) {
        (void)sched_yield();
    }
    reset_count = diag_atomic_increment_saturating(
        &g_diag_counters[DIAG_COUNTER_RESET_REQUESTS]
    );
    for (index = 0; index < DIAG_COUNTER_MAX; ++index) {
        atomic_store_explicit(
            &g_diag_counters[index],
            0ULL,
            memory_order_relaxed
        );
    }
    atomic_store_explicit(&g_diag_sequence, 0ULL, memory_order_relaxed);
    atomic_store_explicit(&g_diag_automatic_attempts, 0ULL, memory_order_relaxed);
    atomic_store_explicit(
        &g_diag_sample_burst,
        TDS_DIAG_DEFAULT_SAMPLE_BURST,
        memory_order_relaxed
    );
    atomic_store_explicit(
        &g_diag_sample_interval,
        TDS_DIAG_DEFAULT_SAMPLE_INTERVAL,
        memory_order_relaxed
    );
    atomic_store_explicit(&g_diag_degraded, 0ULL, memory_order_relaxed);
    for (index = 0; index < TDS_DIAG_RING_CAPACITY; ++index) {
        diag_slot_clear(&g_diag_ring[index]);
    }
    atomic_store_explicit(
        &g_diag_counters[DIAG_COUNTER_RING_CAPACITY],
        TDS_DIAG_RING_CAPACITY,
        memory_order_relaxed
    );
    atomic_store_explicit(
        &g_diag_counters[DIAG_COUNTER_RESET_REQUESTS],
        reset_count,
        memory_order_relaxed
    );
    atomic_store_explicit(&g_diag_resetting, 0ULL, memory_order_release);
    Py_RETURN_NONE;
}

static PyObject *module_diag_set_enabled(PyObject *self, PyObject *args) {
    int enabled = 1;
    (void)self;
    if (!PyArg_ParseTuple(args, "p", &enabled)) return NULL;
    atomic_store_explicit(
        &g_diag_enabled,
        enabled ? 1ULL : 0ULL,
        memory_order_release
    );
    Py_RETURN_NONE;
}

static PyObject *module_diag_set_sampling(
    PyObject *self,
    PyObject *args,
    PyObject *kwargs
) {
    unsigned long long interval = (unsigned long long)diag_atomic_get(
        &g_diag_sample_interval
    );
    unsigned long long burst = (unsigned long long)diag_atomic_get(
        &g_diag_sample_burst
    );
    static char *kwlist[] = {"interval", "burst", NULL};
    (void)self;

    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "|KK",
            kwlist,
            &interval,
            &burst)) {
        return NULL;
    }
    if (interval == 0ULL) {
        PyErr_SetString(PyExc_ValueError, "diagnostic sampling interval must be positive");
        return NULL;
    }
    atomic_store_explicit(
        &g_diag_sample_interval,
        (uint64_t)interval,
        memory_order_release
    );
    atomic_store_explicit(
        &g_diag_sample_burst,
        (uint64_t)burst,
        memory_order_release
    );
    atomic_store_explicit(
        &g_diag_automatic_attempts,
        0ULL,
        memory_order_release
    );
    Py_RETURN_NONE;
}

static PyObject *module_diag_mark_degraded(PyObject *self, PyObject *args) {
    int degraded = 1;
    (void)self;
    if (!PyArg_ParseTuple(args, "|p", &degraded)) return NULL;
    atomic_store_explicit(
        &g_diag_degraded,
        degraded ? 1ULL : 0ULL,
        memory_order_release
    );
    if (degraded) diag_counter_add(DIAG_COUNTER_DEGRADED, 1);
    Py_RETURN_NONE;
}

static PyObject *module_diag_emit(PyObject *self, PyObject *args) {
    unsigned int code;
    unsigned long long value_a = 0;
    unsigned long long value_b = 0;
    (void)self;

    if (!PyArg_ParseTuple(args, "I|KK", &code, &value_a, &value_b)) {
        return NULL;
    }
    diag_count_transition((DiagEventCode)code);
    diag_emit_transition_impl(
        (DiagEventCode)code,
        0,
        0,
        (uint64_t)value_a,
        (uint64_t)value_b,
        0,
        1
    );
    Py_RETURN_NONE;
}

static int diag_atomics_lock_free(void) {
    return atomic_is_lock_free(&g_diag_enabled)
        && atomic_is_lock_free(&g_diag_sequence)
        && atomic_is_lock_free(&g_diag_counters[0])
        && atomic_is_lock_free(&g_diag_ring[0].version)
        && atomic_is_lock_free(&g_diag_ring[0].seq)
        && atomic_is_lock_free(&g_diag_ring[0].code);
}

static void diag_initialize(void) {
    atomic_store_explicit(
        &g_diag_counters[DIAG_COUNTER_RING_CAPACITY],
        TDS_DIAG_RING_CAPACITY,
        memory_order_relaxed
    );
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


/*
 * Immutable input ownership for GIL-free native truth operations.
 * Exact bytes are held zero-copy. Every other contiguous exporter is copied
 * once while the GIL is held, then the original Py_buffer is released before
 * native work begins.
 */
typedef struct {
    PyObject *owner;
    const char *data;
    Py_ssize_t len;
} TDSStableInput;

static void stable_input_init(TDSStableInput *input) {
    input->owner = NULL;
    input->data = NULL;
    input->len = 0;
}

static void stable_input_release(TDSStableInput *input) {
    Py_CLEAR(input->owner);
    input->data = NULL;
    input->len = 0;
}

static int stable_input_acquire(PyObject *object, TDSStableInput *input, const char *label) {
    Py_buffer view;
    PyObject *snapshot = NULL;

    stable_input_init(input);
    if (PyBytes_CheckExact(object)) {
        Py_INCREF(object);
        input->owner = object;
        input->data = PyBytes_AS_STRING(object);
        input->len = PyBytes_GET_SIZE(object);
        return 0;
    }
    if (PyObject_GetBuffer(object, &view, PyBUF_CONTIG_RO) < 0) {
        return -1;
    }
    if (view.len < 0) {
        PyBuffer_Release(&view);
        PyErr_Format(PyExc_ValueError, "%s buffer length must not be negative", label);
        return -1;
    }
    snapshot = PyBytes_FromStringAndSize(
        view.len == 0 ? "" : (const char *)view.buf,
        view.len
    );
    PyBuffer_Release(&view);
    if (snapshot == NULL) {
        return -1;
    }
    input->owner = snapshot;
    input->data = PyBytes_AS_STRING(snapshot);
    input->len = PyBytes_GET_SIZE(snapshot);
    return 0;
}

static uint32_t crc32_ieee_nogil(const char *data, Py_ssize_t len) {
    static const uint32_t table[16] = {
        0x00000000u, 0x1DB71064u, 0x3B6E20C8u, 0x26D930ACu,
        0x76DC4190u, 0x6B6B51F4u, 0x4DB26158u, 0x5005713Cu,
        0xEDB88320u, 0xF00F9344u, 0xD6D6A3E8u, 0xCB61B38Cu,
        0x9B64C2B0u, 0x86D3D2D4u, 0xA00AE278u, 0xBDBDF21Cu
    };
    uint32_t crc = 0xFFFFFFFFu;
    Py_ssize_t i;
    for (i = 0; i < len; ++i) {
        uint32_t byte = (uint32_t)(unsigned char)data[i];
        crc = table[(crc ^ byte) & 0x0Fu] ^ (crc >> 4);
        crc = table[(crc ^ (byte >> 4)) & 0x0Fu] ^ (crc >> 4);
    }
    return crc ^ 0xFFFFFFFFu;
}

typedef enum {
    CHECKSUM_ALGORITHM_INVALID = 0,
    CHECKSUM_ALGORITHM_CRC32_IEEE_V1 = 1,
    CHECKSUM_ALGORITHM_FNV1A32_LEGACY_V1 = 2
} ChecksumAlgorithm;

static ChecksumAlgorithm checksum_algorithm_from_name(const char *name) {
    if (strcmp(name, "crc32-ieee-v1") == 0) {
        return CHECKSUM_ALGORITHM_CRC32_IEEE_V1;
    }
    if (strcmp(name, "fnv1a32-legacy-v1") == 0) {
        return CHECKSUM_ALGORITHM_FNV1A32_LEGACY_V1;
    }
    return CHECKSUM_ALGORITHM_INVALID;
}

static uint32_t checksum32_for_algorithm_nogil(
    const char *data,
    Py_ssize_t len,
    ChecksumAlgorithm algorithm
) {
    if (algorithm == CHECKSUM_ALGORITHM_CRC32_IEEE_V1) {
        return crc32_ieee_nogil(data, len);
    }
    return fnv1a32(data, len);
}

typedef enum {
    UTF8_ERROR_NONE = 0,
    UTF8_ERROR_INVALID_START = 1,
    UTF8_ERROR_INVALID_CONTINUATION = 2,
    UTF8_ERROR_TRUNCATED = 3,
    UTF8_ERROR_OVERLONG = 4,
    UTF8_ERROR_SURROGATE = 5,
    UTF8_ERROR_OUT_OF_RANGE = 6,
    UTF8_ERROR_BOUND_CAPACITY = 7
} UTF8ErrorCode;

typedef struct {
    UTF8ErrorCode code;
    Py_ssize_t start;
    Py_ssize_t end;
} UTF8Error;

static int utf8_is_continuation(unsigned char value) {
    return value >= 0x80u && value <= 0xBFu;
}

static int utf8_width_nogil(
    const unsigned char *data,
    Py_ssize_t len,
    Py_ssize_t position,
    Py_ssize_t *width,
    UTF8Error *error
) {
    unsigned char lead = data[position];
    Py_ssize_t remaining = len - position;
    unsigned char second;
    Py_ssize_t expected = 0;

    if (lead <= 0x7Fu) {
        *width = 1;
        return 1;
    }
    if (lead >= 0xC2u && lead <= 0xDFu) {
        expected = 2;
    } else if (lead >= 0xE0u && lead <= 0xEFu) {
        expected = 3;
    } else if (lead >= 0xF0u && lead <= 0xF4u) {
        expected = 4;
    } else {
        error->code = UTF8_ERROR_INVALID_START;
        error->start = position;
        error->end = position + 1;
        return 0;
    }
    if (remaining < expected) {
        error->code = UTF8_ERROR_TRUNCATED;
        error->start = position;
        error->end = len;
        return 0;
    }
    for (Py_ssize_t offset = 1; offset < expected; ++offset) {
        if (!utf8_is_continuation(data[position + offset])) {
            error->code = UTF8_ERROR_INVALID_CONTINUATION;
            error->start = position + offset;
            error->end = position + offset + 1;
            return 0;
        }
    }
    second = data[position + 1];
    if (lead == 0xE0u && second < 0xA0u) {
        error->code = UTF8_ERROR_OVERLONG;
        error->start = position;
        error->end = position + expected;
        return 0;
    }
    if (lead == 0xEDu && second > 0x9Fu) {
        error->code = UTF8_ERROR_SURROGATE;
        error->start = position;
        error->end = position + expected;
        return 0;
    }
    if (lead == 0xF0u && second < 0x90u) {
        error->code = UTF8_ERROR_OVERLONG;
        error->start = position;
        error->end = position + expected;
        return 0;
    }
    if (lead == 0xF4u && second > 0x8Fu) {
        error->code = UTF8_ERROR_OUT_OF_RANGE;
        error->start = position;
        error->end = position + expected;
        return 0;
    }
    *width = expected;
    return 1;
}

static Py_ssize_t utf8_plan_bounds_nogil(
    const unsigned char *data,
    Py_ssize_t len,
    Py_ssize_t chunk_size,
    Py_ssize_t *bounds,
    Py_ssize_t capacity,
    UTF8Error *error
) {
    Py_ssize_t position = 0;
    Py_ssize_t chunk_start = 0;
    Py_ssize_t count = 0;

    error->code = UTF8_ERROR_NONE;
    error->start = 0;
    error->end = 0;
    while (position < len) {
        Py_ssize_t width = 0;
        Py_ssize_t used = position - chunk_start;
        if (!utf8_width_nogil(data, len, position, &width, error)) {
            return -1;
        }
        if (position > chunk_start && width > chunk_size - used) {
            if (count >= capacity) {
                error->code = UTF8_ERROR_BOUND_CAPACITY;
                return -1;
            }
            bounds[count++] = position;
            chunk_start = position;
        }
        position += width;
        if (position - chunk_start >= chunk_size) {
            if (count >= capacity) {
                error->code = UTF8_ERROR_BOUND_CAPACITY;
                return -1;
            }
            bounds[count++] = position;
            chunk_start = position;
        }
    }
    if (position > chunk_start) {
        if (count >= capacity) {
            error->code = UTF8_ERROR_BOUND_CAPACITY;
            return -1;
        }
        bounds[count++] = position;
    }
    return count;
}

static const char *utf8_error_reason(UTF8ErrorCode code) {
    switch (code) {
        case UTF8_ERROR_INVALID_START: return "invalid start byte";
        case UTF8_ERROR_INVALID_CONTINUATION: return "invalid continuation byte";
        case UTF8_ERROR_TRUNCATED: return "unexpected end of data";
        case UTF8_ERROR_OVERLONG: return "invalid overlong encoding";
        case UTF8_ERROR_SURROGATE: return "UTF-8 surrogate encoding";
        case UTF8_ERROR_OUT_OF_RANGE: return "code point exceeds U+10FFFF";
        default: return "invalid UTF-8";
    }
}

static void utf8_raise_decode_error(const TDSStableInput *input, const UTF8Error *error) {
    PyObject *exception = PyUnicodeDecodeError_Create(
        "utf-8",
        input->data,
        input->len,
        error->start,
        error->end,
        utf8_error_reason(error->code)
    );
    if (exception != NULL) {
        PyErr_SetObject(PyExc_UnicodeDecodeError, exception);
        Py_DECREF(exception);
    }
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
    if (len <= 0) {
        return NULL;
    }

    /*
     * TinyKeyPool safety invariant:
     *
     * Every pointer stored in free_list is allocated with exactly
     * pool->block_size bytes of capacity.  key_free() only receives the
     * logical key length, not the allocation capacity, so pooled buffers must
     * all have the same known capacity.
     *
     * Do not allocate small keys with malloc(len) and later pool them.  That
     * allows a 10-byte allocation to be reused for a 100-byte key and causes a
     * heap buffer overflow during memcpy().
     */
    if (len <= pool->block_size) {
        if (pool->free_list) {
            KeyNode *n = pool->free_list;
            pool->free_list = n->next;
            pool->reuse_count++;
            return (char*)n;
        }
        pool->allocator_calls++;
        return (char*)malloc((size_t)pool->block_size);
    }

    pool->allocator_calls++;
    return (char*)malloc((size_t)len);
}

static void key_free(NativeHandleIndex *self, char *ptr, Py_ssize_t len) {
    if (!ptr) return;
    TinyKeyPool *pool = &self->key_pool;
    if (len > 0 && len <= pool->block_size) {
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
    (void)args;
    (void)kwds;
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
    (void)self;
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
        /* Keep the operation boundaries identical to Python's evaluation.
         * Apple Clang may otherwise contract the weighted terms into an FMA
         * at -O3, producing a one-ULP platform-only parity difference. */
        double weighted_score = base * score_weight;
        double weighted_confidence = c * confidence_weight;
        double weighted_total = weighted_score + weighted_confidence;
        double after_depth = weighted_total - d_pen;
        out[i] = after_depth - a_pen;
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

static PyObject *module_checksum32_legacy(PyObject *self, PyObject *args) {
    PyObject *payload = NULL;
    TDSStableInput input;
    uint32_t out;
    (void)self;
    if (!PyArg_ParseTuple(args, "O", &payload)) return NULL;
    if (stable_input_acquire(payload, &input, "checksum") < 0) return NULL;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHECKSUM_CALLS);
    Py_BEGIN_ALLOW_THREADS
    out = checksum32_for_algorithm_nogil(
        input.data,
        input.len,
        CHECKSUM_ALGORITHM_FNV1A32_LEGACY_V1
    );
    Py_END_ALLOW_THREADS
    stable_input_release(&input);
    return PyLong_FromUnsignedLong((unsigned long)out);
}

static PyObject *module_checksum32_for_algorithm(PyObject *self, PyObject *args) {
    PyObject *payload = NULL;
    const char *algorithm_name = NULL;
    ChecksumAlgorithm algorithm;
    TDSStableInput input;
    uint32_t out;
    (void)self;
    if (!PyArg_ParseTuple(args, "Os", &payload, &algorithm_name)) return NULL;
    algorithm = checksum_algorithm_from_name(algorithm_name);
    if (algorithm == CHECKSUM_ALGORITHM_INVALID) {
        PyErr_Format(PyExc_ValueError, "unsupported checksum algorithm: %s", algorithm_name);
        return NULL;
    }
    if (stable_input_acquire(payload, &input, "checksum") < 0) return NULL;
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHECKSUM_CALLS);
    Py_BEGIN_ALLOW_THREADS
    out = checksum32_for_algorithm_nogil(input.data, input.len, algorithm);
    Py_END_ALLOW_THREADS
    stable_input_release(&input);
    return PyLong_FromUnsignedLong((unsigned long)out);
}

static PyObject *checksum32_many_impl(
    PyObject *sequence,
    ChecksumAlgorithm algorithm,
    const char *error_message
) {
    PyObject *fast = PySequence_Fast(sequence, error_message);
    TDSStableInput *inputs = NULL;
    uint32_t *outputs = NULL;
    PyObject *list = NULL;
    Py_ssize_t n;
    Py_ssize_t acquired = 0;

    if (fast == NULL) return NULL;
    n = PySequence_Fast_GET_SIZE(fast);
    if (n == 0) {
        Py_DECREF(fast);
        return PyList_New(0);
    }
    if ((size_t)n > SIZE_MAX / sizeof(TDSStableInput)
            || (size_t)n > SIZE_MAX / sizeof(uint32_t)) {
        Py_DECREF(fast);
        PyErr_SetString(PyExc_OverflowError, "checksum batch allocation overflow");
        return NULL;
    }
    inputs = (TDSStableInput *)PyMem_Calloc((size_t)n, sizeof(TDSStableInput));
    outputs = (uint32_t *)PyMem_Malloc((size_t)n * sizeof(uint32_t));
    if (inputs == NULL || outputs == NULL) {
        Py_DECREF(fast);
        PyMem_Free(inputs);
        PyMem_Free(outputs);
        PyErr_NoMemory();
        return NULL;
    }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *item = PySequence_Fast_GET_ITEM(fast, i);
        if (stable_input_acquire(item, &inputs[i], "checksum") < 0) {
            goto done;
        }
        acquired += 1;
    }
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHECKSUM_BATCH_CALLS);
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t i = 0; i < n; ++i) {
        outputs[i] = checksum32_for_algorithm_nogil(inputs[i].data, inputs[i].len, algorithm);
    }
    Py_END_ALLOW_THREADS
    list = PyList_New(n);
    if (list == NULL) goto done;
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *value = PyLong_FromUnsignedLong((unsigned long)outputs[i]);
        if (value == NULL) {
            Py_CLEAR(list);
            goto done;
        }
        PyList_SET_ITEM(list, i, value);
    }

done:
    for (Py_ssize_t i = 0; i < acquired; ++i) stable_input_release(&inputs[i]);
    PyMem_Free(inputs);
    PyMem_Free(outputs);
    Py_DECREF(fast);
    return list;
}

static PyObject *module_checksum32_many_legacy(PyObject *self, PyObject *args) {
    PyObject *sequence = NULL;
    (void)self;
    if (!PyArg_ParseTuple(args, "O", &sequence)) return NULL;
    return checksum32_many_impl(
        sequence,
        CHECKSUM_ALGORITHM_FNV1A32_LEGACY_V1,
        "checksum32_many expects an iterable of bytes-like objects"
    );
}

static PyObject *module_checksum32_many_for_algorithm(PyObject *self, PyObject *args) {
    PyObject *sequence = NULL;
    const char *algorithm_name = NULL;
    ChecksumAlgorithm algorithm;
    (void)self;
    if (!PyArg_ParseTuple(args, "Os", &sequence, &algorithm_name)) return NULL;
    algorithm = checksum_algorithm_from_name(algorithm_name);
    if (algorithm == CHECKSUM_ALGORITHM_INVALID) {
        PyErr_Format(PyExc_ValueError, "unsupported checksum algorithm: %s", algorithm_name);
        return NULL;
    }
    return checksum32_many_impl(
        sequence,
        algorithm,
        "checksum32_many_for_algorithm expects an iterable of bytes-like objects"
    );
}

static PyObject *module_utf8_chunk_bounds(PyObject *self, PyObject *args) {
    PyObject *payload = NULL;
    Py_ssize_t chunk_size = 0;
    TDSStableInput input;
    Py_ssize_t *bounds = NULL;
    Py_ssize_t count;
    PyObject *list = NULL;
    UTF8Error error;
    (void)self;

    if (!PyArg_ParseTuple(args, "On", &payload, &chunk_size)) return NULL;
    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk size must be positive");
        return NULL;
    }
    if (stable_input_acquire(payload, &input, "UTF-8") < 0) return NULL;
    if (input.len == 0) {
        stable_input_release(&input);
        return PyList_New(0);
    }
    if ((size_t)input.len > SIZE_MAX / sizeof(Py_ssize_t)) {
        stable_input_release(&input);
        PyErr_SetString(PyExc_OverflowError, "UTF-8 boundary allocation overflow");
        return NULL;
    }
    bounds = (Py_ssize_t *)PyMem_Malloc((size_t)input.len * sizeof(Py_ssize_t));
    if (bounds == NULL) {
        stable_input_release(&input);
        PyErr_NoMemory();
        return NULL;
    }
    diag_note_gil_released(DIAG_COUNTER_NATIVE_CHUNK_SCAN_CALLS);
    Py_BEGIN_ALLOW_THREADS
    count = utf8_plan_bounds_nogil(
        (const unsigned char *)input.data,
        input.len,
        chunk_size,
        bounds,
        input.len,
        &error
    );
    Py_END_ALLOW_THREADS
    if (count < 0) {
        if (error.code == UTF8_ERROR_BOUND_CAPACITY) {
            PyErr_SetString(PyExc_OverflowError, "UTF-8 boundary capacity exceeded");
        } else {
            utf8_raise_decode_error(&input, &error);
        }
        goto done;
    }
    list = PyList_New(count);
    if (list == NULL) goto done;
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *value = PyLong_FromSsize_t(bounds[i]);
        if (value == NULL) {
            Py_CLEAR(list);
            goto done;
        }
        PyList_SET_ITEM(list, i, value);
    }

done:
    PyMem_Free(bounds);
    stable_input_release(&input);
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
    {"checksum32", module_checksum32_legacy, METH_VARARGS, "Historical FNV-1a 32-bit checksum over an immutable input snapshot."},
    {"checksum32_many", module_checksum32_many_legacy, METH_VARARGS, "Historical batch FNV-1a checksums over immutable input snapshots."},
    {"checksum32_for_algorithm", module_checksum32_for_algorithm, METH_VARARGS, "Compute a registered 32-bit checksum over an immutable input snapshot."},
    {"checksum32_many_for_algorithm", module_checksum32_many_for_algorithm, METH_VARARGS, "Compute registered 32-bit checksums over immutable input snapshots."},
    {"spiral_rank_scores", (PyCFunction)module_spiral_rank_scores, METH_VARARGS | METH_KEYWORDS, "Native Spiral rank scoring loop with released GIL."},
    {"utf8_chunk_bounds", module_utf8_chunk_bounds, METH_VARARGS, "Return strict RFC 3629 complete-codepoint chunk boundaries."},
    {"diag_snapshot", (PyCFunction)module_diag_snapshot, METH_VARARGS | METH_KEYWORDS, "Return immutable native diagnostic snapshot."},
    {"diag_reset", module_diag_reset, METH_NOARGS, "Reset native diagnostic counters and event ring."},
    {"diag_set_enabled", module_diag_set_enabled, METH_VARARGS, "Enable or disable native diagnostics."},
    {"diag_set_sampling", (PyCFunction)module_diag_set_sampling, METH_VARARGS | METH_KEYWORDS, "Set bounded automatic diagnostic sampling."},
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
    if (!diag_atomics_lock_free()) {
        PyErr_SetString(PyExc_RuntimeError, "native diagnostics requires lock-free C11 atomics");
        return NULL;
    }
    diag_initialize();
    m = PyModule_Create(&moduledef);
    if (!m) return NULL;
    if (PyModule_AddIntConstant(m, "TDS_NATIVE_ABI_VERSION", 1) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_ENGINE", "index") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_CAPABILITIES", "index,checksum32,checksum_registry,spiral_rank,utf8_chunks,utf8_strict,diagnostics,diagnostics_c11_ring,diagnostics_sampling") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_CHECKSUM_ALGORITHMS", "crc32-ieee-v1,fnv1a32-legacy-v1") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_UTF8_CHUNK_CONTRACT", "strict-rfc3629-complete-codepoints-v1") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_DIAG_PROTOCOL", "c11-atomic-slot-seqlock-mpsc-v1") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    if (PyModule_AddStringConstant(m, "TDS_NATIVE_DIAG_SAMPLING", "burst=64;period=1024;manual=all") < 0) {
        Py_DECREF(m);
        return NULL;
    }
    Py_INCREF(&NativeHandleIndexType);
    if (PyModule_AddObject(m, "NativeHandleIndex", (PyObject*)&NativeHandleIndexType) < 0) {
        Py_DECREF(&NativeHandleIndexType);
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
