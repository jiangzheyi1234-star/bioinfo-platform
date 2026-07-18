#define _GNU_SOURCE
#define PY_SSIZE_T_CLEAN
#define Py_LIMITED_API 0x030C0000

#include <Python.h>

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/openat2.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#if !defined(__linux__) || !defined(__x86_64__)
#error "activation release directory owner supports Linux x86_64 only"
#endif

#if !defined(SYS_openat2)
#error "SYS_openat2 is unavailable"
#endif

_Static_assert(SYS_openat2 == 437, "unexpected Linux x86_64 openat2 syscall");
_Static_assert(sizeof(struct open_how) == 24, "unexpected open_how ABI");
_Static_assert(O_RDONLY == 0, "unexpected O_RDONLY ABI");
_Static_assert(O_DIRECTORY == 00200000, "unexpected O_DIRECTORY ABI");
_Static_assert(O_NOFOLLOW == 00400000, "unexpected O_NOFOLLOW ABI");
_Static_assert(O_CLOEXEC == 02000000, "unexpected O_CLOEXEC ABI");
_Static_assert(RESOLVE_NO_XDEV == 0x01, "unexpected RESOLVE_NO_XDEV ABI");
_Static_assert(
    RESOLVE_NO_MAGICLINKS == 0x02,
    "unexpected RESOLVE_NO_MAGICLINKS ABI"
);
_Static_assert(RESOLVE_NO_SYMLINKS == 0x04, "unexpected RESOLVE_NO_SYMLINKS ABI");
_Static_assert(RESOLVE_BENEATH == 0x08, "unexpected RESOLVE_BENEATH ABI");

#ifdef H2OMETA_NATIVE_TESTING
#define H2OMETA_CAPSULE_NAME \
    "h2ometa.remote_runner.activation-release-dir-owner-proof.v1"
#define H2OMETA_MODULE_NAME \
    "remote_runner._activation_release_dir_owner_proof"
#define H2OMETA_MODULE_INIT PyInit__activation_release_dir_owner_proof
#else
#define H2OMETA_CAPSULE_NAME \
    "h2ometa.remote_runner.activation-release-dir-owner.v1"
#define H2OMETA_MODULE_NAME "remote_runner._activation_release_dir_owner"
#define H2OMETA_MODULE_INIT PyInit__activation_release_dir_owner
#endif
#define H2OMETA_OWNER_MAGIC UINT64_C(0x48324f4d45544131)
#define H2OMETA_MAX_COMPONENT_BYTES 255
#define H2OMETA_OPENAT2_MAX_ATTEMPTS 3

#define H2OMETA_OPEN_FLAGS \
    ((uint64_t)(O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC))
#define H2OMETA_RESOLVE_FLAGS                                        \
    ((uint64_t)(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS |             \
                RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV))

typedef struct {
    uint64_t magic;
    int fd;
    dev_t device;
    ino_t inode;
    uid_t uid;
} H2OMetaDirOwner;

#ifdef H2OMETA_NATIVE_TESTING
typedef struct {
    int errnos[H2OMETA_OPENAT2_MAX_ATTEMPTS];
    Py_ssize_t errno_count;
    Py_ssize_t errno_index;
    int attempt_count;
    int shape_mismatch;
    dev_t parent_device;
    ino_t parent_inode;
    int parent_fd;
    char component[H2OMETA_MAX_COMPONENT_BYTES + 1];
    Py_ssize_t component_length;
    uint64_t flags;
    uint64_t mode;
    uint64_t resolve;
    size_t how_size;
    int close_calls;
    int close_report_errno;
    int raise_sigint_after_adopt;
} H2OMetaNativeTestState;

static H2OMetaNativeTestState h2ometa_test_state;
#endif

static int h2ometa_set_errno_error(int error_number) {
    errno = error_number;
    PyErr_SetFromErrno(PyExc_OSError);
    return -1;
}

static void h2ometa_capsule_destructor(PyObject *capsule);

static PyObject *h2ometa_new_owner_capsule(H2OMetaDirOwner **owner_out) {
    H2OMetaDirOwner *owner = PyMem_Malloc(sizeof(*owner));
    PyObject *capsule;

    if (owner == NULL) {
        return PyErr_NoMemory();
    }
    memset(owner, 0, sizeof(*owner));
    owner->magic = H2OMETA_OWNER_MAGIC;
    owner->fd = -1;
    capsule = PyCapsule_New(owner, H2OMETA_CAPSULE_NAME, h2ometa_capsule_destructor);
    if (capsule == NULL) {
        owner->magic = 0;
        PyMem_Free(owner);
        return NULL;
    }
    *owner_out = owner;
    return capsule;
}

static H2OMetaDirOwner *h2ometa_owner_from_capsule(PyObject *capsule) {
    H2OMetaDirOwner *owner;

    if (!PyCapsule_IsValid(capsule, H2OMETA_CAPSULE_NAME)) {
        PyErr_SetString(PyExc_TypeError, "invalid directory capability");
        return NULL;
    }
    owner = PyCapsule_GetPointer(capsule, H2OMETA_CAPSULE_NAME);
    if (owner == NULL) {
        return NULL;
    }
    if (owner->magic != H2OMETA_OWNER_MAGIC) {
        PyErr_SetString(PyExc_TypeError, "invalid directory capability");
        return NULL;
    }
    return owner;
}

static int h2ometa_close_once(int fd) {
    int result = close(fd);
    int saved_errno = errno;

#ifdef H2OMETA_NATIVE_TESTING
    h2ometa_test_state.close_calls += 1;
    if (h2ometa_test_state.close_report_errno != 0) {
        saved_errno = h2ometa_test_state.close_report_errno;
        h2ometa_test_state.close_report_errno = 0;
        result = -1;
    }
#endif
    if (result < 0) {
        errno = saved_errno;
    }
    return result;
}

static int h2ometa_consume_owner_fd(H2OMetaDirOwner *owner, int report_error) {
    int fd = owner->fd;
    int result;
    int saved_errno;

    owner->fd = -1;
    if (fd < 0) {
        return 0;
    }
    result = h2ometa_close_once(fd);
    saved_errno = errno;
    if (result < 0 && report_error) {
        return h2ometa_set_errno_error(saved_errno);
    }
    return 0;
}

static void h2ometa_capsule_destructor(PyObject *capsule) {
    H2OMetaDirOwner *owner;

    if (!PyCapsule_IsValid(capsule, H2OMETA_CAPSULE_NAME)) {
        return;
    }
    owner = PyCapsule_GetPointer(capsule, H2OMETA_CAPSULE_NAME);
    if (owner == NULL) {
        PyErr_Clear();
        return;
    }
    if (owner->magic == H2OMETA_OWNER_MAGIC) {
        (void)h2ometa_consume_owner_fd(owner, 0);
        owner->magic = 0;
        PyMem_Free(owner);
    }
}

static int h2ometa_require_directory_policy(const struct stat *status) {
    if (!S_ISDIR(status->st_mode)) {
        return h2ometa_set_errno_error(ENOTDIR);
    }
    if ((status->st_mode & (S_IWGRP | S_IWOTH)) != 0) {
        return h2ometa_set_errno_error(EPERM);
    }
    return 0;
}

static int h2ometa_finish_adoption(
    H2OMetaDirOwner *owner,
    uid_t authority_uid
) {
    struct stat status;
    int descriptor_flags = fcntl(owner->fd, F_GETFD);

    if (descriptor_flags < 0) {
        return h2ometa_set_errno_error(errno);
    }
    if ((descriptor_flags & FD_CLOEXEC) == 0) {
        return h2ometa_set_errno_error(EIO);
    }
    if (fstat(owner->fd, &status) < 0) {
        return h2ometa_set_errno_error(errno);
    }
    if (h2ometa_require_directory_policy(&status) < 0) {
        return -1;
    }
    if (status.st_uid != authority_uid) {
        return h2ometa_set_errno_error(EPERM);
    }
    owner->device = status.st_dev;
    owner->inode = status.st_ino;
    owner->uid = status.st_uid;
    return 0;
}

static int h2ometa_require_live_owner(H2OMetaDirOwner *owner) {
    struct stat status;
    int descriptor_flags;

    if (owner->fd < 0) {
        return h2ometa_set_errno_error(EBADF);
    }
    descriptor_flags = fcntl(owner->fd, F_GETFD);
    if (descriptor_flags < 0) {
        return h2ometa_set_errno_error(errno);
    }
    if ((descriptor_flags & FD_CLOEXEC) == 0) {
        return h2ometa_set_errno_error(EIO);
    }
    if (fstat(owner->fd, &status) < 0) {
        return h2ometa_set_errno_error(errno);
    }
    if (h2ometa_require_directory_policy(&status) < 0) {
        return -1;
    }
    if (status.st_dev != owner->device || status.st_ino != owner->inode) {
        return h2ometa_set_errno_error(ESTALE);
    }
    if (status.st_uid != owner->uid) {
        return h2ometa_set_errno_error(EPERM);
    }
    return 0;
}

static int h2ometa_require_component(
    PyObject *value,
    const char **component_out,
    Py_ssize_t *length_out
) {
    const char *component;
    Py_ssize_t length;
    Py_ssize_t index;
    static const char reserved_prefix[] = ".h2ometa-";

    if (!PyUnicode_CheckExact(value)) {
        PyErr_SetString(PyExc_ValueError, "invalid release-tree component");
        return -1;
    }
    component = PyUnicode_AsUTF8AndSize(value, &length);
    if (component == NULL) {
        return -1;
    }
    if (length < 1 || length > H2OMETA_MAX_COMPONENT_BYTES ||
        component[0] == ' ' || component[length - 1] == ' ' ||
        (length == 1 && component[0] == '.') ||
        (length == 2 && component[0] == '.' && component[1] == '.') ||
        (length >= (Py_ssize_t)(sizeof(reserved_prefix) - 1) &&
         memcmp(component, reserved_prefix, sizeof(reserved_prefix) - 1) == 0)) {
        PyErr_SetString(PyExc_ValueError, "invalid release-tree component");
        return -1;
    }
    for (index = 0; index < length; index += 1) {
        unsigned char byte = (unsigned char)component[index];
        if (byte < 0x20 || byte > 0x7e || byte == '/' || byte == '\\') {
            PyErr_SetString(PyExc_ValueError, "invalid release-tree component");
            return -1;
        }
    }
    *component_out = component;
    *length_out = length;
    return 0;
}

#ifdef H2OMETA_NATIVE_TESTING
static void h2ometa_test_reset_attempts(void) {
    h2ometa_test_state.errno_index = 0;
    h2ometa_test_state.attempt_count = 0;
    h2ometa_test_state.shape_mismatch = 0;
    h2ometa_test_state.parent_device = 0;
    h2ometa_test_state.parent_inode = 0;
    h2ometa_test_state.parent_fd = -1;
    h2ometa_test_state.component[0] = '\0';
    h2ometa_test_state.component_length = 0;
    h2ometa_test_state.flags = 0;
    h2ometa_test_state.mode = 0;
    h2ometa_test_state.resolve = 0;
    h2ometa_test_state.how_size = 0;
}

static void h2ometa_test_record_attempt(
    const H2OMetaDirOwner *parent,
    const char *component,
    Py_ssize_t component_length,
    const struct open_how *how
) {
    int same_shape =
        h2ometa_test_state.parent_device == parent->device &&
        h2ometa_test_state.parent_inode == parent->inode &&
        h2ometa_test_state.parent_fd == parent->fd &&
        h2ometa_test_state.component_length == component_length &&
        memcmp(
            h2ometa_test_state.component,
            component,
            (size_t)component_length
        ) == 0 &&
        h2ometa_test_state.flags == how->flags &&
        h2ometa_test_state.mode == how->mode &&
        h2ometa_test_state.resolve == how->resolve &&
        h2ometa_test_state.how_size == sizeof(*how);

    if (h2ometa_test_state.attempt_count == 0) {
        h2ometa_test_state.parent_device = parent->device;
        h2ometa_test_state.parent_inode = parent->inode;
        h2ometa_test_state.parent_fd = parent->fd;
        memcpy(
            h2ometa_test_state.component,
            component,
            (size_t)component_length
        );
        h2ometa_test_state.component[component_length] = '\0';
        h2ometa_test_state.component_length = component_length;
        h2ometa_test_state.flags = how->flags;
        h2ometa_test_state.mode = how->mode;
        h2ometa_test_state.resolve = how->resolve;
        h2ometa_test_state.how_size = sizeof(*how);
    } else if (!same_shape) {
        h2ometa_test_state.shape_mismatch = 1;
    }
    h2ometa_test_state.attempt_count += 1;
}

static int h2ometa_test_injected_errno(void) {
    int error_number;

    if (h2ometa_test_state.errno_index >= h2ometa_test_state.errno_count) {
        return 0;
    }
    error_number = h2ometa_test_state.errnos[h2ometa_test_state.errno_index];
    h2ometa_test_state.errno_index += 1;
    return error_number;
}
#endif

static long h2ometa_openat2_once(
    const H2OMetaDirOwner *parent,
    const char *component,
    Py_ssize_t component_length,
    const struct open_how *how
) {
#ifdef H2OMETA_NATIVE_TESTING
    int injected_errno;

    h2ometa_test_record_attempt(parent, component, component_length, how);
    injected_errno = h2ometa_test_injected_errno();
    if (injected_errno != 0) {
        errno = injected_errno;
        return -1;
    }
#else
    (void)component_length;
#endif
    return syscall(SYS_openat2, parent->fd, component, how, sizeof(*how));
}

static PyObject *h2ometa_open_child(PyObject *self, PyObject *args) {
    PyObject *parent_capsule;
    PyObject *component_object;
    PyObject *child_capsule;
    H2OMetaDirOwner *parent;
    H2OMetaDirOwner *child;
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
    H2OMetaDirOwner *owner;
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
