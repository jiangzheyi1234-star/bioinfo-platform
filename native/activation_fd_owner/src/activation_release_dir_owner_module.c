#include "activation_release_dir_owner_internal.h"

static PyObject *h2ometa_open_child(PyObject *self, PyObject *args) {
    PyObject *parent_capsule;
    PyObject *component_object;
    PyObject *child_capsule;
    H2OMetaDirOwner *parent;
    H2OMetaDirOwner *child = NULL;
    const char *component;
    Py_ssize_t component_length;
    struct open_how how = {
        .flags = H2OMETA_OPEN_FLAGS,
        .mode = 0,
        .resolve = H2OMETA_RESOLVE_FLAGS,
    };
    long result = -1;
    int attempt;
    int saved_errno = EIO;

    (void)self;
    if (!PyArg_ParseTuple(
            args,
            "OO:_open_child",
            &parent_capsule,
            &component_object
        )) {
        return NULL;
    }
    parent = h2ometa_owner_from_capsule(parent_capsule);
    if (parent == NULL || h2ometa_require_live_owner(parent) < 0) {
        return NULL;
    }
    if (h2ometa_require_component(
            component_object,
            &component,
            &component_length
        ) < 0) {
        return NULL;
    }
    child_capsule = h2ometa_new_owner_capsule(&child);
    if (child_capsule == NULL) {
        return NULL;
    }

#ifdef H2OMETA_NATIVE_TESTING
    h2ometa_test_reset_attempts();
#endif
    for (attempt = 0; attempt < H2OMETA_OPENAT2_MAX_ATTEMPTS; attempt += 1) {
        result = h2ometa_openat2_once(
            parent,
            component,
            component_length,
            &how
        );
        if (result >= 0) {
            child->fd = (int)result;
#ifdef H2OMETA_NATIVE_TESTING
            h2ometa_test_state.fd_adoptions += 1;
#endif
            break;
        }
        saved_errno = errno;
        if (saved_errno != EAGAIN ||
            attempt + 1 == H2OMETA_OPENAT2_MAX_ATTEMPTS) {
            Py_DecRef(child_capsule);
            h2ometa_set_errno_error(saved_errno);
            return NULL;
        }
    }
    if (child->fd < 0) {
        Py_DecRef(child_capsule);
        h2ometa_set_errno_error(EIO);
        return NULL;
    }
#ifdef H2OMETA_NATIVE_TESTING
    if (h2ometa_test_state.raise_sigint_after_adopt) {
        (void)raise(SIGINT);
    }
#endif
    if (h2ometa_finish_adoption(child, parent->uid) < 0) {
        Py_DecRef(child_capsule);
        return NULL;
    }
    return child_capsule;
}

static PyObject *h2ometa_require_live(PyObject *self, PyObject *args) {
    PyObject *capsule;
    H2OMetaDirOwner *owner;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_require_live", &capsule)) {
        return NULL;
    }
    owner = h2ometa_owner_from_capsule(capsule);
    if (owner == NULL || h2ometa_require_live_owner(owner) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *h2ometa_close_owner(PyObject *self, PyObject *args) {
    PyObject *capsule;
    H2OMetaDirOwner *owner;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_close", &capsule)) {
        return NULL;
    }
    owner = h2ometa_owner_from_capsule(capsule);
    if (owner == NULL || h2ometa_consume_owner_fd(owner, 1) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

#ifdef H2OMETA_NATIVE_TESTING
static int h2ometa_require_plain_fd(PyObject *value, int *fd_out) {
    long candidate;

    if (!PyLong_CheckExact(value)) {
        PyErr_SetString(PyExc_TypeError, "invalid test directory descriptor");
        return -1;
    }
    candidate = PyLong_AsLong(value);
    if (candidate < 0 || candidate > INT_MAX || PyErr_Occurred()) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError, "invalid test directory descriptor");
        }
        return -1;
    }
    *fd_out = (int)candidate;
    return 0;
}

static PyObject *h2ometa_test_duplicate_directory(PyObject *self, PyObject *args) {
    PyObject *fd_object;
    PyObject *capsule;
    H2OMetaDirOwner *owner = NULL;
    int source_fd;
    int result;
    int saved_errno;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_test_duplicate_directory", &fd_object)) {
        return NULL;
    }
    if (h2ometa_require_plain_fd(fd_object, &source_fd) < 0) {
        return NULL;
    }
    capsule = h2ometa_new_owner_capsule(&owner);
    if (capsule == NULL) {
        return NULL;
    }
    result = fcntl(source_fd, F_DUPFD_CLOEXEC, 0);
    if (result >= 0) {
        owner->fd = result;
#ifdef H2OMETA_NATIVE_TESTING
        h2ometa_test_state.fd_adoptions += 1;
#endif
    } else {
        saved_errno = errno;
        Py_DecRef(capsule);
        h2ometa_set_errno_error(saved_errno);
        return NULL;
    }
    if (h2ometa_finish_adoption(owner, geteuid()) < 0) {
        Py_DecRef(capsule);
        return NULL;
    }
    return capsule;
}

static PyObject *h2ometa_test_set_openat2_errnos(PyObject *self, PyObject *args) {
    PyObject *sequence;
    Py_ssize_t count;
    Py_ssize_t index;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_test_set_openat2_errnos", &sequence)) {
        return NULL;
    }
    if (!PyTuple_Check(sequence)) {
        PyErr_SetString(PyExc_TypeError, "openat2 errno script must be a tuple");
        return NULL;
    }
    count = PyTuple_Size(sequence);
    if (count < 0) {
        return NULL;
    }
    if (count > H2OMETA_OPENAT2_MAX_ATTEMPTS) {
        PyErr_SetString(PyExc_ValueError, "openat2 errno script is too long");
        return NULL;
    }
    for (index = 0; index < count; index += 1) {
        PyObject *item = PyTuple_GetItem(sequence, index);
        long error_number;

        if (item == NULL || !PyLong_CheckExact(item)) {
            PyErr_SetString(PyExc_TypeError, "openat2 errno script is invalid");
            return NULL;
        }
        error_number = PyLong_AsLong(item);
        if (error_number < 0 || error_number > INT_MAX || PyErr_Occurred()) {
            if (!PyErr_Occurred()) {
                PyErr_SetString(PyExc_ValueError, "openat2 errno script is invalid");
            }
            return NULL;
        }
        h2ometa_test_state.errnos[index] = (int)error_number;
    }
    h2ometa_test_state.errno_count = count;
    h2ometa_test_reset_attempts();
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_set_close_report_errno(
    PyObject *self,
    PyObject *args
) {
    PyObject *value;
    long error_number;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_test_set_close_report_errno", &value)) {
        return NULL;
    }
    if (!PyLong_CheckExact(value)) {
        PyErr_SetString(PyExc_TypeError, "close report errno is invalid");
        return NULL;
    }
    error_number = PyLong_AsLong(value);
    if (error_number < 0 || error_number > INT_MAX || PyErr_Occurred()) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError, "close report errno is invalid");
        }
        return NULL;
    }
    h2ometa_test_state.close_report_errno = (int)error_number;
    Py_RETURN_NONE;
}

static int h2ometa_test_store_errno(
    PyObject *args,
    int *slot,
    const char *label
) {
    PyObject *value;
    long error_number;

    if (!PyArg_ParseTuple(args, "O", &value)) {
        return -1;
    }
    if (!PyLong_CheckExact(value)) {
        PyErr_Format(PyExc_TypeError, "%s errno is invalid", label);
        return -1;
    }
    error_number = PyLong_AsLong(value);
    if (error_number < 0 || error_number > INT_MAX || PyErr_Occurred()) {
        if (!PyErr_Occurred()) {
            PyErr_Format(PyExc_ValueError, "%s errno is invalid", label);
        }
        return -1;
    }
    *slot = (int)error_number;
    return 0;
}

static PyObject *h2ometa_test_set_mkdirat_errno(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (h2ometa_test_store_errno(
            args,
            &h2ometa_test_state.mkdirat_errno,
            "mkdirat"
        ) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_set_fchmod_errno(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (h2ometa_test_store_errno(
            args,
            &h2ometa_test_state.fchmod_errno,
            "fchmod"
        ) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_set_fsync_errno(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (h2ometa_test_store_errno(
            args,
            &h2ometa_test_state.fsync_errno,
            "fsync"
        ) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static int h2ometa_test_reproof_phase(
    PyObject *value,
    H2OMetaReproofPhase *phase_out
) {
    static const char *const phase_names[H2OMETA_REPROOF_PHASE_COUNT] = {
        "mkdir_parent_pre",
        "mkdir_child_baseline",
        "mkdir_parent_post",
        "mkdir_child_post",
        "fsync_pre",
        "fsync_post",
    };
    int phase;

    if (!PyUnicode_CheckExact(value)) {
        PyErr_SetString(PyExc_TypeError, "reproof phase is invalid");
        return -1;
    }
    for (phase = 0; phase < H2OMETA_REPROOF_PHASE_COUNT; phase += 1) {
        if (PyUnicode_CompareWithASCIIString(value, phase_names[phase]) == 0) {
            *phase_out = (H2OMetaReproofPhase)phase;
            return 0;
        }
        if (PyErr_Occurred()) {
            return -1;
        }
    }
    PyErr_SetString(PyExc_ValueError, "reproof phase is invalid");
    return -1;
}

static PyObject *h2ometa_test_set_reproof_errno(
    PyObject *self,
    PyObject *args
) {
    PyObject *phase_object;
    PyObject *errno_object;
    H2OMetaReproofPhase phase;
    long error_number;

    (void)self;
    if (!PyArg_ParseTuple(
            args,
            "OO:_test_set_reproof_errno",
            &phase_object,
            &errno_object
        )) {
        return NULL;
    }
    if (h2ometa_test_reproof_phase(phase_object, &phase) < 0) {
        return NULL;
    }
    if (!PyLong_CheckExact(errno_object)) {
        PyErr_SetString(PyExc_TypeError, "reproof errno is invalid");
        return NULL;
    }
    error_number = PyLong_AsLong(errno_object);
    if (error_number < 0 || error_number > INT_MAX || PyErr_Occurred()) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError, "reproof errno is invalid");
        }
        return NULL;
    }
    h2ometa_test_state.reproof_errnos[phase] = (int)error_number;
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_fail_next_capsule_creation(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_fail_next_capsule_creation")) {
        return NULL;
    }
    h2ometa_test_state.fail_next_capsule_creation = 1;
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_arm_sigint_for_next_eintr(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_arm_sigint_for_next_eintr")) {
        return NULL;
    }
    h2ometa_test_state.arm_sigint_for_next_eintr = 1;
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_note_signal_handler_dispatch(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_note_signal_handler_dispatch")) {
        return NULL;
    }
    if (h2ometa_test_state.inside_errno_conversion) {
        h2ometa_test_state.handler_dispatch_inside += 1;
    } else {
        h2ometa_test_state.handler_dispatch_outside += 1;
    }
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_lifecycle_snapshot(
    PyObject *self,
    PyObject *args
) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_lifecycle_snapshot")) {
        return NULL;
    }
    return Py_BuildValue(
        "(iiiiiiiiiiiiiiii)",
        h2ometa_test_state.owner_allocations,
        h2ometa_test_state.capsule_creation_successes,
        h2ometa_test_state.pretransfer_owner_frees,
        h2ometa_test_state.destructor_calls,
        h2ometa_test_state.destructor_owner_frees,
        h2ometa_test_state.fd_adoptions,
        h2ometa_test_state.fd_consumptions,
        h2ometa_test_state.namespace_mutations,
        h2ometa_test_state.eintr_conversions,
        h2ometa_test_state.sigint_raise_calls,
        h2ometa_test_state.handler_dispatch_inside,
        h2ometa_test_state.handler_dispatch_outside,
        h2ometa_test_state.inside_errno_conversion,
        h2ometa_test_state.boundary_owner_state,
        h2ometa_test_state.boundary_namespace_state,
        h2ometa_test_state.last_errno
    );
}

static PyObject *h2ometa_test_leaf_snapshot(PyObject *self, PyObject *args) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_leaf_snapshot")) {
        return NULL;
    }
    return Py_BuildValue(
        "((iKKy#K)(iKKK)(iKK)(iiiiii))",
        h2ometa_test_state.mkdirat_calls,
        (unsigned long long)h2ometa_test_state.mkdir_parent_device,
        (unsigned long long)h2ometa_test_state.mkdir_parent_inode,
        h2ometa_test_state.mkdir_component,
        h2ometa_test_state.mkdir_component_length,
        (unsigned long long)h2ometa_test_state.mkdir_mode,
        h2ometa_test_state.fchmod_calls,
        (unsigned long long)h2ometa_test_state.fchmod_device,
        (unsigned long long)h2ometa_test_state.fchmod_inode,
        (unsigned long long)h2ometa_test_state.fchmod_mode,
        h2ometa_test_state.fsync_calls,
        (unsigned long long)h2ometa_test_state.fsync_device,
        (unsigned long long)h2ometa_test_state.fsync_inode,
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_MKDIR_PARENT_PRE],
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_MKDIR_CHILD_BASELINE],
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_MKDIR_PARENT_POST],
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_MKDIR_CHILD_POST],
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_FSYNC_PRE],
        h2ometa_test_state.reproof_calls[H2OMETA_REPROOF_FSYNC_POST]
    );
}

static PyObject *h2ometa_test_raise_sigint_after_adopt(
    PyObject *self,
    PyObject *args
) {
    int enabled;

    (void)self;
    if (!PyArg_ParseTuple(args, "p:_test_raise_sigint_after_adopt", &enabled)) {
        return NULL;
    }
    h2ometa_test_state.raise_sigint_after_adopt = enabled;
    Py_RETURN_NONE;
}

static PyObject *h2ometa_test_snapshot(PyObject *self, PyObject *args) {
    PyObject *capsule;
    H2OMetaDirOwner *owner;
    int live;
    int cloexec = 0;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_test_snapshot", &capsule)) {
        return NULL;
    }
    owner = h2ometa_owner_from_capsule(capsule);
    if (owner == NULL) {
        return NULL;
    }
    live = owner->fd >= 0;
    if (live) {
        int descriptor_flags = fcntl(owner->fd, F_GETFD);
        if (descriptor_flags < 0) {
            h2ometa_set_errno_error(errno);
            return NULL;
        }
        cloexec = (descriptor_flags & FD_CLOEXEC) != 0;
    }
    return Py_BuildValue(
        "(iKKKi)",
        live,
        (unsigned long long)owner->device,
        (unsigned long long)owner->inode,
        (unsigned long long)owner->uid,
        cloexec
    );
}

static PyObject *h2ometa_test_attempt_snapshot(PyObject *self, PyObject *args) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_attempt_snapshot")) {
        return NULL;
    }
    return Py_BuildValue(
        "(iKKy#KKKKiii)",
        h2ometa_test_state.attempt_count,
        (unsigned long long)h2ometa_test_state.parent_device,
        (unsigned long long)h2ometa_test_state.parent_inode,
        h2ometa_test_state.component,
        h2ometa_test_state.component_length,
        (unsigned long long)h2ometa_test_state.flags,
        (unsigned long long)h2ometa_test_state.mode,
        (unsigned long long)h2ometa_test_state.resolve,
        (unsigned long long)h2ometa_test_state.how_size,
        h2ometa_test_state.shape_mismatch,
        h2ometa_test_state.close_calls,
        h2ometa_test_state.parent_fd
    );
}

static PyObject *h2ometa_test_reset(PyObject *self, PyObject *args) {
    (void)self;
    if (!PyArg_ParseTuple(args, ":_test_reset")) {
        return NULL;
    }
    memset(&h2ometa_test_state, 0, sizeof(h2ometa_test_state));
    Py_RETURN_NONE;
}
#endif

static PyMethodDef h2ometa_methods[] = {
    {
        "_open_child",
        h2ometa_open_child,
        METH_VARARGS,
        "Open one release-tree child from a live directory capability.",
    },
    {
        "_mkdir_child",
        h2ometa_mkdir_child,
        METH_VARARGS,
        "Create and adopt one private release-tree child directory.",
    },
    {
        "_fsync_directory",
        h2ometa_fsync_directory,
        METH_VARARGS,
        "Synchronize one live directory capability and reprove it.",
    },
    {
        "_require_live",
        h2ometa_require_live,
        METH_VARARGS,
        "Reprove a live directory capability without exposing its descriptor.",
    },
    {
        "_close",
        h2ometa_close_owner,
        METH_VARARGS,
        "Idempotently consume a directory capability.",
    },
#ifdef H2OMETA_NATIVE_TESTING
    {
        "_test_duplicate_directory",
        h2ometa_test_duplicate_directory,
        METH_VARARGS,
        "Proof-only directory capability seed.",
    },
    {
        "_test_set_openat2_errnos",
        h2ometa_test_set_openat2_errnos,
        METH_VARARGS,
        "Proof-only openat2 errno script.",
    },
    {
        "_test_set_close_report_errno",
        h2ometa_test_set_close_report_errno,
        METH_VARARGS,
        "Proof-only close error report injection.",
    },
    {
        "_test_set_mkdirat_errno",
        h2ometa_test_set_mkdirat_errno,
        METH_VARARGS,
        "Proof-only mkdirat error injection.",
    },
    {
        "_test_set_fchmod_errno",
        h2ometa_test_set_fchmod_errno,
        METH_VARARGS,
        "Proof-only fchmod error injection.",
    },
    {
        "_test_set_fsync_errno",
        h2ometa_test_set_fsync_errno,
        METH_VARARGS,
        "Proof-only fsync error injection.",
    },
    {
        "_test_set_reproof_errno",
        h2ometa_test_set_reproof_errno,
        METH_VARARGS,
        "Proof-only phase-specific reproof error injection.",
    },
    {
        "_test_fail_next_capsule_creation",
        h2ometa_test_fail_next_capsule_creation,
        METH_VARARGS,
        "Proof-only pre-transfer capsule creation failure.",
    },
    {
        "_test_arm_sigint_for_next_eintr",
        h2ometa_test_arm_sigint_for_next_eintr,
        METH_VARARGS,
        "Proof-only in-method EINTR signal dispatch arm.",
    },
    {
        "_test_note_signal_handler_dispatch",
        h2ometa_test_note_signal_handler_dispatch,
        METH_VARARGS,
        "Proof-only signal handler dispatch observation.",
    },
    {
        "_test_raise_sigint_after_adopt",
        h2ometa_test_raise_sigint_after_adopt,
        METH_VARARGS,
        "Proof-only pending SIGINT injection.",
    },
    {
        "_test_snapshot",
        h2ometa_test_snapshot,
        METH_VARARGS,
        "Proof-only redacted owner snapshot.",
    },
    {
        "_test_attempt_snapshot",
        h2ometa_test_attempt_snapshot,
        METH_VARARGS,
        "Proof-only syscall attempt snapshot.",
    },
    {
        "_test_lifecycle_snapshot",
        h2ometa_test_lifecycle_snapshot,
        METH_VARARGS,
        "Proof-only redacted lifecycle snapshot.",
    },
    {
        "_test_leaf_snapshot",
        h2ometa_test_leaf_snapshot,
        METH_VARARGS,
        "Proof-only redacted directory leaf snapshot.",
    },
    {
        "_test_reset",
        h2ometa_test_reset,
        METH_VARARGS,
        "Reset proof-only process state.",
    },
#endif
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef h2ometa_module = {
    PyModuleDef_HEAD_INIT,
    H2OMETA_MODULE_NAME,
    "Private native owner for H2OMeta release-tree directory capabilities.",
    -1,
    h2ometa_methods,
    NULL,
    NULL,
    NULL,
    NULL,
};

PyMODINIT_FUNC H2OMETA_MODULE_INIT(void) {
    return PyModule_Create(&h2ometa_module);
}
