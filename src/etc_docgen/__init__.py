"""etc-docgen — Template-first documentation generator for ETC projects.

Turn codebase + Docker into TKKT, TKCS, Test Case, HDSD documents.
Docs-as-Code pattern: AI produces structured JSON, Python engines render.
"""

__version__ = "1.0.0"
__author__ = "Công ty CP Hệ thống Công nghệ ETC"

from etc_docgen.config import Config, load_config

__all__ = ["Config", "load_config", "__version__"]
