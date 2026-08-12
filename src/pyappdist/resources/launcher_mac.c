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
 *
 * App-specific values come from a sidecar JSON at
 * <bundle>/Contents/Resources/<name>.launcher.json — named after this
 * executable, so several launchers can share one bundle (written by the build
 * pipeline next to a prebuilt stub, and sealed by the bundle's code signature);
 * a source-built launcher embeds them via a generated header instead, and the
 * sidecar, when present, wins.
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

/* Sidecar config paths, relative to the directory of this executable. The
   per-executable name is tried first; the fixed legacy name is a fallback for
   bundles assembled by pyappdist versions that wrote only that name. */
#define CONFIG_REL_FMT "../Resources/%s.launcher.json"
#define CONFIG_REL_LEGACY "../Resources/pyappdist-launcher.json"

/* Refuse configs larger than this (a valid one is a few KB at most). */
#define CONFIG_MAX (4 * 1024 * 1024)

static const char *const FIXED[] = PYAPPDIST_FIXED_ARGS;

/* --- minimal JSON reader ---------------------------------------------------
 *
 * Parses exactly the shape the pipeline writes:
 *     { "pyrel": "...", "bootstrap": "...", "args": ["...", ...] }
 * Keys may appear in any order; values must be strings or arrays of strings.
 * String escapes (\" \\ \/ \b \f \n \r \t \uXXXX incl. surrogate pairs) are
 * decoded to UTF-8. Any deviation makes the whole load fail, which falls back
 * to the compiled-in config (or an error for a prebuilt stub).
 */

struct js {
    const char *p;
    const char *end;
};

static void js_ws(struct js *j) {
    while (j->p < j->end &&
           (*j->p == ' ' || *j->p == '\t' || *j->p == '\n' || *j->p == '\r'))
        ++j->p;
}

/* Skip whitespace, then consume the expected character. */
static int js_ch(struct js *j, char c) {
    js_ws(j);
    if (j->p >= j->end || *j->p != c)
        return 0;
    ++j->p;
    return 1;
}

static int js_hex4(struct js *j, unsigned *out) {
    unsigned v = 0;
    for (int i = 0; i < 4; ++i) {
        if (j->p >= j->end)
            return 0;
        char c = *j->p++;
        v <<= 4;
        if (c >= '0' && c <= '9') v |= (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v |= (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v |= (unsigned)(c - 'A' + 10);
        else return 0;
    }
    *out = v;
    return 1;
}

static void utf8_put(char **w, unsigned cp) {
    if (cp < 0x80) {
        *(*w)++ = (char)cp;
    } else if (cp < 0x800) {
        *(*w)++ = (char)(0xC0 | (cp >> 6));
        *(*w)++ = (char)(0x80 | (cp & 0x3F));
    } else if (cp < 0x10000) {
        *(*w)++ = (char)(0xE0 | (cp >> 12));
        *(*w)++ = (char)(0x80 | ((cp >> 6) & 0x3F));
        *(*w)++ = (char)(0x80 | (cp & 0x3F));
    } else {
        *(*w)++ = (char)(0xF0 | (cp >> 18));
        *(*w)++ = (char)(0x80 | ((cp >> 12) & 0x3F));
        *(*w)++ = (char)(0x80 | ((cp >> 6) & 0x3F));
        *(*w)++ = (char)(0x80 | (cp & 0x3F));
    }
}

/* Parse a string (opening quote not yet consumed); malloc'd UTF-8 or NULL.
   Decoded output is never longer than the escaped input, so sizing the buffer
   by the input span is safe. */
static char *js_string(struct js *j) {
    if (!js_ch(j, '"'))
        return NULL;
    char *buf = (char *)malloc((size_t)(j->end - j->p) + 1);
    if (!buf)
        return NULL;
    char *w = buf;
    while (j->p < j->end) {
        char c = *j->p++;
        if (c == '"') {
            *w = '\0';
            return buf;
        }
        if ((unsigned char)c < 0x20)
            break; /* raw control characters are invalid in JSON strings */
        if (c != '\\') {
            *w++ = c;
            continue;
        }
        if (j->p >= j->end)
            break;
        char e = *j->p++;
        unsigned cp;
        switch (e) {
        case '"': case '\\': case '/': *w++ = e; break;
        case 'b': *w++ = '\b'; break;
        case 'f': *w++ = '\f'; break;
        case 'n': *w++ = '\n'; break;
        case 'r': *w++ = '\r'; break;
        case 't': *w++ = '\t'; break;
        case 'u':
            if (!js_hex4(j, &cp))
                goto fail;
            if (cp >= 0xD800 && cp <= 0xDBFF) { /* high surrogate: pair up */
                unsigned lo;
                if (j->p + 1 >= j->end || j->p[0] != '\\' || j->p[1] != 'u')
                    goto fail;
                j->p += 2;
                if (!js_hex4(j, &lo) || lo < 0xDC00 || lo > 0xDFFF)
                    goto fail;
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                goto fail; /* lone low surrogate */
            }
            utf8_put(&w, cp);
            break;
        default:
            goto fail;
        }
    }
fail:
    free(buf);
    return NULL;
}

/* Parse an array of strings (opening bracket not yet consumed); malloc'd
   NULL-terminated vector or NULL. */
static char **js_strarray(struct js *j) {
    if (!js_ch(j, '['))
        return NULL;
    size_t cap = 8, n = 0;
    char **items = (char **)malloc(cap * sizeof(char *));
    if (!items)
        return NULL;
    js_ws(j);
    if (j->p < j->end && *j->p == ']') {
        ++j->p;
        items[0] = NULL;
        return items;
    }
    for (;;) {
        char *s = js_string(j);
        if (!s)
            goto fail;
        if (n + 2 > cap) {
            cap *= 2;
            char **grown = (char **)realloc(items, cap * sizeof(char *));
            if (!grown) {
                free(s);
                goto fail;
            }
            items = grown;
        }
        items[n++] = s;
        js_ws(j);
        if (j->p >= j->end)
            goto fail;
        if (*j->p == ',') {
            ++j->p;
            continue;
        }
        if (*j->p == ']') {
            ++j->p;
            items[n] = NULL;
            return items;
        }
        goto fail;
    }
fail:
    for (size_t i = 0; i < n; ++i)
        free(items[i]);
    free(items);
    return NULL;
}

static void free_strarray(char **items) {
    if (!items)
        return;
    for (char **it = items; *it; ++it)
        free(*it);
    free(items);
}

struct config {
    char *pyrel;
    char *bootstrap;
    char **args; /* NULL-terminated */
};

/* Load the sidecar at `rel` (relative to `dir`) into `cfg`. Returns 1 on
   success; on any failure returns 0 with `cfg` untouched-or-freed (caller
   falls back). */
static int load_config_at(const char *dir, const char *rel, struct config *cfg) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof(path), "%s/%s", dir, rel) >= (int)sizeof(path))
        return 0;
    FILE *f = fopen(path, "rb");
    if (!f)
        return 0;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return 0;
    }
    long size = ftell(f);
    if (size <= 0 || size > CONFIG_MAX) {
        fclose(f);
        return 0;
    }
    char *text = (char *)malloc((size_t)size);
    int ok = text && fseek(f, 0, SEEK_SET) == 0 &&
             fread(text, 1, (size_t)size, f) == (size_t)size;
    fclose(f);
    if (!ok) {
        free(text);
        return 0;
    }

    struct js j = { text, text + size };
    char *pyrel = NULL, *bootstrap = NULL;
    char **args = NULL;
    ok = 0;
    if (!js_ch(&j, '{'))
        goto done;
    js_ws(&j);
    if (j.p < j.end && *j.p == '}') {
        ++j.p;
    } else {
        for (;;) {
            char *key = js_string(&j);
            if (!key || !js_ch(&j, ':')) {
                free(key);
                goto done;
            }
            js_ws(&j);
            if (j.p < j.end && *j.p == '[') {
                char **arr = js_strarray(&j);
                if (!arr) {
                    free(key);
                    goto done;
                }
                if (strcmp(key, "args") == 0) {
                    free_strarray(args);
                    args = arr;
                } else {
                    free_strarray(arr); /* unknown array key: ignore */
                }
            } else {
                char *val = js_string(&j);
                if (!val) {
                    free(key);
                    goto done;
                }
                if (strcmp(key, "pyrel") == 0) {
                    free(pyrel);
                    pyrel = val;
                } else if (strcmp(key, "bootstrap") == 0) {
                    free(bootstrap);
                    bootstrap = val;
                } else {
                    free(val); /* unknown string key: ignore */
                }
            }
            free(key);
            js_ws(&j);
            if (j.p >= j.end)
                goto done;
            if (*j.p == ',') {
                ++j.p;
                continue;
            }
            if (*j.p == '}') {
                ++j.p;
                break;
            }
            goto done;
        }
    }
    js_ws(&j);
    ok = j.p == j.end && pyrel && bootstrap;

done:
    free(text);
    if (!ok) {
        free(pyrel);
        free(bootstrap);
        free_strarray(args);
        return 0;
    }
    if (!args) { /* "args" omitted: no fixed arguments */
        args = (char **)malloc(sizeof(char *));
        if (!args) {
            free(pyrel);
            free(bootstrap);
            return 0;
        }
        args[0] = NULL;
    }
    cfg->pyrel = pyrel;
    cfg->bootstrap = bootstrap;
    cfg->args = args;
    return 1;
}

/* Load this executable's sidecar config: "<base>.launcher.json" first (several
   launchers can share one bundle), then the fixed legacy name. */
static int load_config(const char *dir, const char *base, struct config *cfg) {
    char rel[PATH_MAX];
    if (snprintf(rel, sizeof(rel), CONFIG_REL_FMT, base) < (int)sizeof(rel) &&
        load_config_at(dir, rel, cfg))
        return 1;
    return load_config_at(dir, CONFIG_REL_LEGACY, cfg);
}

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
    /* Split into directory + basename; both halves live in `self` (realpath
       already resolved any /usr/local/bin symlink to the bundle-internal name,
       which is what the sidecar is named after). */
    char *slash = strrchr(self, '/');
    const char *base = self;
    if (slash) {
        *slash = '\0';
        base = slash + 1;
    }

    /* 2. load the sidecar config; fall back to the compiled-in values. */
    struct config cfg;
    int have_cfg = load_config(self, base, &cfg);
    if (!have_cfg) {
#ifdef PYAPPDIST_REQUIRE_CONFIG
        /* A prebuilt stub without its sidecar: the compiled-in defaults are
           placeholders, so running would silently do nothing. */
        fprintf(stderr, "pyappdist launcher: missing or invalid configuration "
                        "(" CONFIG_REL_FMT ")\n", base);
        return 125;
#endif
    }
    const char *pyrel = have_cfg ? cfg.pyrel : PYAPPDIST_PYREL;
    const char *bootstrap = have_cfg ? cfg.bootstrap : PYAPPDIST_BOOTSTRAP;
    const char *const *fixed = have_cfg ? (const char *const *)cfg.args : FIXED;

    /* 3. derive the bundled python path relative to our directory. */
    char raw[PATH_MAX];
    if (snprintf(raw, sizeof(raw), "%s/%s", self, pyrel) >= (int)sizeof(raw)) {
        fprintf(stderr, "pyappdist launcher: interpreter path too long\n");
        return 125;
    }
    char pyexe[PATH_MAX];
    if (!realpath(raw, pyexe)) {
        /* fall back to the un-normalized path; execv resolves .. via the kernel. */
        snprintf(pyexe, sizeof(pyexe), "%s", raw);
    }

    /* 4. isolate the environment. */
    scrub_python_env();

    /* 5. argv = { python3, -I, -c, bootstrap, fixed..., forwarded argv[1..], NULL } */
    int nfixed = 0;
    while (fixed[nfixed])
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
    args[k++] = (char *)bootstrap;
    for (int i = 0; i < nfixed; ++i)
        args[k++] = (char *)fixed[i];
    for (int i = 1; i < argc; ++i)
        args[k++] = argv[i];
    args[k] = NULL;

    execv(pyexe, args);

    /* execv only returns on failure. */
    perror("pyappdist launcher: execv");
    fprintf(stderr, "pyappdist launcher: failed to launch %s\n", pyexe);
    return 127;
}
