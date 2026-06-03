Samples
=======

The ``samples/`` directory contains real-world apps built and verified
end-to-end. Each is an independent project that declares pyappdist as an editable
dev dependency, mirroring how you would use it in your own project. Most declare
several targets (Windows ``msi`` plus ``linux`` and ``macos``) in one config.

.. list-table::
   :header-rows: 1
   :widths: 20 50 15

   * - Sample
     - Shows
     - Launcher
   * - ``helloworld``
     - minimal, no dependencies
     - console
   * - ``datafiles``
     - bundled package data / resources
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

Build any of them (name a target when the sample defines several):

.. code-block:: bash

   uv run pyappdist build -C samples/pandascli windows-x86_64

These exercise the cases freezers usually struggle with — C extensions, ``abi3``
wheels, Qt plugins, and GUI toolkits relying on bundled tkinter — and run
unmodified because the app is installed into a real runtime.
