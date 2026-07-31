#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>

static int run_code(const char *code) {
    int status = PyRun_SimpleString(code);
    if (status != 0 && PyErr_Occurred()) {
        PyErr_Print();
    }
    return status;
}

int main(void) {
    PyThreadState *main_state;
    PyThreadState *sub_state;
    PyConfig config;
    PyStatus init_status;
    int status = 0;

    PyConfig_InitPythonConfig(&config);
    config.site_import = 0;
    config.user_site_directory = 0;
    init_status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(init_status) || !Py_IsInitialized()) {
        fputs("Python initialization failed\n", stderr);
        return 1;
    }
    if (run_code(
            "import importlib.util\n"
            "from pathlib import Path\n"
            "paths = sorted(Path('src/staqtapp_tds').glob('_native_index*.so'))\n"
            "assert len(paths) == 1, paths\n"
            "spec = importlib.util.spec_from_file_location('_native_index', paths[0])\n"
            "native = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(native)\n"
            "assert native.TDS_NATIVE_MODULE_INIT == 'multiphase-pep489-v1'\n") != 0) {
        status = 1;
        goto finalize;
    }

    main_state = PyThreadState_Get();
    sub_state = Py_NewInterpreter();
    if (sub_state == NULL) {
        PyErr_Print();
        status = 1;
        goto finalize;
    }
    if (run_code(
            "import importlib.util\n"
            "from pathlib import Path\n"
            "paths = sorted(Path('src/staqtapp_tds').glob('_native_index*.so'))\n"
            "assert len(paths) == 1, paths\n"
            "try:\n"
            "    spec = importlib.util.spec_from_file_location('_native_index', paths[0])\n"
            "    native = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(native)\n"
            "except (ImportError, RuntimeError):\n"
            "    pass\n"
            "else:\n"
            "    raise RuntimeError('native subinterpreter import was accepted')\n") != 0) {
        status = 1;
    }
    Py_EndInterpreter(sub_state);
    (void)PyThreadState_Swap(main_state);

finalize:
    if (Py_FinalizeEx() < 0) {
        status = 1;
    }
    if (status == 0) {
        puts("v3.6 native subinterpreter admission rejection passed");
    }
    return status;
}
