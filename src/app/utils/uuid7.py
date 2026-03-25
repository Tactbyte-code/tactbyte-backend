# /utils/uuid7.py
import uuid
import uuid_utils


def uuid7() -> uuid.UUID:
    """
    Generates a UUIDv7 and returns it as a standard uuid.UUID.

    uuid_utils.uuid7() returns a uuid_utils.UUID object which is
    incompatible with SQLAlchemy's sentinel matching system — it expects
    the exact Python uuid.UUID type in result rows. Wrapping via str
    conversion ensures the standard type is always returned.
    """
    return uuid.UUID(str(uuid_utils.uuid7()))