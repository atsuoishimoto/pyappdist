# Configuration file for the Sphinx documentation builder.
#
# For the full list of options see:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from __future__ import annotations

import pathlib
import tomllib

_pyproject = tomllib.loads(
    (pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )
)

# -- Project information -----------------------------------------------------

project = "pyappdist"
author = "Atsuo Ishimoto"
copyright = "2026, Atsuo Ishimoto"
release = _pyproject["project"]["version"]
version = ".".join(release.split(".")[:2])

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autosectionlabel",
]

# Prefix section labels with the document name to keep them unique.
autosectionlabel_prefix_document = True

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_title = f"{project} {release}"

# "Edit on GitHub" links in the page header.
html_context = {
    "display_github": True,
    "github_user": "atsuoishimoto",
    "github_repo": "pyappdist",
    "github_version": "main",
    "conf_py_path": "/docs/",
}
