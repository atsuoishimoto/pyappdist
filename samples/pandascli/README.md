# pandascli

A pyappdist CLI sample. It formats and prints a small DataFrame with pandas
(a C extension that depends on numpy). The launcher is `gui = false`, so the
distribution launches via `python.exe` (console shown).

It also shows that C-extension dependencies like pandas / numpy are collected as
Windows wheels and installed into the runtime's site-packages.

## Build the distribution

```bash
pyappdist build -C samples/pandascli
```
