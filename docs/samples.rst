Samples
=======

The ``samples/`` directory contains real-world apps built and verified
end-to-end. Each is an independent project that declares pyappdist as an editable
dev dependency, mirroring how you would use it in your own project. Most declare
several targets (Windows ``msi`` plus ``linux`` and ``macos``) in one config.

``helloworld``
   Minimal, no dependencies (console launcher).

``datafiles``
   Bundled package data / resources (console launcher).

``pandascli``
   pandas + numpy, i.e. C extensions (console launcher).

``pygamedemo``
   pygame-ce (SDL), a GUI launcher.

``pyside6demo``
   PySide6 / Qt with large ``abi3`` wheels, a GUI launcher.

``matplotlibdemo``
   matplotlib (TkAgg, bundled tkinter), a GUI launcher.

Build any of them (name a target when the sample defines several):

.. code-block:: bash

   uv run pyappdist build -C samples/pandascli windows-x86_64

These exercise the cases freezers usually struggle with — C extensions, ``abi3``
wheels, Qt plugins, and GUI toolkits relying on bundled tkinter — and run
unmodified because the app is installed into a real runtime.
