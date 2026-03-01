from flask import Blueprint, jsonify
from models.base import db_session
from models.audit import AuditLog

bp = Blueprint('audit', __name__, url_prefix='/api/audit')


@bp.route('/projects/<int:project_id>', methods=['GET'])
def project_audit_logs(project_id):
    """
    Return recent audit events for a project (FR-36 backend).
    """
    try:
        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.project_id == project_id)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
            .all()
        )

        return jsonify([
            {
                'id': l.id,
                'project_id': l.project_id,
                'design_id': l.design_id,
                'entity_type': l.entity_type,
                'entity_id': l.entity_id,
                'action': l.action,
                'actor': l.actor,
                'before_state': l.before_state,
                'after_state': l.after_state,
                'audit_metadata': l.audit_metadata,
                'created_at': l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/designs/<int:design_id>', methods=['GET'])
def design_audit_logs(design_id):
    """
    Return recent audit events for a design (FR-36 backend).
    """
    try:
        logs = (
            db_session.query(AuditLog)
            .filter(AuditLog.design_id == design_id)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
            .all()
        )

        return jsonify([
            {
                'id': l.id,
                'project_id': l.project_id,
                'design_id': l.design_id,
                'entity_type': l.entity_type,
                'entity_id': l.entity_id,
                'action': l.action,
                'actor': l.actor,
                'before_state': l.before_state,
                'after_state': l.after_state,
                'audit_metadata': l.audit_metadata,
                'created_at': l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

