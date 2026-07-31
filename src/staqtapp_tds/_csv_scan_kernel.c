#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

/*
 * Native CSV scanner safety rule:
 *
 * - exact bytes are held by a strong reference and may be scanned zero-copy;
 * - every other contiguous buffer is copied once while the GIL is held;
 * - only the immutable owned snapshot is read while the GIL is released.
 *
 * This keeps mutable exporters out of the GIL-free scan and closes the
 * two-pass row-count/offset race without adding storage or semantic authority.
 */
typedef struct {
    PyObject *owner;
    const unsigned char *data;
    Py_ssize_t len;
} CsvStableInput;

static void csv_stable_input_init(CsvStableInput *input) {
    input->owner = NULL;
    input->data = NULL;
    input->len = 0;
}

static void csv_stable_input_release(CsvStableInput *input) {
    Py_CLEAR(input->owner);
    input->data = NULL;
    input->len = 0;
}

static int csv_stable_input_acquire(PyObject *object, CsvStableInput *input) {
    Py_buffer view;
    PyObject *snapshot = NULL;

    csv_stable_input_init(input);
    if (PyBytes_CheckExact(object)) {
        Py_INCREF(object);
        input->owner = object;
        input->data = (const unsigned char *)PyBytes_AS_STRING(object);
        input->len = PyBytes_GET_SIZE(object);
        return 0;
    }

    if (PyObject_GetBuffer(object, &view, PyBUF_CONTIG_RO) < 0) {
        return -1;
    }
    if (view.len < 0) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "CSV input buffer length must not be negative");
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
    input->data = (const unsigned char *)PyBytes_AS_STRING(snapshot);
    input->len = PyBytes_GET_SIZE(snapshot);
    return 0;
}

static int csv_validate_tokens(
    int delimiter,
    int quote,
    int escape,
    Py_ssize_t chunk_size,
    const char *message
) {
    if (delimiter < 0 || delimiter > 255 || quote < 0 || quote > 255
            || escape < -1 || escape > 255 || chunk_size < 0) {
        PyErr_SetString(PyExc_ValueError, message);
        return -1;
    }
    return 0;
}

static Py_ssize_t csv_chunk_count(Py_ssize_t n, Py_ssize_t chunk_size) {
    if (n <= 0) {
        return 0;
    }
    if (chunk_size == 0) {
        return 1;
    }
    return (n / chunk_size) + ((n % chunk_size) != 0);
}

static Py_ssize_t *csv_allocate_offsets(Py_ssize_t row_count) {
    size_t count;

    if (row_count <= 0) {
        return NULL;
    }
    count = (size_t)row_count;
    if (count > SIZE_MAX / sizeof(Py_ssize_t)) {
        PyErr_SetString(PyExc_OverflowError, "CSV row-offset allocation overflow");
        return NULL;
    }

    Py_ssize_t *offsets = (Py_ssize_t *)PyMem_Malloc(
        count * sizeof(Py_ssize_t)
    );
    if (offsets == NULL) {
        PyErr_NoMemory();
    }
    return offsets;
}

static int csv_dict_set_ssize(PyObject *dict, const char *name, Py_ssize_t value) {
    PyObject *item = PyLong_FromSsize_t(value);
    int status;

    if (item == NULL) {
        return -1;
    }
    status = PyDict_SetItemString(dict, name, item);
    Py_DECREF(item);
    return status;
}

static int csv_dict_set_bool(PyObject *dict, const char *name, int value) {
    PyObject *item = PyBool_FromLong(value ? 1 : 0);
    int status;

    if (item == NULL) {
        return -1;
    }
    status = PyDict_SetItemString(dict, name, item);
    Py_DECREF(item);
    return status;
}

static void scan_counts(
    const unsigned char *buf,
    Py_ssize_t n,
    int delimiter,
    int quote,
    int escape,
    int doublequote,
    Py_ssize_t *row_count,
    Py_ssize_t *newline_lf_count,
    Py_ssize_t *newline_crlf_count,
    Py_ssize_t *newline_cr_count,
    Py_ssize_t *quoted_newline_count,
    Py_ssize_t *delimiter_count,
    Py_ssize_t *quote_count,
    Py_ssize_t *escaped_quote_count,
    Py_ssize_t *escape_sequence_count,
    Py_ssize_t *max_record_span,
    int *ended_in_open_quote
) {
    int in_quotes = 0;
    Py_ssize_t offsets = n == 0 ? 0 : 1;
    Py_ssize_t lf = 0;
    Py_ssize_t crlf = 0;
    Py_ssize_t cr = 0;
    Py_ssize_t quoted_nl = 0;
    Py_ssize_t delimiters = 0;
    Py_ssize_t quotes = 0;
    Py_ssize_t escaped_quotes = 0;
    Py_ssize_t escape_sequences = 0;
    Py_ssize_t last_record_start = 0;
    Py_ssize_t max_span = 0;
    Py_ssize_t i = 0;

    while (i < n) {
        unsigned char byte = buf[i];
        if (escape >= 0 && in_quotes && byte == (unsigned char)escape
                && i + 1 < n) {
            escape_sequences += 1;
            i += 2;
            continue;
        }

        if (byte == (unsigned char)quote) {
            int next_is_quote;

            quotes += 1;
            next_is_quote = (
                i + 1 < n && buf[i + 1] == (unsigned char)quote
            );
            if (in_quotes && doublequote && next_is_quote) {
                escaped_quotes += 1;
                quotes += 1;
                i += 2;
                continue;
            }
            in_quotes = !in_quotes;
        } else if (byte == (unsigned char)delimiter && !in_quotes) {
            delimiters += 1;
        } else if (byte == 10 || byte == 13) {
            int is_crlf = (
                byte == 13 && i + 1 < n && buf[i + 1] == 10
            );
            if (in_quotes) {
                quoted_nl += 1;
                if (is_crlf) {
                    i += 1;
                }
            } else {
                Py_ssize_t next_offset;

                if (is_crlf) {
                    crlf += 1;
                    i += 1;
                } else if (byte == 10) {
                    lf += 1;
                } else {
                    cr += 1;
                }
                next_offset = i + 1;
                if (next_offset < n) {
                    Py_ssize_t span = next_offset - last_record_start;
                    if (span > max_span) {
                        max_span = span;
                    }
                    offsets += 1;
                    last_record_start = next_offset;
                }
            }
        }
        i += 1;
    }

    if (n > 0) {
        Py_ssize_t tail_span = n - last_record_start;
        if (tail_span > max_span) {
            max_span = tail_span;
        }
    }

    *row_count = offsets;
    *newline_lf_count = lf;
    *newline_crlf_count = crlf;
    *newline_cr_count = cr;
    *quoted_newline_count = quoted_nl;
    *delimiter_count = delimiters;
    *quote_count = quotes;
    *escaped_quote_count = escaped_quotes;
    *escape_sequence_count = escape_sequences;
    *max_record_span = max_span;
    *ended_in_open_quote = in_quotes;
}

static int fill_offsets(
    const unsigned char *buf,
    Py_ssize_t n,
    int quote,
    int escape,
    int doublequote,
    Py_ssize_t *offsets,
    Py_ssize_t capacity,
    Py_ssize_t *written
) {
    int in_quotes = 0;
    Py_ssize_t out = 0;
    Py_ssize_t i = 0;

    *written = 0;
    if (n == 0) {
        return capacity == 0 ? 0 : -1;
    }
    if (offsets == NULL || capacity <= 0) {
        return -1;
    }

    offsets[out++] = 0;
    while (i < n) {
        unsigned char byte = buf[i];
        if (escape >= 0 && in_quotes && byte == (unsigned char)escape
                && i + 1 < n) {
            i += 2;
            continue;
        }
        if (byte == (unsigned char)quote) {
            int next_is_quote = (
                i + 1 < n && buf[i + 1] == (unsigned char)quote
            );
            if (in_quotes && doublequote && next_is_quote) {
                i += 2;
                continue;
            }
            in_quotes = !in_quotes;
        } else if (byte == 10 || byte == 13) {
            int is_crlf = (
                byte == 13 && i + 1 < n && buf[i + 1] == 10
            );
            if (in_quotes) {
                if (is_crlf) {
                    i += 1;
                }
            } else {
                Py_ssize_t next_offset;

                if (is_crlf) {
                    i += 1;
                }
                next_offset = i + 1;
                if (next_offset < n) {
                    if (out >= capacity) {
                        return -1;
                    }
                    offsets[out++] = next_offset;
                }
            }
        }
        i += 1;
    }

    *written = out;
    return 0;
}

static int csv_fill_offsets_checked(
    const CsvStableInput *input,
    int quote,
    int escape,
    int doublequote,
    Py_ssize_t *offsets,
    Py_ssize_t row_count
) {
    int status;
    Py_ssize_t written = 0;

    Py_BEGIN_ALLOW_THREADS
    status = fill_offsets(
        input->data,
        input->len,
        quote,
        escape,
        doublequote,
        offsets,
        row_count,
        &written
    );
    Py_END_ALLOW_THREADS

    if (status < 0 || written != row_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "CSV row-count/offset invariant failed for stable input"
        );
        return -1;
    }
    return 0;
}

static PyObject *csv_offsets_tuple(
    const Py_ssize_t *offsets,
    Py_ssize_t row_count
) {
    PyObject *tuple = PyTuple_New(row_count);

    if (tuple == NULL) {
        return NULL;
    }
    for (Py_ssize_t i = 0; i < row_count; ++i) {
        PyObject *value = PyLong_FromSsize_t(offsets[i]);
        if (value == NULL) {
            Py_DECREF(tuple);
            return NULL;
        }
        PyTuple_SET_ITEM(tuple, i, value);
    }
    return tuple;
}

static PyObject *csv_scan_kernel_scan_bytes(
    PyObject *self,
    PyObject *args,
    PyObject *kwargs
) {
    PyObject *raw_object = NULL;
    CsvStableInput input;
    int delimiter = ',';
    int quote = '"';
    int escape = -1;
    int doublequote = 1;
    Py_ssize_t chunk_size = 0;
    Py_ssize_t row_count = 0;
    Py_ssize_t newline_lf_count = 0;
    Py_ssize_t newline_crlf_count = 0;
    Py_ssize_t newline_cr_count = 0;
    Py_ssize_t quoted_newline_count = 0;
    Py_ssize_t delimiter_count = 0;
    Py_ssize_t quote_count = 0;
    Py_ssize_t escaped_quote_count = 0;
    Py_ssize_t escape_sequence_count = 0;
    Py_ssize_t max_record_span = 0;
    Py_ssize_t *offsets_raw = NULL;
    PyObject *offsets_tuple = NULL;
    PyObject *result = NULL;
    int ended_in_open_quote = 0;
    int terminal_newline;
    static char *kwlist[] = {
        "raw", "delimiter", "quote", "escape", "doublequote", "chunk_size", NULL
    };

    (void)self;
    csv_stable_input_init(&input);
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "Oiiiin:scan_bytes",
            kwlist,
            &raw_object,
            &delimiter,
            &quote,
            &escape,
            &doublequote,
            &chunk_size)) {
        return NULL;
    }
    if (csv_validate_tokens(
            delimiter,
            quote,
            escape,
            chunk_size,
            "CSV scan kernel tokens must be byte-sized and chunk_size must be non-negative") < 0) {
        return NULL;
    }
    if (csv_stable_input_acquire(raw_object, &input) < 0) {
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    scan_counts(
        input.data,
        input.len,
        delimiter,
        quote,
        escape,
        doublequote,
        &row_count,
        &newline_lf_count,
        &newline_crlf_count,
        &newline_cr_count,
        &quoted_newline_count,
        &delimiter_count,
        &quote_count,
        &escaped_quote_count,
        &escape_sequence_count,
        &max_record_span,
        &ended_in_open_quote
    );
    Py_END_ALLOW_THREADS

    offsets_raw = csv_allocate_offsets(row_count);
    if (row_count > 0 && offsets_raw == NULL) {
        goto error;
    }
    if (row_count > 0 && csv_fill_offsets_checked(
            &input,
            quote,
            escape,
            doublequote,
            offsets_raw,
            row_count) < 0) {
        goto error;
    }

    offsets_tuple = csv_offsets_tuple(offsets_raw, row_count);
    if (offsets_tuple == NULL) {
        goto error;
    }

    terminal_newline = (
        input.len > 0
        && (input.data[input.len - 1] == 10 || input.data[input.len - 1] == 13)
    );
    result = PyDict_New();
    if (result == NULL) {
        goto error;
    }

    if (csv_dict_set_ssize(result, "raw_size", input.len) < 0
            || PyDict_SetItemString(result, "row_offsets", offsets_tuple) < 0
            || csv_dict_set_ssize(result, "row_count", row_count) < 0
            || csv_dict_set_ssize(result, "newline_lf_count", newline_lf_count) < 0
            || csv_dict_set_ssize(result, "newline_crlf_count", newline_crlf_count) < 0
            || csv_dict_set_ssize(result, "newline_cr_count", newline_cr_count) < 0
            || csv_dict_set_ssize(result, "quoted_newline_count", quoted_newline_count) < 0
            || csv_dict_set_ssize(result, "delimiter_count", delimiter_count) < 0
            || csv_dict_set_ssize(result, "quote_count", quote_count) < 0
            || csv_dict_set_ssize(result, "escaped_quote_count", escaped_quote_count) < 0
            || csv_dict_set_ssize(result, "escape_sequence_count", escape_sequence_count) < 0
            || csv_dict_set_ssize(result, "max_record_span", max_record_span) < 0
            || csv_dict_set_bool(result, "terminal_newline", terminal_newline) < 0
            || csv_dict_set_bool(result, "ended_in_open_quote", ended_in_open_quote) < 0
            || csv_dict_set_ssize(
                result,
                "chunk_count",
                csv_chunk_count(input.len, chunk_size)) < 0) {
        goto error;
    }

    PyMem_Free(offsets_raw);
    Py_DECREF(offsets_tuple);
    csv_stable_input_release(&input);
    return result;

error:
    PyMem_Free(offsets_raw);
    Py_XDECREF(offsets_tuple);
    Py_XDECREF(result);
    csv_stable_input_release(&input);
    return NULL;
}

static PyObject *csv_scan_kernel_row_offsets(
    PyObject *self,
    PyObject *args,
    PyObject *kwargs
) {
    PyObject *raw_object = NULL;
    CsvStableInput input;
    int quote = '"';
    int escape = -1;
    int doublequote = 1;
    Py_ssize_t chunk_size = 0;
    Py_ssize_t row_count = 0;
    Py_ssize_t newline_lf_count = 0;
    Py_ssize_t newline_crlf_count = 0;
    Py_ssize_t newline_cr_count = 0;
    Py_ssize_t quoted_newline_count = 0;
    Py_ssize_t delimiter_count = 0;
    Py_ssize_t quote_count = 0;
    Py_ssize_t escaped_quote_count = 0;
    Py_ssize_t escape_sequence_count = 0;
    Py_ssize_t max_record_span = 0;
    Py_ssize_t *offsets_raw = NULL;
    PyObject *offsets_tuple = NULL;
    PyObject *spans_tuple = NULL;
    PyObject *result = NULL;
    int ended_in_open_quote = 0;
    static char *kwlist[] = {
        "raw", "quote", "escape", "doublequote", "chunk_size", NULL
    };

    (void)self;
    csv_stable_input_init(&input);
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "Oiiin:row_offsets",
            kwlist,
            &raw_object,
            &quote,
            &escape,
            &doublequote,
            &chunk_size)) {
        return NULL;
    }
    if (csv_validate_tokens(
            ',',
            quote,
            escape,
            chunk_size,
            "CSV row-offset kernel tokens must be byte-sized and chunk_size must be non-negative") < 0) {
        return NULL;
    }
    if (csv_stable_input_acquire(raw_object, &input) < 0) {
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    scan_counts(
        input.data,
        input.len,
        ',',
        quote,
        escape,
        doublequote,
        &row_count,
        &newline_lf_count,
        &newline_crlf_count,
        &newline_cr_count,
        &quoted_newline_count,
        &delimiter_count,
        &quote_count,
        &escaped_quote_count,
        &escape_sequence_count,
        &max_record_span,
        &ended_in_open_quote
    );
    Py_END_ALLOW_THREADS

    offsets_raw = csv_allocate_offsets(row_count);
    if (row_count > 0 && offsets_raw == NULL) {
        goto error;
    }
    if (row_count > 0 && csv_fill_offsets_checked(
            &input,
            quote,
            escape,
            doublequote,
            offsets_raw,
            row_count) < 0) {
        goto error;
    }

    offsets_tuple = PyTuple_New(row_count);
    spans_tuple = PyTuple_New(row_count);
    if (offsets_tuple == NULL || spans_tuple == NULL) {
        goto error;
    }
    for (Py_ssize_t i = 0; i < row_count; ++i) {
        Py_ssize_t start = offsets_raw[i];
        Py_ssize_t end = i + 1 < row_count ? offsets_raw[i + 1] : input.len;
        PyObject *offset_value;
        PyObject *span_value;

        if (start < 0 || end < start || end > input.len) {
            PyErr_SetString(PyExc_RuntimeError, "CSV row-offset ordering invariant failed");
            goto error;
        }
        offset_value = PyLong_FromSsize_t(start);
        span_value = PyLong_FromSsize_t(end - start);
        if (offset_value == NULL || span_value == NULL) {
            Py_XDECREF(offset_value);
            Py_XDECREF(span_value);
            goto error;
        }
        PyTuple_SET_ITEM(offsets_tuple, i, offset_value);
        PyTuple_SET_ITEM(spans_tuple, i, span_value);
    }

    result = PyDict_New();
    if (result == NULL) {
        goto error;
    }
    if (csv_dict_set_ssize(result, "raw_size", input.len) < 0
            || csv_dict_set_ssize(result, "row_count", row_count) < 0
            || csv_dict_set_ssize(
                result,
                "chunk_count",
                csv_chunk_count(input.len, chunk_size)) < 0
            || csv_dict_set_ssize(result, "max_record_span", max_record_span) < 0
            || PyDict_SetItemString(result, "row_offsets", offsets_tuple) < 0
            || PyDict_SetItemString(result, "row_spans", spans_tuple) < 0) {
        goto error;
    }

    PyMem_Free(offsets_raw);
    Py_DECREF(offsets_tuple);
    Py_DECREF(spans_tuple);
    csv_stable_input_release(&input);
    return result;

error:
    PyMem_Free(offsets_raw);
    Py_XDECREF(offsets_tuple);
    Py_XDECREF(spans_tuple);
    Py_XDECREF(result);
    csv_stable_input_release(&input);
    return NULL;
}

static PyMethodDef CsvScanKernelMethods[] = {
    {
        "scan_bytes",
        (PyCFunction)csv_scan_kernel_scan_bytes,
        METH_VARARGS | METH_KEYWORDS,
        "Scan CSV bytes with an immutable-input native sidecar."
    },
    {
        "row_offsets",
        (PyCFunction)csv_scan_kernel_row_offsets,
        METH_VARARGS | METH_KEYWORDS,
        "Return logical CSV row offsets and spans from an immutable input snapshot."
    },
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef csv_scan_kernel_module = {
    PyModuleDef_HEAD_INIT,
    "_csv_scan_kernel",
    "Optional native CSV scan prototype sidecar for Staqtapp-TDS.",
    -1,
    CsvScanKernelMethods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC PyInit__csv_scan_kernel(void) {
    PyObject *module = PyModule_Create(&csv_scan_kernel_module);

    if (module == NULL) {
        return NULL;
    }
    if (PyModule_AddStringConstant(
            module,
            "CSV_NATIVE_SCAN_KERNEL_ABI",
            "tds.csv.scan.kernel.prototype.v1") < 0
            || PyModule_AddStringConstant(
                module,
                "CSV_NATIVE_SCAN_KERNEL_BACKEND",
                "native.c.csv_scan.prototype") < 0
            || PyModule_AddStringConstant(
                module,
                "CSV_NATIVE_SCAN_INPUT_OWNERSHIP",
                "bytes-zero-copy;other-contiguous-buffers-snapshot") < 0) {
        Py_DECREF(module);
        return NULL;
    }
    return module;
}
