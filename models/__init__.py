from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# Create engine
try:
    engine = create_engine(DATABASE_URL, echo=True)
    # Test connection
    with engine.connect() as conn:
        print("✅ Database connection successful")
except Exception as e:
    print(f"❌ Database connection error: {e}")
    engine = None

# Create session factory
SessionFactory = sessionmaker(bind=engine) if engine else None
db_session = scoped_session(SessionFactory) if SessionFactory else None

# Base class for models
Base = declarative_base()
if Base and engine:
    Base.metadata.bind = engine

# Import all models so they're available when importing from models
from .location import State, District, Authority, Zone
from .project import Project, ProjectType, Design, DesignElement, ProjectStatus, DesignStatus
from .rules import Regulation, Rule, RuleParameter, ComplianceResult
from .templates import Template, TemplateVersion, TemplateElement
from .audit import AuditLog
from .cost import RateCard, BOQItem, CostScenario
from .auth import User, Role

# Export all models
__all__ = [
    'db_session',
    'engine',
    'Base',
    'State',
    'District',
    'Authority',
    'Zone',
    'Project',
    'ProjectType',
    'Design',
    'DesignElement',
    'ProjectStatus',
    'DesignStatus',
    'Regulation',
    'Rule',
    'RuleParameter',
    'ComplianceResult',
    'Template',
    'TemplateVersion',
    'TemplateElement',
    'AuditLog',
    'RateCard',
    'BOQItem',
    'CostScenario',
    'User',
    'Role',
]