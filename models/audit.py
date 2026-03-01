from sqlalchemy import Column, BigInteger, String, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from . import Base, db_session


class AuditLog(Base):
    """
    Simple audit trail for key domain actions.
    
    This is intended to support FR-36 (Audit Trail) incrementally:
    - Project lifecycle events (create/clone/archive/finalise)
    - Design creation and manual overrides
    - BOQ edits (to be wired later)
    """

    __tablename__ = 'audit_logs'

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey('projects.id'), nullable=True)
    design_id = Column(BigInteger, ForeignKey('designs.id'), nullable=True)
    entity_type = Column(String(50), nullable=False)  # e.g. 'project', 'design', 'design_element', 'boq_item'
    entity_id = Column(BigInteger, nullable=True)
    action = Column(String(50), nullable=False)  # e.g. 'create', 'update', 'clone', 'archive', 'finalise', 'override'
    actor = Column(String(150), nullable=True)  # until full auth, this can be 'system' or email
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    audit_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    @classmethod
    def log(
        cls,
        *,
        project_id=None,
        design_id=None,
        entity_type,
        entity_id=None,
        action,
        actor='system',
        before_state=None,
        after_state=None,
        audit_metadata=None,
    ):
        """Helper to append an audit entry without breaking the main flow."""
        if not db_session:
            return
        try:
            entry = cls(
                project_id=project_id,
                design_id=design_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                actor=actor,
                before_state=before_state,
                after_state=after_state,
                metadata=metadata,
            )
            db_session.add(entry)
            db_session.commit()
        except Exception:
            # Never let audit failures break the main transaction
            db_session.rollback()

# __table_args__ = (
#     Index('idx_audit_logs_project_created', 'project_id', 'created_at'),
#     Index('idx_audit_logs_entity', 'entity_type', 'entity_id'),
# )
