Samples
=======

The repository ships a set of runnable example apps under `samples/
<https://github.com/atsuoishimoto/pyappdist/tree/main/samples>`_, each with its
own ``[tool.pyappdist]`` config. They are the quickest way to see a real
``pyproject.toml`` for a given case, and they double as smoke tests for the
tricky parts of packaging — C extensions, GUI stacks, bundled data files, and
per-target :ref:`extras <config-targets>`.

To build one, run ``pyappdist build`` (or a specific target) from its directory:

.. code-block:: bash

   cd samples/helloworld
   uv run pyappdist build windows      # build just the Windows MSI target

The shippable installer lands under
``samples/<name>/appdist/<target>/``; build intermediates (runtime, wheelhouse,
image) live separately under ``samples/<name>/.appdist-build/<target>/``.

CLI samples
-----------

`helloworld <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/helloworld>`_
   The smallest possible config — a single ``main()`` and **no dependencies**.
   The best starting template; it defines a target for every format
   (``msi``, ``msix``, ``linux``, ``macos``, ``dmg``).

`pandascli <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pandascli>`_
   Formats and prints a DataFrame with pandas + numpy. Shows that C-extension
   dependencies are collected as binary wheels and installed into the runtime's
   site-packages. Console launcher.

`datafiles <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/datafiles>`_
   Ships a non-code data file (``data/ebi.jpeg``) via
   ``[tool.uv.build-backend].data`` and locates it at runtime through
   ``sysconfig``, then opens it with Pillow. Shows where package data lands in
   the install tree.

GUI samples
-----------

All GUI samples use ``gui = true``, so the distribution launches via
``pythonw.exe`` (no console window) on Windows.

`matplotlibdemo <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/matplotlibdemo>`_
   Plots sin / cos curves with matplotlib's **TkAgg** backend. tkinter / tcl-tk
   ship with the python-build-standalone runtime, so it needs no extra GUI
   dependencies; matplotlib's own C-extension stack (numpy, etc.) is collected
   as wheels.

`pygamedemo <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pygamedemo>`_
   Bounces a ball around a window with pygame-ce (a C-extension dependency),
   demonstrating that such wheels are collected and installed unmodified.

`pyside6demo <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pyside6demo>`_
   Shows a Qt window with PySide6 — a large ``abi3`` wheel (``cp39-abi3``)
   installed into the cp312 runtime, with Qt plugins shipped in their normal
   wheel layout.

`niceguidemo <https://github.com/atsuoishimoto/pyappdist/tree/main/samples/niceguidemo>`_
   "Weather Panel" — a web-based desktop GUI built with NiceGUI + pywebview +
   requests. Uses per-target ``extras`` (``gtk`` / ``qt`` / ``gui``) to pull the
   right pywebview backend on each platform.
