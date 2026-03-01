from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from . import Base, db_session


class Role(Base):
    """
    Simple role model aligned with existing 'roles' table used in project creation.
    """

    __tablename__ = 'roles'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)


class User(Base):
    """
    Basic user model for auth/RBAC (NFR-40).
    Passwords are expected to be stored as hashes; for now we simply treat
    'password_hash' as an opaque string.
    """

    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role_id = Column(BigInteger, ForeignKey('roles.id'), nullable=False)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, server_default=func.now())

    @classmethod
    def get_by_email(cls, email: str):
        if not db_session:
            return None
        try:
            return db_session.query(cls).filter(cls.email == email).first()
        except Exception:
            return None

