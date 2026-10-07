"""Import every model module here so that Base.metadata is complete.

Alembic's autogenerate and the model/migration drift test both rely on this module.
"""

from megooarti.system import models as _system_models  # noqa: F401
