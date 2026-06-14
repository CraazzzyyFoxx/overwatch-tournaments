# Re-export shared modules for backward-compatible `from src.core import errors, utils, pagination`
from shared.core import errors as errors  # noqa: F401
from shared.core import pagination as pagination  # noqa: F401
from shared.core import utils as utils  # noqa: F401
