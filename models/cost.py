from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Numeric,
    Boolean,
    Date,
    ForeignKey,
    DateTime,
)
from sqlalchemy.sql import func
from . import Base, db_session


class RateCard(Base):
    __tablename__ = 'rate_cards'
    
    id = Column(BigInteger, primary_key=True)
    authority_id = Column(BigInteger, ForeignKey('authorities.id'), nullable=False)
    project_type_id = Column(BigInteger, ForeignKey('project_types.id'), nullable=False)
    
    # Add these missing fields
    state_code = Column(String(10), nullable=True)
    city = Column(String(100), nullable=True)
    item_code = Column(String(50), nullable=False)
    description = Column(String(255), nullable=False)
    unit = Column(String(20), nullable=False)
    quantity_source = Column(String(50), nullable=True)
    quantity_multiplier = Column(Numeric(14, 4), nullable=True)
    
    rate_per_sqm = Column(Numeric(12, 2), nullable=False)
    effective_from = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class BOQItem(Base):
    """
    BOQ lines for a project/design (FR-29/30/31).
    """

    __tablename__ = 'boq_items'

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=False)
    design_id = Column(BigInteger, ForeignKey('designs.id'), nullable=True)

    category = Column(String(50), nullable=False)  # civil / finishing / external / services
    item_code = Column(String(50), nullable=False)
    description = Column(String(255), nullable=False)
    unit = Column(String(20), nullable=False)

    quantity = Column(Numeric(14, 3), nullable=False)
    rate = Column(Numeric(14, 2), nullable=False)
    amount = Column(Numeric(16, 2), nullable=False)

    source = Column(String(20), nullable=False, default='auto')  # auto / manual
    override_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CostScenario(Base):
    """
    Cost sensitivity / material substitution scenarios (FR-29/30/31).

    factor_profile is a JSON blob mapping categories or item_codes to
    multipliers, e.g. {"civil": 1.1, "finishing": 0.9}.
    """

    __tablename__ = 'cost_scenarios'

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    factor_profile = Column(String, nullable=True)  # store as JSON string for simplicity

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# __table_args__ = (
#     Index('idx_boq_project_design', 'project_id', 'design_id'),
# )