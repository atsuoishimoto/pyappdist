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

static int run(void) {
    WCHAR self[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, self, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 125;
    for (DWORD i = n; i > 0; --i) {
        if (self[i - 1] == L'\\' || self[i - 1] == L'/') { self[i - 1] = L'\0'; break; }
    }

    static WCHAR pyexe[MAX_PATH * 2];
    /* _snwprintf_s with _TRUNCATE guarantees null-termination on truncation
       (plain _snwprintf does not, hence the C4996 deprecation warning). */
    _snwprintf_s(pyexe, MAX_PATH * 2, _TRUNCATE, L"%s\\%s", self, PYAPPDIST_PYEXE);

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
    if (!ok) { if (job) CloseHandle(job); return 126; }

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
