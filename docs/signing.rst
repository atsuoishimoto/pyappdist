Code signing
============

Artifacts are unsigned by default. To sign each ``.exe`` and the ``.msi``, set
the ``PYAPPDIST_SIGN_CMD`` environment variable. The token ``{file}`` is replaced
with the path of the artifact being signed, and the command is run for each one.

.. code-block:: bash

   export PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'

When the variable is unset, signing is skipped silently.

Signing happens as part of ``pyappdist build``: each launcher executable is
signed after it is compiled, and the MSI is signed after it is built.

.. note::

   Obtaining and managing code-signing certificates is out of scope for
   pyappdist. Unsigned installers will trigger a Windows SmartScreen warning.
