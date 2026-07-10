/* pyappdist macOS launcher (exec approach)
 *
 * A thin Mach-O stub placed at <bundle>/Contents/MacOS/<name>. It resolves the
 * bundled interpreter at <bundle>/Contents/Resources/python/bin/python3 relative
 * to its own location and execv()s it with `-I -c <bootstrap>`.
 *
 * execv (not posix_spawn): the .app process IS replaced by python, so
 * LaunchServices/Dock/AppKit see a single process whose Mach-O lives under
 * Contents/MacOS, and [NSBundle mainBundle] resolves to this .app. Isolation is
 * twofold: python's -I (=-E -s) plus scrubbing PYTHON* from the environment.
 * App-specific values are embedded at build time via a generated header.
 */

#include <crt_externs.h> /* _NSGetEnviron */
#include <limits.h>
#include <mach-o/dyld.h> /* _NSGetExecutablePath */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "pyappdist_launcher_config.h"

/* Path to the bundled interpreter, relative to Contents/MacOS/<name>. */
#ifndef PYAPPDIST_PYREL
#define PYAPPDIST_PYREL "../Resources/python/bin/python3"
#endif
#ifndef PYAPPDIST_BOOTSTRAP
#define PYAPPDIST_BOOTSTRAP ""
#endif
/* Brace-initializer of fixed args, NULL-terminated (e.g. { "--flag", NULL }). */
#ifndef PYAPPDIST_FIXED_ARGS
#define PYAPPDIST_FIXED_ARGS { NULL }
#endif

static const char *const FIXED[] = PYAPPDIST_FIXED_ARGS;

/* Remove every PYTHON* variable from the environment (belt-and-suspenders to -I).
 * Names are gathered first, then unset, because unsetenv() mutates environ. */
static void scrub_python_env(void) {
    char *names[256];
    int n = 0;
    for (char **e = *_NSGetEnviron(); *e && n < 256; ++e) {
        if (strncmp(*e, "PYTHON", 6) != 0)
            continue;
        const char *eq = strchr(*e, '=');
        size_t len = eq ? (size_t)(eq - *e) : strlen(*e);
        char *nm = (char *)malloc(len + 1);
        if (!nm)
            continue;
        memcpy(nm, *e, len);
        nm[len] = '\0';
        names[n++] = nm;
    }
    for (int i = 0; i < n; ++i) {
        unsetenv(names[i]);
        free(names[i]);
    }
}

int main(int argc, char **argv) {
    /* 1. resolve our own executable path (may contain .. / symlinks). */
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) {
        fprintf(stderr, "pyappdist launcher: executable path too long\n");
        return 125;
    }
    char self[PATH_MAX];
    if (!realpath(exe, self)) {
        fprintf(stderr, "pyappdist launcher: realpath(%s) failed\n", exe);
        return 125;
    }

    /* 2. derive the bundled python path relative to our directory. */
    char *slash = strrchr(self, '/');
    if (slash)
        *slash = '\0';
    char raw[PATH_MAX];
    snprintf(raw, sizeof(raw), "%s/%s", self, PYAPPDIST_PYREL);
    char pyexe[PATH_MAX];
    if (!realpath(raw, pyexe)) {
        /* fall back to the un-normalized path; execv resolves .. via the kernel. */
        snprintf(pyexe, sizeof(pyexe), "%s", raw);
    }

    /* 3. isolate the environment. */
    scrub_python_env();

    /* 4. argv = { python3, -I, -c, BOOTSTRAP, FIXED..., forwarded argv[1..], NULL } */
    int nfixed = 0;
    while (FIXED[nfixed])
        ++nfixed;
    /* argc == 0 is legal on macOS (execve with an empty argv); clamp so the
       NULL terminator below stays within the allocation. */
    int nuser = argc > 1 ? argc - 1 : 0;
    int total = 4 + nfixed + nuser + 1;
    char **args = (char **)malloc((size_t)total * sizeof(char *));
    if (!args) {
        fprintf(stderr, "pyappdist launcher: out of memory\n");
        return 125;
    }
    int k = 0;
    args[k++] = pyexe;
    args[k++] = (char *)"-I";
    args[k++] = (char *)"-c";
    args[k++] = (char *)PYAPPDIST_BOOTSTRAP;
    for (int i = 0; i < nfixed; ++i)
        args[k++] = (char *)FIXED[i];
    for (int i = 1; i < argc; ++i)
        args[k++] = argv[i];
    args[k] = NULL;

    execv(pyexe, args);

    /* execv only returns on failure. */
    perror("pyappdist launcher: execv");
    fprintf(stderr, "pyappdist launcher: failed to launch %s\n", pyexe);
    return 127;
}
