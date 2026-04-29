"""etc-platform — Template-first documentation generator for ETC projects.

Turn codebase + Docker into TKKT, TKCS, Test Case, HDSD documents.
Docs-as-Code pattern: AI produces structured JSON, Python engines render.
"""

__version__ = "3.0.0"
__author__ = "Công ty CP Hệ thống Công nghệ ETC"

from etc_platform.config import Config, load_config

__all__ = ["Config", "load_config", "__version__"]
