# pyside6demo

A pyappdist GUI sample. It shows a window with PySide6 (Qt). The launcher is
`gui = true`, so the distribution launches via `pythonw.exe` (no console).

It also shows that a large C-extension dependency like PySide6 (an abi3 wheel:
`cp39-abi3-win_amd64`) can be collected and installed into the cp312 runtime.

## Build the distribution

```bash
pyappdist build -C samples/pyside6demo
```
