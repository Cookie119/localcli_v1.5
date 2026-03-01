from sqlalchemy import Column, String, Boolean, ForeignKey, BigInteger, Text
from sqlalchemy.orm import relationship
from . import Base, db_session

class State(Base):
    __tablename__ = 'states'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(10), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    
    districts = relationship('District', backref='state')
    
    @classmethod
    def get_all_active(cls):
        if not db_session:
            return []
        try:
            return db_session.query(cls).filter_by(is_active=True).all()
        except Exception as e:
            print(f"Error fetching states: {e}")
            return []

class District(Base):
    __tablename__ = 'districts'
    
    id = Column(BigInteger, primary_key=True)
    state_id = Column(BigInteger, ForeignKey('states.id'), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(20))
    is_active = Column(Boolean, default=True)
    
    @classmethod
    def get_by_state(cls, state_id):
        if not db_session:
            return []
        try:
            return db_session.query(cls).filter_by(
                state_id=state_id, 
                is_active=True
            ).all()
        except Exception as e:
            print(f"Error fetching districts: {e}")
            return []

class Authority(Base):
    __tablename__ = 'authorities'
    
    id = Column(BigInteger, primary_key=True)
    state_id = Column(BigInteger, ForeignKey('states.id'), nullable=False)
    district_id = Column(BigInteger, ForeignKey('districts.id'), nullable=False)
    name = Column(String(150), nullable=False)
    authority_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)

class Zone(Base):
    __tablename__ = 'zones'
    
    id = Column(BigInteger, primary_key=True)
    authority_id = Column(BigInteger, ForeignKey('authorities.id'), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    zone_type = Column(String(50), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)