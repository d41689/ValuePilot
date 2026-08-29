"""
Import model modules to ensure SQLAlchemy relationship registries are populated.

This avoids runtime mapper resolution errors when models are accessed in scripts
or services that don't otherwise import the full model set.
"""

from app.models import users  # noqa: F401
from app.models import auth_tokens  # noqa: F401
from app.models import stocks  # noqa: F401
from app.models import artifacts  # noqa: F401
from app.models import extractions  # noqa: F401
from app.models import facts  # noqa: F401
from app.models import institutions  # noqa: F401
from app.models import oracles_lens  # noqa: F401
from app.models import coverage  # noqa: F401
from app.models import research  # noqa: F401
from app.models import notifications  # noqa: F401
from app.models import portfolios  # noqa: F401
from app.models import api_security  # noqa: F401
from app.models import sec_financials  # noqa: F401
from app.models import analysis_methods  # noqa: F401
