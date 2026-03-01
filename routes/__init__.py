from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv


from . import project, layout, export, cost, design, report, audit, auth, authorities, zones , plots



__all__ = [
    'project',
    'layout', 
    'export',
    'cost',
    'design',
    'report',
    'audit',
    'auth',
    'authorities',
    'zones',
    'plots'

]

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# Create engine with error handling
try:
    engine = create_engine(DATABASE_URL, echo=True)
    # Test connection
    with engine.connect() as conn:
        print("Database connection successful")
except Exception as e:
    print(f"Database connection error: {e}")
    engine = None

# Create session factory
db_session = scoped_session(sessionmaker(bind=engine)) if engine else None

# Base class for models
Base = declarative_base()
if Base and engine:
    Base.metadata.bind = engine

