# pygamedemo

A pyappdist GUI sample. It opens a window with pygame-ce (a dependency with C
extensions) where a ball bounces around. Close the window or press ESC to quit.

The launcher is `gui = true`, so the distribution launches via `pythonw.exe` (no console).
It also shows that C-extension dependencies like pygame-ce are collected into the
wheelhouse (as Windows wheels) and installed into the runtime's site-packages.

## Build the distribution

```bash
pyappdist build samples/pygamedemo
```

The image / portable zip / MSI are written under `samples/pygamedemo/appdist/`.
