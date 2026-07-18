#include "activation_release_dir_owner_internal.h"

#if !defined(SYS_mkdirat)
#error "SYS_mkdirat is unavailable"
#endif

_Static_assert(SYS_mkdirat == 258, "unexpected Linux x86_64 mkdirat syscall");

static int h2ometa_reproof_injected_error(H2OMetaReproofPhase phase) {
#ifdef H2OMETA_NATIVE_TESTING
    int error_number;

    h2ometa_test_state.reproof_calls[phase] += 1;
    error_number = h2ometa_test_state.reproof_errnos[phase];
    h2ometa_test_state.reproof_errnos[phase] = 0;
    return error_number;
#else
    (void)phase;
    return 0;
#endif
}

static int h2ometa_parent_reproof_error(
    const H2OMetaDirOwner *parent,
    H2OMetaReproofPhase phase
) {
    struct stat status;
    int error_number = h2ometa_reproof_injected_error(phase);

    if (error_number != 0) {
        return error_number;
    }
    return h2ometa_live_owner_status_error(parent, &status);
}

static int h2ometa_child_baseline_error(
    const H2OMetaDirOwner *parent,
    H2OMetaDirOwner *child
) {
    int error_number = h2ometa_reproof_injected_error(
        H2OMETA_REPROOF_MKDIR_CHILD_BASELINE
    );

    if (error_number != 0) {
        return error_number;
    }
    error_number = h2ometa_finish_adoption_error(child, parent->uid);
    if (error_number != 0) {
        return error_number;
    }
    if (child->device != parent->device) {
        return EXDEV;
    }
    return 0;
}

static int h2ometa_child_postproof_error(
    const H2OMetaDirOwner *parent,
    H2OMetaDirOwner *child,
    int baseline_complete
) {
    struct stat status;
    int error_number = h2ometa_reproof_injected_error(
        H2OMETA_REPROOF_MKDIR_CHILD_POST
    );

    if (error_number != 0) {
        return error_number;
    }
    if (!baseline_complete) {
        error_number = h2ometa_finish_adoption_error(child, parent->uid);
        if (error_number != 0) {
            return error_number;
        }
        if (child->device != parent->device) {
            return EXDEV;
        }
    }
    error_number = h2ometa_live_owner_status_error(child, &status);
    if (error_number != 0) {
        return error_number;
    }
    if (status.st_dev != parent->device) {
        return EXDEV;
    }
    if (status.st_uid != parent->uid) {
        return EPERM;
    }
    if ((status.st_mode & 07777) != H2OMETA_PRIVATE_DIRECTORY_MODE) {
        return EPERM;
    }
    return 0;
}

static int h2ometa_mkdir_postproof_error(
    const H2OMetaDirOwner *parent,
    H2OMetaDirOwner *child,
    int baseline_complete
) {
    int parent_error = h2ometa_parent_reproof_error(
        parent,
        H2OMETA_REPROOF_MKDIR_PARENT_POST
    );
    int child_error = 0;

    if (child->fd >= 0) {
        child_error = h2ometa_child_postproof_error(
            parent,
            child,
            baseline_complete
        );
    }
    if (parent_error != 0) {
        return parent_error;
    }
    return child_error;
}

static long h2ometa_mkdirat_once(
    const H2OMetaDirOwner *parent,
    const char *component,
    Py_ssize_t component_length,
    int *syscall_issued_out
) {
    long result;

    *syscall_issued_out = 0;

#ifdef H2OMETA_NATIVE_TESTING
    int injected_errno;

    h2ometa_test_state.mkdirat_calls += 1;
    h2ometa_test_state.mkdir_parent_device = parent->device;
    h2ometa_test_state.mkdir_parent_inode = parent->inode;
    memcpy(
        h2ometa_test_state.mkdir_component,
        component,
        (size_t)component_length
    );
    h2ometa_test_state.mkdir_component[component_length] = '\0';
    h2ometa_test_state.mkdir_component_length = component_length;
    h2ometa_test_state.mkdir_mode = H2OMETA_PRIVATE_DIRECTORY_MODE;
    injected_errno = h2ometa_test_state.mkdirat_errno;
    h2ometa_test_state.mkdirat_errno = 0;
    if (injected_errno != 0) {
        errno = injected_errno;
        return -1;
    }
#else
    (void)component_length;
#endif
    *syscall_issued_out = 1;
    result = syscall(
        SYS_mkdirat,
        parent->fd,
        component,
        H2OMETA_PRIVATE_DIRECTORY_MODE
    );
#ifdef H2OMETA_NATIVE_TESTING
    if (result == 0) {
        h2ometa_test_state.namespace_mutations += 1;
    }
#endif
    return result;
}

static int h2ometa_fchmod_private_once(H2OMetaDirOwner *child) {
    int result;

#ifdef H2OMETA_NATIVE_TESTING
    int injected_errno;

    h2ometa_test_state.fchmod_calls += 1;
    h2ometa_test_state.fchmod_device = child->device;
    h2ometa_test_state.fchmod_inode = child->inode;
    h2ometa_test_state.fchmod_mode = H2OMETA_PRIVATE_DIRECTORY_MODE;
    injected_errno = h2ometa_test_state.fchmod_errno;
    h2ometa_test_state.fchmod_errno = 0;
    if (injected_errno != 0) {
        errno = injected_errno;
        return -1;
    }
#endif
    result = fchmod(child->fd, H2OMETA_PRIVATE_DIRECTORY_MODE);
    return result;
}

static int h2ometa_fsync_once(H2OMetaDirOwner *owner) {
    int result;

#ifdef H2OMETA_NATIVE_TESTING
    int injected_errno;

    h2ometa_test_state.fsync_calls += 1;
    h2ometa_test_state.fsync_device = owner->device;
    h2ometa_test_state.fsync_inode = owner->inode;
    injected_errno = h2ometa_test_state.fsync_errno;
    h2ometa_test_state.fsync_errno = 0;
    if (injected_errno != 0) {
        errno = injected_errno;
        return -1;
    }
#endif
    result = fsync(owner->fd);
    return result;
}

static PyObject *h2ometa_discard_child_with_error(
    PyObject *child_capsule,
    int error_number,
    int namespace_mutated
) {
    Py_DecRef(child_capsule);
#ifdef H2OMETA_NATIVE_TESTING
    h2ometa_test_state.boundary_owner_state = 0;
    h2ometa_test_state.boundary_namespace_state = namespace_mutated;
#else
    (void)namespace_mutated;
#endif
    (void)h2ometa_set_errno_error(error_number);
    return NULL;
}

PyObject *h2ometa_mkdir_child(PyObject *self, PyObject *args) {
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
    long result;
    int attempt;
    int saved_errno;
    int baseline_complete = 0;
    int namespace_mutated = 0;
    int mkdirat_issued = 0;
    int postproof_error;

    (void)self;
    if (!PyArg_ParseTuple(
            args,
            "OO:_mkdir_child",
            &parent_capsule,
            &component_object
        )) {
        return NULL;
    }
    parent = h2ometa_owner_from_capsule(parent_capsule);
    if (parent == NULL) {
        return NULL;
    }
    if (h2ometa_require_component(
            component_object,
            &component,
            &component_length
        ) < 0) {
        return NULL;
    }
    saved_errno = h2ometa_parent_reproof_error(
        parent,
        H2OMETA_REPROOF_MKDIR_PARENT_PRE
    );
    if (saved_errno != 0) {
#ifdef H2OMETA_NATIVE_TESTING
        h2ometa_test_state.boundary_owner_state = parent->fd >= 0;
        h2ometa_test_state.boundary_namespace_state = 0;
#endif
        (void)h2ometa_set_errno_error(saved_errno);
        return NULL;
    }
    child_capsule = h2ometa_new_owner_capsule(&child);
    if (child_capsule == NULL) {
        return NULL;
    }
#ifdef H2OMETA_NATIVE_TESTING
    h2ometa_test_reset_attempts();
#endif
    result = h2ometa_mkdirat_once(
        parent,
        component,
        component_length,
        &mkdirat_issued
    );
    if (result < 0) {
        saved_errno = errno;
        postproof_error = h2ometa_mkdir_postproof_error(parent, child, 0);
        return h2ometa_discard_child_with_error(
            child_capsule,
            postproof_error != 0 ? postproof_error : saved_errno,
            saved_errno == EINTR && mkdirat_issued ? -1 : 0
        );
    }
    namespace_mutated = 1;

    result = -1;
    saved_errno = EIO;
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
            postproof_error = h2ometa_mkdir_postproof_error(parent, child, 0);
            return h2ometa_discard_child_with_error(
                child_capsule,
                postproof_error != 0 ? postproof_error : saved_errno,
                namespace_mutated
            );
        }
    }
    if (child->fd < 0) {
        postproof_error = h2ometa_mkdir_postproof_error(parent, child, 0);
        return h2ometa_discard_child_with_error(
            child_capsule,
            postproof_error != 0 ? postproof_error : EIO,
            namespace_mutated
        );
    }
    saved_errno = h2ometa_child_baseline_error(parent, child);
    if (saved_errno != 0) {
        postproof_error = h2ometa_mkdir_postproof_error(parent, child, 0);
        return h2ometa_discard_child_with_error(
            child_capsule,
            postproof_error != 0 ? postproof_error : saved_errno,
            namespace_mutated
        );
    }
    baseline_complete = 1;
    if (h2ometa_fchmod_private_once(child) < 0) {
        saved_errno = errno;
        postproof_error = h2ometa_mkdir_postproof_error(
            parent,
            child,
            baseline_complete
        );
        return h2ometa_discard_child_with_error(
            child_capsule,
            postproof_error != 0 ? postproof_error : saved_errno,
            namespace_mutated
        );
    }
    postproof_error = h2ometa_mkdir_postproof_error(
        parent,
        child,
        baseline_complete
    );
    if (postproof_error != 0) {
        return h2ometa_discard_child_with_error(
            child_capsule,
            postproof_error,
            namespace_mutated
        );
    }
#ifdef H2OMETA_NATIVE_TESTING
    if (h2ometa_test_state.raise_sigint_after_adopt) {
        (void)raise(SIGINT);
    }
#endif
    return child_capsule;
}

PyObject *h2ometa_fsync_directory(PyObject *self, PyObject *args) {
    PyObject *capsule;
    H2OMetaDirOwner *owner;
    struct stat status;
    int result;
    int saved_errno;
    int postproof_error;

    (void)self;
    if (!PyArg_ParseTuple(args, "O:_fsync_directory", &capsule)) {
        return NULL;
    }
    owner = h2ometa_owner_from_capsule(capsule);
    if (owner == NULL) {
        return NULL;
    }
    saved_errno = h2ometa_reproof_injected_error(H2OMETA_REPROOF_FSYNC_PRE);
    if (saved_errno == 0) {
        saved_errno = h2ometa_live_owner_status_error(owner, &status);
    }
    if (saved_errno != 0) {
#ifdef H2OMETA_NATIVE_TESTING
        h2ometa_test_state.boundary_owner_state = owner->fd >= 0;
        h2ometa_test_state.boundary_namespace_state = 0;
#endif
        (void)h2ometa_set_errno_error(saved_errno);
        return NULL;
    }
    result = h2ometa_fsync_once(owner);
    saved_errno = errno;
    postproof_error = h2ometa_reproof_injected_error(
        H2OMETA_REPROOF_FSYNC_POST
    );
    if (postproof_error == 0) {
        postproof_error = h2ometa_live_owner_status_error(owner, &status);
    }
    if (postproof_error != 0 || result < 0) {
#ifdef H2OMETA_NATIVE_TESTING
        h2ometa_test_state.boundary_owner_state = owner->fd >= 0;
        h2ometa_test_state.boundary_namespace_state = 0;
#endif
        (void)h2ometa_set_errno_error(
            postproof_error != 0 ? postproof_error : saved_errno
        );
        return NULL;
    }
    Py_RETURN_NONE;
}
