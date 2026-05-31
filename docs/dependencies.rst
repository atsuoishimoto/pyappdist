Dependency resolution
======================

pyappdist pins **dependencies from your project's lockfile** so the distribution
matches the versions you tested. It exports a ``requirements.txt`` using your
package manager, then turns those requirements into wheels with the target
runtime's own ``python.exe``.

Why the lockfile
----------------

Resolving from PyPI at build time could drift from what you developed and tested
against. Exporting from the lockfile guarantees the shipped versions are exactly
the locked ones.

Why the *target* interpreter
----------------------------

The exported requirements include environment markers and are turned into wheels
by the target's ``python.exe`` via ``pip wheel -r``. Evaluating markers on the
target keeps them natively correct — for example pandas'
``tzdata; sys_platform == "win32"`` is included for a Windows target even when you
build from Linux. Dependencies with only an sdist are built into wheels at this
step, so the wheelhouse ends up containing wheels only and the later offline
install never needs a compiler.

Manager detection
-----------------

If ``[tool.pyappdist].manager`` is not set, pyappdist detects the manager by
lockfile, in this order:

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Manager
     - Lockfile
     - Export command
   * - uv
     - ``uv.lock``
     - ``uv export --frozen --no-dev --no-emit-project --format requirements-txt``
   * - poetry
     - ``poetry.lock``
     - ``poetry export -f requirements.txt --without dev``
   * - pipenv
     - ``Pipfile.lock``
     - ``pipenv requirements --hash``
   * - PDM
     - ``pdm.lock``
     - ``pdm export -f requirements --prod``

All exports are **production dependencies only** (development dependencies are
excluded, so pyappdist itself and other dev tooling are never bundled) and
**include hashes**.

Overriding the manager
----------------------

Set ``[tool.pyappdist].manager`` explicitly to bypass detection:

.. code-block:: toml

   [tool.pyappdist]
   manager = "poetry"

``requirements.txt`` mode
-------------------------

Set ``manager = "requirements.txt"`` to skip exporting and use a
``requirements.txt`` you maintain at the project root:

.. code-block:: toml

   [tool.pyappdist]
   manager = "requirements.txt"

Fallback behavior
-----------------

If no lockfile is found and ``manager`` is unset, pyappdist prints a warning and
falls back to ``requirements.txt`` mode. If that file is also absent, the build
fails with an error.

The manager tool must be installed at build time. As a developer you already use
it to manage the project, so this is normally already satisfied.
