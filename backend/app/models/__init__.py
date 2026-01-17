"""
Import model modules to ensure SQLAlchemy relationship registries are populated.

This avoids runtime mapper resolution errors when models are accessed in scripts
or services that don't otherwise import the full model set.
"""

from app.models import users  # noqa: F401
from app.models import stocks  # noqa: F401
from app.models import artifacts  # noqa: F401
from app.models import extractions  # noqa: F401
from app.models import facts  # noqa: F401
