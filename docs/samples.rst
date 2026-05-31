Samples
=======

The ``samples/`` directory contains real-world apps built and verified
end-to-end. Each is an independent project that declares pyappdist as an editable
dev dependency, mirroring how you would use it in your own project.

.. list-table::
   :header-rows: 1
   :widths: 20 50 15

   * - Sample
     - Shows
     - Launcher
   * - ``helloworld``
     - minimal, no dependencies
     - console
   * - ``pandascli``
     - pandas + numpy (C extensions)
     - console
   * - ``pygamedemo``
     - pygame-ce (SDL)
     - GUI
   * - ``pyside6demo``
     - PySide6 / Qt (large ``abi3`` wheels)
     - GUI
   * - ``matplotlibdemo``
     - matplotlib (TkAgg, bundled tkinter)
     - GUI

Build any of them:

.. code-block:: bash

   uv run pyappdist build samples/pandascli

These exercise the cases freezers usually struggle with — C extensions, ``abi3``
wheels, Qt plugins, and GUI toolkits relying on bundled tkinter — and run
unmodified because the app is installed into a real runtime.
