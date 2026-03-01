from flask import Blueprint, send_file, jsonify
from sqlalchemy import text
from decimal import Decimal
import os

from models.base import db_session
from models.rules import ComplianceResult
from models.cost import BOQItem
from services.rule_engine import RuleEngine
from services.reporting import generate_compliance_report, generate_cost_report

bp = Blueprint('report', __name__, url_prefix='/api/reports')


@bp.route('/projects/<int:project_id>/compliance.pdf', methods=['GET'])
def compliance_report(project_id):
    """
    Generate a PDF compliance summary report for the latest design of a project (FR-37).
    """
    try:
        # Get latest design id for the project
        row = db_session.execute(
            text(
                "SELECT d.id, p.regulation_id "
                "FROM designs d "
                "JOIN project_versions pv ON d.project_version_id = pv.id "
                "JOIN projects p ON pv.project_id = p.id "
                "WHERE p.id = :pid "
                "ORDER BY d.id DESC LIMIT 1"
            ),
            {'pid': project_id},
        ).first()

        if not row:
            return jsonify({'error': 'No design found for project'}), 404

        design_id, regulation_id = row

        # Re-evaluate rules using RuleEngine to get rich meta
        rule_engine = RuleEngine(regulation_id)
        ctx = {'design_id': design_id}
        compliance = rule_engine.evaluate_all(ctx)
        summary = RuleEngine.summarize_results(compliance)

        filename = f"compliance_project_{project_id}_design_{design_id}.pdf"
        generate_compliance_report(filename, project_id, design_id, compliance, summary)

        return send_file(
            filename,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/projects/<int:project_id>/cost.pdf', methods=['GET'])
def cost_report(project_id):
    """
    Generate a PDF cost / BOQ summary for a project (FR-37).
    Uses all BOQ items for the project.
    """
    try:
        items = db_session.query(BOQItem).filter(BOQItem.project_id == project_id).all()
        if not items:
            return jsonify({'error': 'No BOQ items found for project'}), 404

        serialised = []
        total_amount = Decimal('0')
        for i in items:
            amt = Decimal(str(i.amount))
            serialised.append({
                'category': i.category,
                'item_code': i.item_code,
                'description': i.description,
                'unit': i.unit,
                'quantity': float(i.quantity),
                'rate': float(i.rate),
                'amount': float(amt),
            })
            total_amount += amt

        filename = f"cost_project_{project_id}.pdf"
        generate_cost_report(filename, project_id, serialised, float(total_amount))

        return send_file(
            filename,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

