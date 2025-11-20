"""
Module runner for ``python -m extensions.intraday_ml.labeling``.

The legacy labeler never exposed a CLI entrypoint, but earlier workflows invoked
``python -m extensions.intraday_ml.labeling`` which simply executed the module.
Keeping a thin shim preserves that ergonomics now that the labeler is a
package.
"""

from . import *  # noqa: F401,F403 - re-export legacy module side effects
