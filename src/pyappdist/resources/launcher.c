/* pyappdist launcher (subprocess approach)
 *
 * A thin stub that merely launches python.exe / pythonw.exe inside the image
 * via CreateProcess. Isolation is twofold: python's -I (=-E -s) plus an
 * environment block with PYTHON* removed. App-specific values are embedded at
 * build time via a generated header.
 *
 * Lifetime: the child is placed in a Job Object with KILL_ON_JOB_CLOSE, so if
 * this launcher is terminated (e.g. killed by a parent or task manager) the
 * python child -- and its whole descendant tree -- is torn down instead of
 * being orphaned. Job setup is best-effort: any failure falls back to launching
 * the child unmanaged rather than failing the launch.
 *
 * Ctrl+C / Ctrl+Break: the console delivers these to every process attached to
 * it, so the python child receives them directly. The launcher ignores them
 * and keeps waiting -- like CPython's py.exe launcher -- so python alone
 * decides how to shut down and the child's real exit code is propagated.
 */

#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "pyappdist_launcher_config.h"

#ifndef PYAPPDIST_PYEXE
#define PYAPPDIST_PYEXE L"python\\python.exe"
#endif
#ifndef PYAPPDIST_BOOTSTRAP
#define PYAPPDIST_BOOTSTRAP L""
#endif
#ifndef PYAPPDIST_FIXED_ARGS
#define PYAPPDIST_FIXED_ARGS L""
#endif

#define CMD_MAX 32768

/* Ceiling on a \\?\ path, and so on any path we build. */
#define PATH_MAX_EXTENDED 32767

/* Build an environment block with PYTHON* removed (for CREATE_UNICODE_ENVIRONMENT). */
static LPWSTR build_clean_env(void) {
    LPWCH all = GetEnvironmentStringsW();
    if (!all) return NULL;
    size_t total = 0;
    for (LPWCH p = all; *p; ) {
        size_t len = wcslen(p);
        if (_wcsnicmp(p, L"PYTHON", 6) != 0)
            total += len + 1;
        p += len + 1;
    }
    total += 1;
    LPWSTR out = (LPWSTR)malloc(total * sizeof(WCHAR));
    if (!out) { FreeEnvironmentStringsW(all); return NULL; }
    LPWSTR w = out;
    for (LPWCH p = all; *p; ) {
        size_t len = wcslen(p);
        if (_wcsnicmp(p, L"PYTHON", 6) != 0) {
            memcpy(w, p, (len + 1) * sizeof(WCHAR));
            w += len + 1;
        }
        p += len + 1;
    }
    *w = L'\0';
    FreeEnvironmentStringsW(all);
    return out;
}

/* Set when the command line would exceed CMD_MAX; checked before launching so
   arguments are never silently dropped. */
static int cmd_overflow = 0;

static void append(WCHAR *buf, size_t *pos, const WCHAR *s) {
    size_t len = wcslen(s);
    if (*pos + len + 1 >= CMD_MAX) { cmd_overflow = 1; return; }
    memcpy(buf + *pos, s, len * sizeof(WCHAR));
    *pos += len;
    buf[*pos] = L'\0';
}

static void append_ch(WCHAR *buf, size_t *pos, WCHAR c) {
    if (*pos + 2 >= CMD_MAX) { cmd_overflow = 1; return; }
    buf[(*pos)++] = c;
    buf[*pos] = L'\0';
}

/* Append one argument following MSVC quoting rules. */
static void append_quoted(WCHAR *buf, size_t *pos, const WCHAR *arg) {
    int need = (arg[0] == L'\0');
    for (const WCHAR *p = arg; *p; ++p)
        if (*p == L' ' || *p == L'\t' || *p == L'"') { need = 1; break; }
    if (!need) { append(buf, pos, arg); return; }
    append_ch(buf, pos, L'"');
    for (const WCHAR *p = arg; ; ++p) {
        int nbs = 0;
        while (*p == L'\\') { ++nbs; ++p; }
        if (*p == L'\0') {
            for (int i = 0; i < nbs * 2; ++i) append_ch(buf, pos, L'\\');
            break;
        } else if (*p == L'"') {
            for (int i = 0; i < nbs * 2 + 1; ++i) append_ch(buf, pos, L'\\');
            append_ch(buf, pos, L'"');
        } else {
            for (int i = 0; i < nbs; ++i) append_ch(buf, pos, L'\\');
            append_ch(buf, pos, *p);
        }
    }
    append_ch(buf, pos, L'"');
}

/* The console delivers Ctrl+C / Ctrl+Break to the python child too; python
   alone decides how to shut down. Returning TRUE stops the default handler
   from exiting the launcher, which would close the kill-on-close job and
   terminate the child mid-cleanup. Other events (e.g. CTRL_CLOSE_EVENT when
   the console window is closed) fall through to the default handler, whose
   exit tears the child down via the job -- the desired behavior there. */
static BOOL WINAPI ctrl_handler(DWORD type) {
    return type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT;
}

/* Directory this executable lives in, as a heap string the caller frees.
   The buffer grows until the path fits: MAX_PATH is only the *traditional*
   limit, and the image format's .zip can be extracted anywhere, including
   below a deeper tree than that. NULL on failure. */
static WCHAR *module_dir(void) {
    DWORD size = MAX_PATH;
    for (;;) {
        WCHAR *buf = (WCHAR *)malloc(size * sizeof(WCHAR));
        if (!buf) return NULL;
        DWORD n = GetModuleFileNameW(NULL, buf, size);
        /* Truncation is reported by filling the buffer exactly (and, since
           Windows XP, by ERROR_INSUFFICIENT_BUFFER); anything shorter fit. */
        if (n != 0 && n < size) {
            for (DWORD i = n; i > 0; --i) {
                if (buf[i - 1] == L'\\' || buf[i - 1] == L'/') { buf[i - 1] = L'\0'; break; }
            }
            return buf;
        }
        free(buf);
        if (n == 0 || size >= PATH_MAX_EXTENDED) return NULL;
        size *= 2;
    }
}

/* "<dir>\<PYAPPDIST_PYEXE>", as a heap string the caller frees.

   Beyond MAX_PATH the result is returned in extended-length form: CreateProcessW
   applies the traditional limit to its application name, so a deep install would
   otherwise fail to start with no way to say why. \\?\ needs a fully-qualified
   path, which GetModuleFileNameW always returns; a UNC path takes the \\?\UNC\
   spelling instead. NULL if the path cannot be represented at all. */
static WCHAR *interpreter_path(const WCHAR *dir) {
    const WCHAR *prefix = L"";
    const WCHAR *body = dir;
    size_t len = wcslen(dir) + 1 + wcslen(PYAPPDIST_PYEXE);  /* + separator */

    if (len >= MAX_PATH && wcsncmp(dir, L"\\\\?\\", 4) != 0) {
        if (dir[0] == L'\\' && dir[1] == L'\\') {
            prefix = L"\\\\?\\UNC";  /* \\server\share -> \\?\UNC\server\share */
            body = dir + 1;
            len -= 1;
        } else {
            prefix = L"\\\\?\\";
        }
        len += wcslen(prefix);
    }
    if (len >= PATH_MAX_EXTENDED) return NULL;

    size_t size = len + 1;
    WCHAR *out = (WCHAR *)malloc(size * sizeof(WCHAR));
    if (!out) return NULL;
    /* _snwprintf_s with _TRUNCATE guarantees null-termination on truncation
       (plain _snwprintf does not, hence the C4996 deprecation warning). */
    _snwprintf_s(out, size, _TRUNCATE, L"%ls%ls\\%ls", prefix, body, PYAPPDIST_PYEXE);
    return out;
}

static int run(void) {
    WCHAR *self = module_dir();
    if (!self) {
        fwprintf(stderr, L"error: cannot determine the launcher's own location\n");
        return 125;
    }

    WCHAR *pyexe = interpreter_path(self);
    free(self);
    if (!pyexe) {
        fwprintf(stderr, L"error: the path to the bundled interpreter is too long\n");
        return 125;
    }

    static WCHAR cmd[CMD_MAX];
    size_t pos = 0;
    cmd[0] = L'\0';
    append_quoted(cmd, &pos, pyexe);
    append(cmd, &pos, L" -I -c ");
    append_quoted(cmd, &pos, PYAPPDIST_BOOTSTRAP);

    const WCHAR *fixed = PYAPPDIST_FIXED_ARGS;
    if (fixed[0]) { append_ch(cmd, &pos, L' '); append(cmd, &pos, fixed); }

    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        for (int i = 1; i < argc; ++i) {
            append_ch(cmd, &pos, L' ');
            append_quoted(cmd, &pos, argv[i]);
        }
        LocalFree(argv);
    }

    if (cmd_overflow) {
        /* Console launchers surface this; gui ones at least exit non-zero. */
        fwprintf(stderr, L"error: command line exceeds the %d-character limit\n",
                 CMD_MAX);
        free(pyexe);
        return 124;
    }

    /* Install before creating the child so there is no window where Ctrl+C
       still kills the launcher (and, via the job, the child). Harmless no-op
       for the GUI launcher, which has no console. */
    SetConsoleCtrlHandler(ctrl_handler, TRUE);

    LPWSTR env = build_clean_env();

    /* Create a kill-on-close Job Object so the child dies with us. Failure here
       is non-fatal: job stays NULL and the child is launched unmanaged. */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION jeli;
        ZeroMemory(&jeli, sizeof(jeli));
        jeli.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                     &jeli, sizeof(jeli))) {
            CloseHandle(job);
            job = NULL;
        }
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    /* Start suspended when using a job so the child can't spawn or escape before
       it is assigned; resume only after AssignProcessToJobObject. */
    DWORD flags = CREATE_UNICODE_ENVIRONMENT;
    if (job) flags |= CREATE_SUSPENDED;

    BOOL ok = CreateProcessW(pyexe, cmd, NULL, NULL, TRUE,
                             flags, env, NULL, &si, &pi);
    if (env) free(env);
    if (!ok) {
        fwprintf(stderr, L"error: cannot start the bundled interpreter (%lu): %ls\n",
                 GetLastError(), pyexe);
        free(pyexe);
        if (job) CloseHandle(job);
        return 126;
    }
    free(pyexe);

    if (job) {
        /* If assignment fails (e.g. nested-job restrictions on old Windows),
           drop the job and let the child run unmanaged rather than killing it. */
        if (!AssignProcessToJobObject(job, pi.hProcess)) {
            CloseHandle(job);
            job = NULL;
        }
        ResumeThread(pi.hThread);
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    /* Safe to close now: on normal exit the child has already terminated, so
       kill-on-close has nothing left to kill. */
    if (job) CloseHandle(job);
    return (int)code;
}

int wmain(void) { return run(); }

int WINAPI wWinMain(HINSTANCE a, HINSTANCE b, LPWSTR c, int d) {
    (void)a; (void)b; (void)c; (void)d;
    return run();
}
