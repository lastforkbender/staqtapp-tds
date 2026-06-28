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

typedef struct {
    PyObject_HEAD
    Slot *slots;
    Py_ssize_t capacity;
    Py_ssize_t size;
    Py_ssize_t tombstones;
    int64_t next_handle;
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

static Py_ssize_t round_pow2(Py_ssize_t n) {
    Py_ssize_t p = 16;
    while (p < n) p <<= 1;
    return p;
}

static void free_slots(Slot *slots, Py_ssize_t cap) {
    if (!slots) return;
    for (Py_ssize_t i = 0; i < cap; ++i) {
        if (slots[i].state == 1 && slots[i].key) free(slots[i].key);
    }
    free(slots);
}

static inline uint8_t ctrl_from_hash(uint64_t hash) {
    uint8_t c = (uint8_t)((hash >> 57) & 0x7F);
    return c ? c : 1;
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
        idx = (idx + probe + 1) & mask; /* triangular probing, Swiss-table inspired */
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

static void lookup_handles_nogil(NativeHandleIndex *self, const char **keys, Py_ssize_t *lens, Py_ssize_t n, int64_t *out) {
    pthread_rwlock_rdlock(&self->lock);
    for (Py_ssize_t i = 0; i < n; ++i) {
        uint64_t hash = fnv1a64(keys[i], lens[i]);
        int found = 0;
        Py_ssize_t idx = find_slot(self->slots, self->capacity, keys[i], lens[i], hash, &found);
        out[i] = (idx >= 0 && found) ? self->slots[idx].handle : -1;
    }
    pthread_rwlock_unlock(&self->lock);
}

static int64_t pop_handle_nogil(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    uint64_t hash = fnv1a64(key, len);
    int64_t out = -1;
    pthread_rwlock_wrlock(&self->lock);
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    if (idx >= 0 && found) {
        out = self->slots[idx].handle;
        free(self->slots[idx].key);
        self->slots[idx].key = NULL;
        self->slots[idx].len = 0;
        self->slots[idx].handle = 0;
        self->slots[idx].hash = 0;
        self->slots[idx].ctrl = 0;
        self->slots[idx].state = 2;
        self->size--;
        self->tombstones++;
    }
    pthread_rwlock_unlock(&self->lock);
    return out;
}

static int resize_index(NativeHandleIndex *self, Py_ssize_t newcap) {
    newcap = round_pow2(newcap);
    Slot *newslots = (Slot*)calloc((size_t)newcap, sizeof(Slot));
    if (!newslots) { PyErr_NoMemory(); return -1; }
    for (Py_ssize_t i = 0; i < self->capacity; ++i) {
        Slot *old = &self->slots[i];
        if (old->state != 1) continue;
        int found = 0;
        Py_ssize_t idx = find_slot(newslots, newcap, old->key, old->len, old->hash, &found);
        if (idx < 0) { free_slots(newslots, newcap); PyErr_SetString(PyExc_RuntimeError, "native index resize failed"); return -1; }
        newslots[idx] = *old;
        old->key = NULL;
        old->state = 0;
    }
    free_slots(self->slots, self->capacity);
    self->slots = newslots;
    self->capacity = newcap;
    self->tombstones = 0;
    return 0;
}

static int maybe_resize(NativeHandleIndex *self) {
    if ((self->size + self->tombstones) * 10 >= self->capacity * 7) {
        return resize_index(self, self->capacity * 2);
    }
    return 0;
}

static PyObject *NativeHandleIndex_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    NativeHandleIndex *self = (NativeHandleIndex*)type->tp_alloc(type, 0);
    if (!self) return NULL;
    self->slots = NULL;
    self->capacity = 0;
    self->size = 0;
    self->tombstones = 0;
    self->next_handle = 1;
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
    free_slots(self->slots, self->capacity);
    self->slots = NULL;
    pthread_rwlock_unlock(&self->lock);
    pthread_rwlock_destroy(&self->lock);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *NativeHandleIndex_put(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len; int64_t handle = 0;
    if (!PyArg_ParseTuple(args, "s#|L", &key, &len, &handle)) return NULL;
    if (len <= 0) { PyErr_SetString(PyExc_ValueError, "key must be non-empty bytes/str"); return NULL; }
    char *copy = NULL;
    uint64_t hash = fnv1a64(key, len);
    pthread_rwlock_wrlock(&self->lock);
    if (maybe_resize(self) < 0) { pthread_rwlock_unlock(&self->lock); return NULL; }
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    if (idx < 0) { pthread_rwlock_unlock(&self->lock); PyErr_SetString(PyExc_RuntimeError, "native index is full"); return NULL; }
    if (found) {
        if (handle > 0) self->slots[idx].handle = handle;
        handle = self->slots[idx].handle;
    } else {
        copy = (char*)malloc((size_t)len);
        if (!copy) { pthread_rwlock_unlock(&self->lock); PyErr_NoMemory(); return NULL; }
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
    }
    pthread_rwlock_unlock(&self->lock);
    return PyLong_FromLongLong(handle);
}

static int64_t lookup_handle_nogil(NativeHandleIndex *self, const char *key, Py_ssize_t len) {
    uint64_t hash = fnv1a64(key, len);
    int64_t out = -1;
    pthread_rwlock_rdlock(&self->lock);
    int found = 0;
    Py_ssize_t idx = find_slot(self->slots, self->capacity, key, len, hash, &found);
    if (idx >= 0 && found) out = self->slots[idx].handle;
    pthread_rwlock_unlock(&self->lock);
    return out;
}

static PyObject *NativeHandleIndex_get_handle(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
    Py_BEGIN_ALLOW_THREADS
    out = lookup_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_contains(NativeHandleIndex *self, PyObject *args) {
    const char *key; Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &key, &len)) return NULL;
    int64_t out;
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
    Py_BEGIN_ALLOW_THREADS
    out = pop_handle_nogil(self, key, len);
    Py_END_ALLOW_THREADS
    return PyLong_FromLongLong(out);
}

static PyObject *NativeHandleIndex_get_handles(NativeHandleIndex *self, PyObject *args) {
    PyObject *seq;
    if (!PyArg_ParseTuple(args, "O", &seq)) return NULL;
    PyObject *fast = PySequence_Fast(seq, "get_handles expects a sequence of bytes/str keys");
    if (!fast) return NULL;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
    const char **keys = (const char**)calloc((size_t)n, sizeof(char*));
    Py_ssize_t *lens = (Py_ssize_t*)calloc((size_t)n, sizeof(Py_ssize_t));
    int64_t *out = (int64_t*)calloc((size_t)n, sizeof(int64_t));
    if (!keys || !lens || !out) {
        free(keys); free(lens); free(out); Py_DECREF(fast); PyErr_NoMemory(); return NULL;
    }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *item = PySequence_Fast_GET_ITEM(fast, i);
        if (PyBytes_Check(item)) {
            if (PyBytes_AsStringAndSize(item, (char**)&keys[i], &lens[i]) < 0) {
                free(keys); free(lens); free(out); Py_DECREF(fast); return NULL;
            }
        } else if (PyUnicode_Check(item)) {
            keys[i] = PyUnicode_AsUTF8AndSize(item, &lens[i]);
            if (!keys[i]) { free(keys); free(lens); free(out); Py_DECREF(fast); return NULL; }
        } else {
            free(keys); free(lens); free(out); Py_DECREF(fast);
            PyErr_SetString(PyExc_TypeError, "get_handles keys must be bytes or str");
            return NULL;
        }
    }
    Py_BEGIN_ALLOW_THREADS
    lookup_handles_nogil(self, keys, lens, n, out);
    Py_END_ALLOW_THREADS
    PyObject *list = PyList_New(n);
    if (!list) { free(keys); free(lens); free(out); Py_DECREF(fast); return NULL; }
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject *v = PyLong_FromLongLong(out[i]);
        if (!v) { Py_DECREF(list); free(keys); free(lens); free(out); Py_DECREF(fast); return NULL; }
        PyList_SET_ITEM(list, i, v);
    }
    free(keys); free(lens); free(out); Py_DECREF(fast);
    return list;
}

static PyObject *NativeHandleIndex_size(NativeHandleIndex *self, PyObject *Py_UNUSED(ignored)) {
    Py_ssize_t size;
    pthread_rwlock_rdlock(&self->lock);
    size = self->size;
    pthread_rwlock_unlock(&self->lock);
    return PyLong_FromSsize_t(size);
}

static PyObject *NativeHandleIndex_stats(NativeHandleIndex *self, PyObject *Py_UNUSED(ignored)) {
    PyObject *d = PyDict_New();
    if (!d) return NULL;
    pthread_rwlock_rdlock(&self->lock);
    PyDict_SetItemString(d, "backend", PyUnicode_FromString("native-c-swiss-entryindex"));
    PyDict_SetItemString(d, "size", PyLong_FromSsize_t(self->size));
    Py_ssize_t max_probe = 0;
    double avg_probe = 0.0;
    for (Py_ssize_t i = 0; i < self->capacity; ++i) {
        if (self->slots[i].state == 1) {
            Py_ssize_t p = probe_length_for_slot(self->slots, self->capacity, &self->slots[i]);
            if (p > max_probe) max_probe = p;
            avg_probe += (double)p;
        }
    }
    if (self->size > 0) avg_probe /= (double)self->size;
    PyDict_SetItemString(d, "capacity", PyLong_FromSsize_t(self->capacity));
    PyDict_SetItemString(d, "tombstones", PyLong_FromSsize_t(self->tombstones));
    PyDict_SetItemString(d, "load_factor", PyFloat_FromDouble(self->capacity ? ((double)self->size / (double)self->capacity) : 0.0));
    PyDict_SetItemString(d, "max_probe", PyLong_FromSsize_t(max_probe));
    PyDict_SetItemString(d, "avg_probe", PyFloat_FromDouble(avg_probe));
    PyDict_SetItemString(d, "next_handle", PyLong_FromLongLong(self->next_handle));
    PyDict_SetItemString(d, "gil_released_get_handle", Py_True);
    PyDict_SetItemString(d, "gil_released_get_handles", Py_True);
    PyDict_SetItemString(d, "gil_released_pop_lookup", Py_True);
    PyDict_SetItemString(d, "swiss_control_bytes", Py_True);
    PyDict_SetItemString(d, "probing", PyUnicode_FromString("triangular"));
    pthread_rwlock_unlock(&self->lock);
    return d;
}

static PyMethodDef NativeHandleIndex_methods[] = {
    {"put", (PyCFunction)NativeHandleIndex_put, METH_VARARGS, "Insert key and return stable int64 handle."},
    {"get_handle", (PyCFunction)NativeHandleIndex_get_handle, METH_VARARGS, "Get handle for key. Releases the GIL during native lookup."},
    {"get_handles", (PyCFunction)NativeHandleIndex_get_handles, METH_VARARGS, "Get handles for keys. Releases the GIL during native batch lookup."},
    {"contains", (PyCFunction)NativeHandleIndex_contains, METH_VARARGS, "Return whether key exists. Releases the GIL during native lookup."},
    {"pop", (PyCFunction)NativeHandleIndex_pop, METH_VARARGS, "Remove key and return its handle or -1."},
    {"size", (PyCFunction)NativeHandleIndex_size, METH_NOARGS, "Return size."},
    {"stats", (PyCFunction)NativeHandleIndex_stats, METH_NOARGS, "Return native index stats."},
    {NULL}
};

static PyTypeObject NativeHandleIndexType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "staqtapp_tds._native_index.NativeHandleIndex",
    .tp_doc = "Native Swiss-table-inspired bytes->int64 handle index with GIL-released reads.",
    .tp_basicsize = sizeof(NativeHandleIndex),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = NativeHandleIndex_new,
    .tp_init = (initproc)NativeHandleIndex_init,
    .tp_dealloc = (destructor)NativeHandleIndex_dealloc,
    .tp_methods = NativeHandleIndex_methods,
};

static PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_native_index",
    .m_doc = "Staqtapp-TDS optional native EntryIndex primitive.",
    .m_size = -1,
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
