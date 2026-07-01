#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

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
    return (idx >= 0 && found) ? self->slots[idx].handle : -1;
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
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_put_calls);
    Py_BEGIN_ALLOW_THREADS
    rc = put_handle_nogil(self, key, len, handle, &out_handle);
    Py_END_ALLOW_THREADS
    if (rc == -1) { PyErr_NoMemory(); return NULL; }
    if (rc == -2) { PyErr_SetString(PyExc_RuntimeError, "native index is full"); return NULL; }
    return PyLong_FromLongLong(out_handle);
}

static void free_key_sequence(const char **keys, Py_ssize_t *lens, Py_ssize_t n) {
    if (keys) {
        for (Py_ssize_t i = 0; i < n; ++i) free((void*)keys[i]);
    }
    free((void*)keys);
    free(lens);
}

/*
 * Copy a Python sequence of bytes/str keys into native-owned memory before
 * entering GIL-released batch operations. This avoids holding borrowed pointers
 * into a caller-owned mutable list while another Python thread could mutate that
 * list and drop the last reference to one of its items.
 */
static int extract_key_sequence(PyObject *seq, const char ***keys_out, Py_ssize_t **lens_out, Py_ssize_t *n_out) {
    PyObject *fast = PySequence_Fast(seq, "expected a sequence of bytes/str keys");
    if (!fast) return -1;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
    const char **keys = (const char**)calloc((size_t)n, sizeof(char*));
    Py_ssize_t *lens = (Py_ssize_t*)calloc((size_t)n, sizeof(Py_ssize_t));
    if (!keys || !lens) { free_key_sequence(keys, lens, n); PyErr_NoMemory(); return -1; }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *item = PySequence_Fast_GET_ITEM(fast, i);
        const char *src = NULL;
        Py_ssize_t len = 0;
        if (PyBytes_Check(item)) {
            if (PyBytes_AsStringAndSize(item, (char**)&src, &len) < 0) { free_key_sequence(keys, lens, n); Py_DECREF(fast); return -1; }
        } else if (PyUnicode_Check(item)) {
            src = PyUnicode_AsUTF8AndSize(item, &len);
            if (!src) { free_key_sequence(keys, lens, n); Py_DECREF(fast); return -1; }
        } else {
            free_key_sequence(keys, lens, n); Py_DECREF(fast);
            PyErr_SetString(PyExc_TypeError, "keys must be bytes or str");
            return -1;
        }
        if (len <= 0) { free_key_sequence(keys, lens, n); Py_DECREF(fast); PyErr_SetString(PyExc_ValueError, "keys must be non-empty"); return -1; }
        char *copy = (char*)malloc((size_t)len);
        if (!copy) { free_key_sequence(keys, lens, n); Py_DECREF(fast); PyErr_NoMemory(); return -1; }
        memcpy(copy, src, (size_t)len);
        keys[i] = copy;
        lens[i] = len;
    }
    Py_DECREF(fast);
    *keys_out = keys; *lens_out = lens; *n_out = n; return 0;
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
    const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free_key_sequence(keys, lens, n); PyErr_NoMemory(); return NULL; }
    int rc;
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_put_calls);
    Py_BEGIN_ALLOW_THREADS
    rc = put_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    free_key_sequence(keys, lens, n);
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
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_lookup_calls);
    Py_BEGIN_ALLOW_THREADS
    out = lookup_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_contains(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_lookup_calls);
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
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_pop_calls);
    Py_BEGIN_ALLOW_THREADS
    out = pop_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_get_handles(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free_key_sequence(keys, lens, n); PyErr_NoMemory(); return NULL; }
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_lookup_calls);
    Py_BEGIN_ALLOW_THREADS
    lookup_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    PyObject *list = int64_list_from_array(out, n);
    free_key_sequence(keys, lens, n); free(out);
    return list;
}

static PyObject *NativeHandleIndex_pop_many(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    const char **keys = NULL; Py_ssize_t *lens = NULL; Py_ssize_t n = 0;
    if (extract_key_sequence(seq, &keys, &lens, &n) < 0) return NULL;
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!out) { free_key_sequence(keys, lens, n); PyErr_NoMemory(); return NULL; }
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_batch_pop_calls);
    Py_BEGIN_ALLOW_THREADS
    pop_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    PyObject *list = int64_list_from_array(out, n);
    free_key_sequence(keys, lens, n); free(out);
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
    bump_u64(&self->python_native_transitions); bump_u64(&self->gil_released_calls); bump_u64(&self->native_stats_calls);
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

static PyObject *module_checksum32(PyObject *self, PyObject *args) {
    const char *data; Py_ssize_t len; uint32_t out;
    if (!PyArg_ParseTuple(args, "y#", &data, &len)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    out = checksum32_nogil(data, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromUnsignedLong((unsigned long)out);
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
    {"utf8_chunk_bounds", module_utf8_chunk_bounds, METH_VARARGS, "Return UTF-8 safe chunk end offsets with GIL released."},
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
