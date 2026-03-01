from sqlalchemy import Column, String, BigInteger, ForeignKey, Numeric, Boolean, Integer, JSON, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base

class Template(Base):
    __tablename__ = 'templates'
    
    id = Column(BigInteger, primary_key=True)
    authority_id = Column(BigInteger, ForeignKey('authorities.id'))
    name = Column(String(150), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    template_type = Column(String(50), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_by = Column(BigInteger, ForeignKey('users.id'))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    versions = relationship('TemplateVersion', backref='template', cascade='all, delete-orphan')

class TemplateVersion(Base):
    __tablename__ = 'template_versions'
    
    id = Column(BigInteger, primary_key=True)
    template_id = Column(BigInteger, ForeignKey('templates.id'), nullable=False)
    version_number = Column(Integer, nullable=False)
    change_summary = Column(Text)
    is_default = Column(Boolean, default=False)
    created_by = Column(BigInteger, ForeignKey('users.id'))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    elements = relationship('TemplateElement', backref='template_version', cascade='all, delete-orphan')

class TemplateElement(Base):
    __tablename__ = 'template_elements'
    
    id = Column(BigInteger, primary_key=True)
    template_version_id = Column(BigInteger, ForeignKey('template_versions.id'), nullable=False)
    parent_element_id = Column(BigInteger, ForeignKey('template_elements.id'))
    element_type = Column(String(50), nullable=False)
    name = Column(String(100))
    floor_number = Column(Integer)
    area = Column(Numeric(12, 2))
    width = Column(Numeric(10, 2))
    length = Column(Numeric(10, 2))
    element_metadata = Column('metadata', JSON)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    parent = relationship('TemplateElement', remote_side=[id], backref='children')