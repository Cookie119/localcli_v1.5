# routes/zones.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
import traceback

bp = Blueprint('zones', __name__, url_prefix='/api/zones')

@bp.route('', methods=['GET'])
def get_zones():
    """Get all active zones"""
    try:
        # Optional filters
        authority_id = request.args.get('authority_id')
        zone_type = request.args.get('zone_type')
        
        query = """
            SELECT z.id, z.name, z.code, z.zone_type, 
                   z.description, z.is_active,
                   a.id as authority_id, a.name as authority_name
            FROM zones z
            LEFT JOIN authorities a ON z.authority_id = a.id
            WHERE z.is_active = true
        """
        params = {}
        
        if authority_id:
            query += " AND z.authority_id = :authority_id"
            params['authority_id'] = authority_id
            
        if zone_type:
            query += " AND z.zone_type = :zone_type"
            params['zone_type'] = zone_type
            
        query += " ORDER BY z.name"
        
        result = db_session.execute(text(query), params)
        zones = []
        
        for row in result:
            zones.append({
                'id': row[0],
                'name': row[1],
                'code': row[2],
                'zone_type': row[3],
                'description': row[4],
                'is_active': row[5],
                'authority_id': row[6],
                'authority_name': row[7]
            })
        
        print(f"Found {len(zones)} zones")  # Debug log
        return jsonify(zones)
        
    except Exception as e:
        print(f"Error fetching zones: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:zone_id>', methods=['GET'])
def get_zone(zone_id):
    """Get a specific zone by ID"""
    try:
        query = text("""
            SELECT z.id, z.name, z.code, z.zone_type, 
                   z.description, z.is_active,
                   a.id as authority_id, a.name as authority_name
            FROM zones z
            LEFT JOIN authorities a ON z.authority_id = a.id
            WHERE z.id = :zone_id
        """)
        
        result = db_session.execute(query, {'zone_id': zone_id})
        row = result.first()
        
        if not row:
            return jsonify({'error': 'Zone not found'}), 404
            
        zone = {
            'id': row[0],
            'name': row[1],
            'code': row[2],
            'zone_type': row[3],
            'description': row[4],
            'is_active': row[5],
            'authority_id': row[6],
            'authority_name': row[7]
        }
        
        return jsonify(zone)
        
    except Exception as e:
        print(f"Error fetching zone: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500