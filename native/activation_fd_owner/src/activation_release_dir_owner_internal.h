#ifndef H2OMETA_ACTIVATION_RELEASE_DIR_OWNER_INTERNAL_H
#define H2OMETA_ACTIVATION_RELEASE_DIR_OWNER_INTERNAL_H

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
#define H2OMETA_PRIVATE_DIRECTORY_MODE ((mode_t)0700)

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

typedef enum {
    H2OMETA_REPROOF_MKDIR_PARENT_PRE = 0,
    H2OMETA_REPROOF_MKDIR_CHILD_BASELINE = 1,
    H2OMETA_REPROOF_MKDIR_PARENT_POST = 2,
    H2OMETA_REPROOF_MKDIR_CHILD_POST = 3,
    H2OMETA_REPROOF_FSYNC_PRE = 4,
    H2OMETA_REPROOF_FSYNC_POST = 5,
    H2OMETA_REPROOF_PHASE_COUNT = 6,
} H2OMetaReproofPhase;

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
    int fail_next_capsule_creation;
    int owner_allocations;
    int capsule_creation_successes;
    int pretransfer_owner_frees;
    int destructor_calls;
    int destructor_owner_frees;
    int fd_adoptions;
    int fd_consumptions;
    int namespace_mutations;
    int mkdirat_errno;
    int fchmod_errno;
    int fsync_errno;
    int mkdirat_calls;
    dev_t mkdir_parent_device;
    ino_t mkdir_parent_inode;
    char mkdir_component[H2OMETA_MAX_COMPONENT_BYTES + 1];
    Py_ssize_t mkdir_component_length;
    uint64_t mkdir_mode;
    int fchmod_calls;
    dev_t fchmod_device;
    ino_t fchmod_inode;
    uint64_t fchmod_mode;
    int fsync_calls;
    dev_t fsync_device;
    ino_t fsync_inode;
    int reproof_errnos[H2OMETA_REPROOF_PHASE_COUNT];
    int reproof_calls[H2OMETA_REPROOF_PHASE_COUNT];
    int arm_sigint_for_next_eintr;
    int inside_errno_conversion;
    int eintr_conversions;
    int sigint_raise_calls;
    int handler_dispatch_inside;
    int handler_dispatch_outside;
    int boundary_owner_state;
    int boundary_namespace_state;
    int last_errno;
} H2OMetaNativeTestState;

extern H2OMetaNativeTestState h2ometa_test_state;
#endif

int h2ometa_set_errno_error(int error_number);
PyObject *h2ometa_new_owner_capsule(H2OMetaDirOwner **owner_out);
H2OMetaDirOwner *h2ometa_owner_from_capsule(PyObject *capsule);
int h2ometa_consume_owner_fd(H2OMetaDirOwner *owner, int report_error);
int h2ometa_finish_adoption(
    H2OMetaDirOwner *owner,
    uid_t authority_uid
);
int h2ometa_finish_adoption_error(
    H2OMetaDirOwner *owner,
    uid_t authority_uid
);
int h2ometa_require_live_owner(H2OMetaDirOwner *owner);
int h2ometa_live_owner_status_error(
    const H2OMetaDirOwner *owner,
    struct stat *status_out
);
int h2ometa_require_component(
    PyObject *value,
    const char **component_out,
    Py_ssize_t *length_out
);
#ifdef H2OMETA_NATIVE_TESTING
void h2ometa_test_reset_attempts(void);
#endif
long h2ometa_openat2_once(
    const H2OMetaDirOwner *parent,
    const char *component,
    Py_ssize_t component_length,
    const struct open_how *how
);
PyObject *h2ometa_mkdir_child(PyObject *self, PyObject *args);
PyObject *h2ometa_fsync_directory(PyObject *self, PyObject *args);

#endif
