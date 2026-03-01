# In your routes/project.py or create a new file routes/location.py
from flask import Blueprint, request, jsonify
from models.base import db_session
from services.layout_ai import LayoutAI
from services.rule_engine import RuleEngine
from models.project import Design
from models.audit import AuditLog
from sqlalchemy import text
import json
import traceback

bp = Blueprint('location', __name__, url_prefix='/api/location')


@bp.route('/authorities', methods=['GET'])
def get_authorities():
    """Get authorities filtered by district"""
    try:
        district_id = request.args.get('district_id')
        if not district_id:
            return jsonify({'error': 'district_id is required'}), 400
        
        query = text("""
            SELECT id, name, authority_type, state_id, district_id
            FROM authorities 
            WHERE district_id = :district_id AND is_active = true
            ORDER BY name
        """)
        
        result = db_session.execute(query, {'district_id': district_id})
        authorities = []
        for row in result:
            authorities.append({
                'id': row[0],
                'name': row[1],
                'authority_type': row[2],
                'state_id': row[3],
                'district_id': row[4]
            })
        
        return jsonify(authorities)
    except Exception as e:
        return jsonify({'error': str(e)}), 500