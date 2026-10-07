"""Import every model module here so that Base.metadata is complete.

Alembic's autogenerate and the model/migration drift test both rely on this module.
"""

from megooarti.repositories import models as _repository_models  # noqa: F401
from megooarti.security import models as _security_models  # noqa: F401
from megooarti.storage import models as _storage_models  # noqa: F401
from megooarti.system import models as _system_models  # noqa: F401
