from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as PostgreSQLJSONB
JSONB = JSON().with_variant(PostgreSQLJSONB(), "postgresql")
