from sqlalchemy import Column, String, BigInteger, ForeignKey, Numeric, Boolean, Text, Date, JSON, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base, db_session

class Regulation(Base):
    __tablename__ = 'regulations'
    
    id = Column(BigInteger, primary_key=True)
    authority_id = Column(BigInteger, ForeignKey('authorities.id'), nullable=False)
    name = Column(String(150), nullable=False)
    version_number = Column(String(50), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    rules = relationship('Rule', backref='regulation', cascade='all, delete-orphan')
    
    @classmethod
    def get_active_by_authority(cls, authority_id):
        if not db_session:
            return None
        return db_session.query(cls).filter_by(
            authority_id=authority_id, 
            is_active=True
        ).order_by(cls.effective_from.desc()).first()

class Rule(Base):
    __tablename__ = 'rules'
    
    id = Column(BigInteger, primary_key=True)
    regulation_id = Column(BigInteger, ForeignKey('regulations.id'), nullable=False)
    rule_code = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    rule_type = Column(String(20), nullable=False)
    expression_logic = Column(JSON, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    parameters = relationship('RuleParameter', backref='rule', cascade='all, delete-orphan')
    compliance_results = relationship('ComplianceResult', backref='rule', cascade='all, delete-orphan')

class RuleParameter(Base):
    __tablename__ = 'rule_parameters'
    
    id = Column(BigInteger, primary_key=True)
    rule_id = Column(BigInteger, ForeignKey('rules.id'), nullable=False)
    parameter_name = Column(String(100), nullable=False)
    parameter_value = Column(Numeric(12, 4), nullable=False)
    unit = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class ComplianceResult(Base):
    __tablename__ = 'compliance_results'
    
    id = Column(BigInteger, primary_key=True)
    design_id = Column(BigInteger, ForeignKey('designs.id'), nullable=False)
    rule_id = Column(BigInteger, ForeignKey('rules.id'), nullable=False)
    status = Column(String(20), default='not_evaluated')  # 'pass', 'fail', 'not_evaluated'
    actual_value = Column(Numeric(14, 4))
    expected_value = Column(Numeric(14, 4))
    remarks = Column(Text)
    evaluated_at = Column(DateTime, server_default=func.now())