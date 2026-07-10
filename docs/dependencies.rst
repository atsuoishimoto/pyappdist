Dependency resolution
======================

pyappdist pins **dependencies from your project's lockfile** so the distribution
matches the versions you tested. It exports the lock with your package manager —
to a PEP 751 ``pylock.toml`` for uv, or a ``requirements.txt`` for the other
managers — then turns those pins into wheels with the target runtime's own
``python.exe``.

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

**uv** — lockfile ``uv.lock``::

   uv export --frozen --no-dev --no-emit-project --format pylock.toml

uv exports a PEP 751 ``pylock.toml`` instead of a requirements.txt; see
`Per-package indexes`_ below for why.

**poetry** — lockfile ``poetry.lock``::

   poetry export -f requirements.txt --without dev

**pipenv** — lockfile ``Pipfile.lock``::

   pipenv requirements --hash

**PDM** — lockfile ``pdm.lock``::

   pdm export -f requirements --prod

All exports are **production dependencies only** (development dependencies are
excluded, so pyappdist itself and other dev tooling are never bundled) and
**include hashes**.

.. _Per-package indexes:

Per-package indexes (uv only)
-----------------------------

A lock can pin *individual packages* to an alternative index. The typical case
is a **GPU (CUDA) build of PyTorch** from the PyTorch wheel index, configured
with ``[tool.uv.sources]`` and an ``explicit = true`` ``[[tool.uv.index]]``:

.. code-block:: toml

   [tool.uv.sources]
   torch = [
       { index = "pytorch-cu130", marker = "sys_platform == 'win32' or sys_platform == 'linux'" },
   ]

   [[tool.uv.index]]
   name = "pytorch-cu130"
   url = "https://download.pytorch.org/whl/cu130"
   explicit = true

pip's ``--index-url`` / ``--extra-index-url`` are *global* options, so a
requirements.txt cannot express this kind of per-package routing. The PEP 751
``pylock.toml`` that uv exports records each package's **exact artifact URLs
and hashes** instead, and pip fetches those URLs directly without consulting
any index — the per-package pin survives into the build exactly as locked.

For GPU builds of PyTorch (or any project pinning packages to a dedicated
index) we therefore recommend managing the project with **uv**, configured as
described in the uv documentation:
`Using uv with PyTorch <https://docs.astral.sh/uv/guides/integration/pytorch/>`_.
The ``pytorchdemo`` sample (:doc:`samples`) is a working configuration. With
the other managers the exported requirements.txt flattens index configuration
into global options, which cannot pin an index per package.

.. note::

   pip's ``pylock.toml`` support is recent (and marked experimental by pip), so
   the bundled runtime needs a reasonably new pip. Current
   python-build-standalone runtimes bundle one that qualifies.

Including optional-dependency extras
------------------------------------

By default only the production (non-dev) dependencies are exported. To also bundle
one or more ``[project.optional-dependencies]`` extras, list them per target with
``extras``:

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "win"
   platform = "windows-x86_64"
   format = "msi"
   extras = ["gui", "pdf"]

Each name is passed through to the manager's own extra selector, alongside the
production dependencies. ``extras`` is ignored (with a warning) in
``requirements.txt`` mode, since that file is used verbatim.

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
