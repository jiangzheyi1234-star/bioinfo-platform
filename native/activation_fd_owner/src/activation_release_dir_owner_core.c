#include "activation_release_dir_owner_internal.h"

#ifdef H2OMETA_NATIVE_TESTING
H2OMetaNativeTestState h2ometa_test_state;
#endif

int h2ometa_set_errno_error(int error_number) {
    errno = error_number;
    PyErr_SetFromErrno(PyExc_OSError);
    return -1;
}

static void h2ometa_capsule_destructor(PyObject *capsule);

PyObject *h2ometa_new_owner_capsule(H2OMetaDirOwner **owner_out) {
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

H2OMetaDirOwner *h2ometa_owner_from_capsule(PyObject *capsule) {
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

int h2ometa_consume_owner_fd(H2OMetaDirOwner *owner, int report_error) {
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

int h2ometa_finish_adoption(
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

int h2ometa_require_live_owner(H2OMetaDirOwner *owner) {
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

int h2ometa_require_component(
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
void h2ometa_test_reset_attempts(void) {
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

long h2ometa_openat2_once(
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
