# routes/authorities.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
import traceback

bp = Blueprint('authorities', __name__, url_prefix='/api/authorities')

@bp.route('', methods=['GET'])
def get_authorities():
    """
    Get authorities filtered by district_id (required)
    """
    try:
        # Get district_id from query params
        district_id = request.args.get('district_id')
        
        # Validate required parameter
        if not district_id:
            return jsonify({'error': 'district_id is required'}), 400
        
        query = """
            SELECT a.id, a.name, a.authority_type, a.is_active,
                   s.id as state_id, s.name as state_name,
                   d.id as district_id, d.name as district_name
            FROM authorities a
            JOIN states s ON a.state_id = s.id
            JOIN districts d ON a.district_id = d.id
            WHERE a.district_id = :district_id
            AND a.is_active = true
            ORDER BY a.name
        """
        
        result = db_session.execute(text(query), {'district_id': district_id})
        authorities = []
        for row in result:
            authorities.append({
                'id': row[0],
                'name': row[1],
                'authority_type': row[2],
                'is_active': row[3],
                'state_id': row[4],
                'state_name': row[5],
                'district_id': row[6],
                'district_name': row[7]
            })
        
        print(f"Found {len(authorities)} authorities for district {district_id}")
        return jsonify(authorities)
        
    except Exception as e:
        print(f"Error fetching authorities: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500