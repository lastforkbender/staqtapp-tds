#define PY_SSIZE_T_CLEAN
#include <Python.h>

static int scan_counts(
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
    if (n == 0) {
        *row_count = 0;
        *newline_lf_count = 0;
        *newline_crlf_count = 0;
        *newline_cr_count = 0;
        *quoted_newline_count = 0;
        *delimiter_count = 0;
        *quote_count = 0;
        *escaped_quote_count = 0;
        *escape_sequence_count = 0;
        *max_record_span = 0;
        *ended_in_open_quote = 0;
        return 0;
    }

    int in_quotes = 0;
    Py_ssize_t offsets = 1;
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
        if (escape >= 0 && in_quotes && byte == (unsigned char)escape && i + 1 < n) {
            escape_sequences += 1;
            i += 2;
            continue;
        }

        if (byte == (unsigned char)quote) {
            quotes += 1;
            int next_is_quote = (i + 1 < n && buf[i + 1] == (unsigned char)quote);
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
            int is_crlf = (byte == 13 && i + 1 < n && buf[i + 1] == 10);
            if (in_quotes) {
                quoted_nl += 1;
                if (is_crlf) {
                    i += 1;
                }
            } else {
                if (is_crlf) {
                    crlf += 1;
                    i += 1;
                } else if (byte == 10) {
                    lf += 1;
                } else {
                    cr += 1;
                }
                Py_ssize_t next_offset = i + 1;
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

    Py_ssize_t tail_span = n - last_record_start;
    if (tail_span > max_span) {
        max_span = tail_span;
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
    return 0;
}

static void fill_offsets(
    const unsigned char *buf,
    Py_ssize_t n,
    int quote,
    int escape,
    int doublequote,
    Py_ssize_t *offsets
) {
    if (n == 0) {
        return;
    }
    int in_quotes = 0;
    Py_ssize_t out = 0;
    offsets[out++] = 0;
    Py_ssize_t i = 0;
    while (i < n) {
        unsigned char byte = buf[i];
        if (escape >= 0 && in_quotes && byte == (unsigned char)escape && i + 1 < n) {
            i += 2;
            continue;
        }
        if (byte == (unsigned char)quote) {
            int next_is_quote = (i + 1 < n && buf[i + 1] == (unsigned char)quote);
            if (in_quotes && doublequote && next_is_quote) {
                i += 2;
                continue;
            }
            in_quotes = !in_quotes;
        } else if (byte == 10 || byte == 13) {
            int is_crlf = (byte == 13 && i + 1 < n && buf[i + 1] == 10);
            if (in_quotes) {
                if (is_crlf) {
                    i += 1;
                }
            } else {
                if (is_crlf) {
                    i += 1;
                }
                Py_ssize_t next_offset = i + 1;
                if (next_offset < n) {
                    offsets[out++] = next_offset;
                }
            }
        }
        i += 1;
    }
}

static PyObject *csv_scan_kernel_scan_bytes(PyObject *self, PyObject *args, PyObject *kwargs) {
    Py_buffer raw;
    int delimiter = ',';
    int quote = '"';
    int escape = -1;
    int doublequote = 1;
    Py_ssize_t chunk_size = 0;
    static char *kwlist[] = {"raw", "delimiter", "quote", "escape", "doublequote", "chunk_size", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*iiiin:scan_bytes", kwlist, &raw, &delimiter, &quote, &escape, &doublequote, &chunk_size)) {
        return NULL;
    }
    if (delimiter < 0 || delimiter > 255 || quote < 0 || quote > 255 || escape > 255 || chunk_size < 0) {
        PyBuffer_Release(&raw);
        PyErr_SetString(PyExc_ValueError, "CSV scan kernel tokens must be byte-sized and chunk_size must be non-negative");
        return NULL;
    }

    const unsigned char *buf = (const unsigned char *)raw.buf;
    Py_ssize_t n = raw.len;
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
    int ended_in_open_quote = 0;

    Py_BEGIN_ALLOW_THREADS
    scan_counts(
        buf, n, delimiter, quote, escape, doublequote,
        &row_count, &newline_lf_count, &newline_crlf_count, &newline_cr_count,
        &quoted_newline_count, &delimiter_count, &quote_count, &escaped_quote_count,
        &escape_sequence_count, &max_record_span, &ended_in_open_quote
    );
    Py_END_ALLOW_THREADS

    Py_ssize_t *offsets_raw = NULL;
    if (row_count > 0) {
        offsets_raw = (Py_ssize_t *)PyMem_Malloc(sizeof(Py_ssize_t) * (size_t)row_count);
        if (offsets_raw == NULL) {
            PyBuffer_Release(&raw);
            return PyErr_NoMemory();
        }
        Py_BEGIN_ALLOW_THREADS
        fill_offsets(buf, n, quote, escape, doublequote, offsets_raw);
        Py_END_ALLOW_THREADS
    }

    PyObject *offsets_tuple = PyTuple_New(row_count);
    if (offsets_tuple == NULL) {
        PyMem_Free(offsets_raw);
        PyBuffer_Release(&raw);
        return NULL;
    }
    for (Py_ssize_t i = 0; i < row_count; i++) {
        PyObject *value = PyLong_FromSsize_t(offsets_raw[i]);
        if (value == NULL) {
            Py_DECREF(offsets_tuple);
            PyMem_Free(offsets_raw);
            PyBuffer_Release(&raw);
            return NULL;
        }
        PyTuple_SET_ITEM(offsets_tuple, i, value);
    }
    PyMem_Free(offsets_raw);

    Py_ssize_t chunk_count = 0;
    if (n == 0) {
        chunk_count = 0;
    } else if (chunk_size == 0) {
        chunk_count = 1;
    } else {
        chunk_count = (n + chunk_size - 1) / chunk_size;
    }
    int terminal_newline = (n > 0 && (buf[n - 1] == 10 || buf[n - 1] == 13));

    PyObject *result = PyDict_New();
    if (result == NULL) {
        Py_DECREF(offsets_tuple);
        PyBuffer_Release(&raw);
        return NULL;
    }

#define SET_LONG_FIELD(name, value) do { \
        PyObject *_v = PyLong_FromSsize_t((Py_ssize_t)(value)); \
        if (_v == NULL || PyDict_SetItemString(result, name, _v) < 0) { \
            Py_XDECREF(_v); \
            Py_DECREF(offsets_tuple); \
            Py_DECREF(result); \
            PyBuffer_Release(&raw); \
            return NULL; \
        } \
        Py_DECREF(_v); \
    } while (0)
#define SET_BOOL_FIELD(name, value) do { \
        PyObject *_v = PyBool_FromLong((value) ? 1 : 0); \
        if (_v == NULL || PyDict_SetItemString(result, name, _v) < 0) { \
            Py_XDECREF(_v); \
            Py_DECREF(offsets_tuple); \
            Py_DECREF(result); \
            PyBuffer_Release(&raw); \
            return NULL; \
        } \
        Py_DECREF(_v); \
    } while (0)

    SET_LONG_FIELD("raw_size", n);
    if (PyDict_SetItemString(result, "row_offsets", offsets_tuple) < 0) {
        Py_DECREF(offsets_tuple);
        Py_DECREF(result);
        PyBuffer_Release(&raw);
        return NULL;
    }
    Py_DECREF(offsets_tuple);
    SET_LONG_FIELD("row_count", row_count);
    SET_LONG_FIELD("newline_lf_count", newline_lf_count);
    SET_LONG_FIELD("newline_crlf_count", newline_crlf_count);
    SET_LONG_FIELD("newline_cr_count", newline_cr_count);
    SET_LONG_FIELD("quoted_newline_count", quoted_newline_count);
    SET_LONG_FIELD("delimiter_count", delimiter_count);
    SET_LONG_FIELD("quote_count", quote_count);
    SET_LONG_FIELD("escaped_quote_count", escaped_quote_count);
    SET_LONG_FIELD("escape_sequence_count", escape_sequence_count);
    SET_LONG_FIELD("max_record_span", max_record_span);
    SET_BOOL_FIELD("terminal_newline", terminal_newline);
    SET_BOOL_FIELD("ended_in_open_quote", ended_in_open_quote);
    SET_LONG_FIELD("chunk_count", chunk_count);
#undef SET_LONG_FIELD
#undef SET_BOOL_FIELD

    PyBuffer_Release(&raw);
    return result;
}

static PyObject *csv_scan_kernel_row_offsets(PyObject *self, PyObject *args, PyObject *kwargs) {
    Py_buffer raw;
    int quote = '"';
    int escape = -1;
    int doublequote = 1;
    Py_ssize_t chunk_size = 0;
    static char *kwlist[] = {"raw", "quote", "escape", "doublequote", "chunk_size", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*iiin:row_offsets", kwlist, &raw, &quote, &escape, &doublequote, &chunk_size)) {
        return NULL;
    }
    if (quote < 0 || quote > 255 || escape > 255 || chunk_size < 0) {
        PyBuffer_Release(&raw);
        PyErr_SetString(PyExc_ValueError, "CSV row-offset kernel tokens must be byte-sized and chunk_size must be non-negative");
        return NULL;
    }

    const unsigned char *buf = (const unsigned char *)raw.buf;
    Py_ssize_t n = raw.len;
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
    int ended_in_open_quote = 0;

    Py_BEGIN_ALLOW_THREADS
    scan_counts(
        buf, n, ',', quote, escape, doublequote,
        &row_count, &newline_lf_count, &newline_crlf_count, &newline_cr_count,
        &quoted_newline_count, &delimiter_count, &quote_count, &escaped_quote_count,
        &escape_sequence_count, &max_record_span, &ended_in_open_quote
    );
    Py_END_ALLOW_THREADS

    Py_ssize_t *offsets_raw = NULL;
    if (row_count > 0) {
        offsets_raw = (Py_ssize_t *)PyMem_Malloc(sizeof(Py_ssize_t) * (size_t)row_count);
        if (offsets_raw == NULL) {
            PyBuffer_Release(&raw);
            return PyErr_NoMemory();
        }
        Py_BEGIN_ALLOW_THREADS
        fill_offsets(buf, n, quote, escape, doublequote, offsets_raw);
        Py_END_ALLOW_THREADS
    }

    PyObject *offsets_tuple = PyTuple_New(row_count);
    PyObject *spans_tuple = PyTuple_New(row_count);
    if (offsets_tuple == NULL || spans_tuple == NULL) {
        Py_XDECREF(offsets_tuple);
        Py_XDECREF(spans_tuple);
        PyMem_Free(offsets_raw);
        PyBuffer_Release(&raw);
        return NULL;
    }
    for (Py_ssize_t i = 0; i < row_count; i++) {
        Py_ssize_t start = offsets_raw[i];
        Py_ssize_t end = (i + 1 < row_count) ? offsets_raw[i + 1] : n;
        PyObject *offset_value = PyLong_FromSsize_t(start);
        PyObject *span_value = PyLong_FromSsize_t(end - start);
        if (offset_value == NULL || span_value == NULL) {
            Py_XDECREF(offset_value);
            Py_XDECREF(span_value);
            Py_DECREF(offsets_tuple);
            Py_DECREF(spans_tuple);
            PyMem_Free(offsets_raw);
            PyBuffer_Release(&raw);
            return NULL;
        }
        PyTuple_SET_ITEM(offsets_tuple, i, offset_value);
        PyTuple_SET_ITEM(spans_tuple, i, span_value);
    }
    PyMem_Free(offsets_raw);

    Py_ssize_t chunk_count = 0;
    if (n == 0) {
        chunk_count = 0;
    } else if (chunk_size == 0) {
        chunk_count = 1;
    } else {
        chunk_count = (n + chunk_size - 1) / chunk_size;
    }

    PyObject *result = PyDict_New();
    if (result == NULL) {
        Py_DECREF(offsets_tuple);
        Py_DECREF(spans_tuple);
        PyBuffer_Release(&raw);
        return NULL;
    }

#define SET_LONG_FIELD(name, value) do { \
        PyObject *_v = PyLong_FromSsize_t((Py_ssize_t)(value)); \
        if (_v == NULL || PyDict_SetItemString(result, name, _v) < 0) { \
            Py_XDECREF(_v); \
            Py_DECREF(offsets_tuple); \
            Py_DECREF(spans_tuple); \
            Py_DECREF(result); \
            PyBuffer_Release(&raw); \
            return NULL; \
        } \
        Py_DECREF(_v); \
    } while (0)

    SET_LONG_FIELD("raw_size", n);
    SET_LONG_FIELD("row_count", row_count);
    SET_LONG_FIELD("chunk_count", chunk_count);
    SET_LONG_FIELD("max_record_span", max_record_span);
#undef SET_LONG_FIELD

    if (PyDict_SetItemString(result, "row_offsets", offsets_tuple) < 0) {
        Py_DECREF(offsets_tuple);
        Py_DECREF(spans_tuple);
        Py_DECREF(result);
        PyBuffer_Release(&raw);
        return NULL;
    }
    Py_DECREF(offsets_tuple);
    if (PyDict_SetItemString(result, "row_spans", spans_tuple) < 0) {
        Py_DECREF(spans_tuple);
        Py_DECREF(result);
        PyBuffer_Release(&raw);
        return NULL;
    }
    Py_DECREF(spans_tuple);

    PyBuffer_Release(&raw);
    return result;
}

static PyMethodDef CsvScanKernelMethods[] = {
    {"scan_bytes", (PyCFunction)csv_scan_kernel_scan_bytes, METH_VARARGS | METH_KEYWORDS, "Scan CSV bytes with the optional native CSV scan prototype sidecar."},
    {"row_offsets", (PyCFunction)csv_scan_kernel_row_offsets, METH_VARARGS | METH_KEYWORDS, "Return native logical CSV row offsets and spans for row-anchor parity."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef csv_scan_kernel_module = {
    PyModuleDef_HEAD_INIT,
    "_csv_scan_kernel",
    "Optional native CSV scan prototype sidecar for Staqtapp-TDS.",
    -1,
    CsvScanKernelMethods
};

PyMODINIT_FUNC PyInit__csv_scan_kernel(void) {
    PyObject *module = PyModule_Create(&csv_scan_kernel_module);
    if (module == NULL) {
        return NULL;
    }
    PyModule_AddStringConstant(module, "CSV_NATIVE_SCAN_KERNEL_ABI", "tds.csv.scan.kernel.prototype.v1");
    PyModule_AddStringConstant(module, "CSV_NATIVE_SCAN_KERNEL_BACKEND", "native.c.csv_scan.prototype");
    return module;
}
