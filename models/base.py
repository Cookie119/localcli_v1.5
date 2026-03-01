from sqlalchemy import create_engine, Column, BigInteger, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from config import Config

engine = create_engine(Config.DATABASE_URL)
db_session = scoped_session(sessionmaker(bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

class BaseModel(Base):
    __abstract__ = True
    
    id = Column(BigInteger, primary_key=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    @classmethod
    def get_by_id(cls, id):
        return cls.query.get(id)
    
    def save(self):
        db_session.add(self)
        db_session.commit()
        return self