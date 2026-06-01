# matplotlibdemo

A pyappdist GUI sample. It plots sin / cos curves in a window with matplotlib.
The launcher is `gui = true`, so the distribution launches via `pythonw.exe` (no console).

The backend is **TkAgg**. tkinter / tcl-tk ship with the python-build-standalone
runtime, so it runs without extra GUI dependencies (Qt, etc.). It also shows that the
C-extension dependencies matplotlib pulls in (numpy, etc.) are collected and installed
as Windows wheels.

## Build the distribution

```bash
pyappdist build samples/matplotlibdemo
```
