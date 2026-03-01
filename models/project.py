from sqlalchemy import Column, String, BigInteger, ForeignKey, Numeric, Enum, Boolean, Integer, Text, JSON, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base, db_session
import enum

class ProjectStatus(enum.Enum):
    draft = 'draft'
    approved = 'approved'
    in_progress = 'in_progress'
    completed = 'completed'
    rejected = 'rejected'

class DesignStatus(enum.Enum):
    draft = 'draft'
    approved = 'approved'
    completed = 'completed'

class ProjectType(Base):
    __tablename__ = 'project_types'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    @classmethod
    def get_all_active(cls):
        if not db_session:
            return []
        try:
            return db_session.query(cls).filter_by(is_active=True).all()
        except Exception as e:
            print(f"Error fetching project types: {e}")
            return []

class Project(Base):
    __tablename__ = 'projects'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(200), nullable=False)
    project_type_id = Column(BigInteger, ForeignKey('project_types.id'), nullable=False)
    authority_id = Column(BigInteger, ForeignKey('authorities.id'), nullable=False)
    regulation_id = Column(BigInteger, ForeignKey('regulations.id'), nullable=False)
    client_name = Column(String(150))
    tentative_budget = Column(Numeric(15, 2))
    status = Column(Enum(ProjectStatus), default='draft')
    created_by = Column(BigInteger, nullable=False)  # Remove ForeignKey temporarily
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    project_type = relationship('ProjectType', foreign_keys=[project_type_id])
    authority = relationship('Authority', foreign_keys=[authority_id])
    versions = relationship('ProjectVersion', backref='project', cascade='all, delete-orphan')
    
    def save(self):
        if not db_session:
            return None
        try:
            db_session.add(self)
            db_session.commit()
            return self
        except Exception as e:
            print(f"Error saving project: {e}")
            db_session.rollback()
            return None
    
    @classmethod
    def get_by_id(cls, id):
        if not db_session:
            return None
        return db_session.query(cls).get(id)

class ProjectVersion(Base):
    __tablename__ = 'project_versions'
    
    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=False)
    version_number = Column(Integer, nullable=False)
    change_summary = Column(Text)
    created_by = Column(BigInteger, nullable=False)  # Remove ForeignKey temporarily
    is_final = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    
    designs = relationship('Design', backref='project_version', cascade='all, delete-orphan')

class Design(Base):
    __tablename__ = 'designs'
    
    id = Column(BigInteger, primary_key=True)
    project_version_id = Column(BigInteger, ForeignKey('project_versions.id'), nullable=False)
    template_version_id = Column(BigInteger, ForeignKey('template_versions.id'), nullable=True)
    total_floors = Column(Integer, nullable=False)
    total_units = Column(Integer, nullable=True)
    parking_required = Column(Boolean, default=False)
    lift_required = Column(Boolean, default=False)
    built_up_area = Column(Numeric(14, 2), nullable=True)
    status = Column(Enum(DesignStatus), default='draft')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    elements = relationship('DesignElement', backref='design', cascade='all, delete-orphan')
    compliance_results = relationship('ComplianceResult', backref='design', cascade='all, delete-orphan')
    
    def save(self):
        if not db_session:
            print("❌ No database session available")
            return None
        try:
            print(f"💾 Saving design with {self.total_floors} floors, {self.total_units} units...")
            db_session.add(self)
            db_session.flush()  # This assigns an ID without committing
            print(f"✅ Design saved with ID: {self.id}")
            db_session.commit()
            return self
        except Exception as e:
            print(f"❌ Error saving design: {e}")
            import traceback
            traceback.print_exc()
            db_session.rollback()
            return None

class DesignElement(Base):
    __tablename__ = 'design_elements'
    
    id = Column(BigInteger, primary_key=True)
    design_id = Column(BigInteger, ForeignKey('designs.id'), nullable=False)
    parent_element_id = Column(BigInteger, ForeignKey('design_elements.id'))
    element_type = Column(String(50), nullable=False)
    name = Column(String(100))
    floor_number = Column(Integer)
    area = Column(Numeric(12, 2))
    width = Column(Numeric(10, 2))
    length = Column(Numeric(10, 2))
    # Use element_metadata to match the database column
    element_metadata = Column('element_metadata', JSON)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    parent = relationship('DesignElement', remote_side=[id], backref='children')