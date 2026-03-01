# routes/templates.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
import traceback
import json

bp = Blueprint('templates', __name__, url_prefix='/api/templates')

@bp.route('', methods=['GET'])
def get_templates():
    """
    Get all active templates with optional filtering
    Query params:
    - type: filter by template_type (flat, floor, core, building)
    - authority_id: filter by authority
    - is_active: boolean (default true)
    """
    try:
        template_type = request.args.get('type')
        authority_id = request.args.get('authority_id')
        is_active = request.args.get('is_active', 'true').lower() == 'true'
        
        query = """
            SELECT 
                t.id, 
                t.name, 
                t.code, 
                t.template_type, 
                t.description, 
                t.is_active,
                t.authority_id,
                t.created_by,
                t.created_at,
                t.updated_at,
                a.name as authority_name
            FROM templates t
            LEFT JOIN authorities a ON t.authority_id = a.id
            WHERE t.is_active = :is_active
        """
        params = {'is_active': is_active}
        
        if template_type:
            query += " AND t.template_type = :template_type"
            params['template_type'] = template_type
            
        if authority_id:
            query += " AND t.authority_id = :authority_id"
            params['authority_id'] = authority_id
            
        query += " ORDER BY t.name"
        
        result = db_session.execute(text(query), params)
        templates = []
        
        for row in result:
            templates.append({
                'id': row[0],
                'name': row[1],
                'code': row[2],
                'template_type': row[3],
                'description': row[4],
                'is_active': row[5],
                'authority_id': row[6],
                'created_by': row[7],
                'created_at': row[8].isoformat() if row[8] else None,
                'updated_at': row[9].isoformat() if row[9] else None,
                'authority_name': row[10]
            })
        
        return jsonify(templates)
        
    except Exception as e:
        print(f"Error fetching templates: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:template_id>', methods=['GET'])
def get_template(template_id):
    """Get a specific template by ID with its versions"""
    try:
        # Get template details
        template_query = text("""
            SELECT 
                t.id, t.name, t.code, t.template_type, 
                t.description, t.is_active, t.authority_id,
                t.created_by, t.created_at, t.updated_at,
                a.name as authority_name
            FROM templates t
            LEFT JOIN authorities a ON t.authority_id = a.id
            WHERE t.id = :template_id
        """)
        
        template_row = db_session.execute(template_query, {'template_id': template_id}).first()
        
        if not template_row:
            return jsonify({'error': 'Template not found'}), 404
        
        # Get all versions of this template
        versions_query = text("""
            SELECT 
                id, version_number, change_summary, 
                is_default, created_by, created_at
            FROM template_versions
            WHERE template_id = :template_id
            ORDER BY version_number DESC
        """)
        
        versions_result = db_session.execute(versions_query, {'template_id': template_id})
        versions = []
        
        for v in versions_result:
            versions.append({
                'id': v[0],
                'version_number': v[1],
                'change_summary': v[2],
                'is_default': v[3],
                'created_by': v[4],
                'created_at': v[5].isoformat() if v[5] else None
            })
        
        template = {
            'id': template_row[0],
            'name': template_row[1],
            'code': template_row[2],
            'template_type': template_row[3],
            'description': template_row[4],
            'is_active': template_row[5],
            'authority_id': template_row[6],
            'created_by': template_row[7],
            'created_at': template_row[8].isoformat() if template_row[8] else None,
            'updated_at': template_row[9].isoformat() if template_row[9] else None,
            'authority_name': template_row[10],
            'versions': versions
        }
        
        return jsonify(template)
        
    except Exception as e:
        print(f"Error fetching template {template_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:template_id>/versions/<int:version_id>/elements', methods=['GET'])
def get_template_elements(template_id, version_id):
    """
    Get all elements for a specific template version
    This is the main endpoint for getting room layouts
    """
    try:
        # First verify the version exists and belongs to the template
        check_query = text("""
            SELECT id FROM template_versions 
            WHERE id = :version_id AND template_id = :template_id
        """)
        
        check = db_session.execute(check_query, {
            'version_id': version_id,
            'template_id': template_id
        }).first()
        
        if not check:
            return jsonify({'error': 'Template version not found'}), 404
        
        # Get all elements for this version
        elements_query = text("""
            WITH RECURSIVE element_tree AS (
                -- Base: get all elements
                SELECT 
                    e.id,
                    e.parent_element_id,
                    e.element_type,
                    e.name,
                    e.floor_number,
                    e.area,
                    e.width,
                    e.length,
                    e.metadata as element_metadata,
                    e.created_at,
                    e.updated_at,
                    0 as level,
                    CAST(e.id AS TEXT) as path
                FROM template_elements e
                WHERE e.template_version_id = :version_id
                
                UNION ALL
                
                -- Recursive: not really needed for flat structure, but keeps hierarchy
                SELECT 
                    e.id,
                    e.parent_element_id,
                    e.element_type,
                    e.name,
                    e.floor_number,
                    e.area,
                    e.width,
                    e.length,
                    e.metadata,
                    e.created_at,
                    e.updated_at,
                    et.level + 1,
                    et.path || ',' || CAST(e.id AS TEXT)
                FROM template_elements e
                JOIN element_tree et ON e.parent_element_id = et.id
            )
            SELECT * FROM element_tree
            ORDER BY path
        """)
        
        elements_result = db_session.execute(elements_query, {'version_id': version_id})
        
        # Organize elements by type and floor
        flats = []
        rooms = []
        elements_by_floor = {}
        
        for row in elements_result:
            # Parse metadata
            metadata = row[8]
            if metadata and isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            elif metadata and hasattr(metadata, 'keys'):
                metadata = dict(metadata)
            else:
                metadata = {}
            
            element = {
                'id': row[0],
                'parent_element_id': row[1],
                'element_type': row[2],
                'name': row[3],
                'floor_number': row[4],
                'area': float(row[5]) if row[5] else None,
                'width': float(row[6]) if row[6] else None,
                'length': float(row[7]) if row[7] else None,
                'metadata': metadata,
                'created_at': row[9].isoformat() if row[9] else None,
                'updated_at': row[10].isoformat() if row[10] else None,
                'level': row[11]
            }
            
            # Categorize
            if element['element_type'] == 'flat':
                flats.append(element)
            elif element['element_type'] == 'room':
                rooms.append(element)
            
            # Group by floor
            floor = element['floor_number'] or 0
            if floor not in elements_by_floor:
                elements_by_floor[floor] = []
            elements_by_floor[floor].append(element)
        
        # For flats, also include their rooms
        flat_map = {f['id']: f for f in flats}
        for room in rooms:
            parent_id = room.get('parent_element_id')
            if parent_id and parent_id in flat_map:
                if 'rooms' not in flat_map[parent_id]:
                    flat_map[parent_id]['rooms'] = []
                flat_map[parent_id]['rooms'].append(room)
        
        return jsonify({
            'template_id': template_id,
            'version_id': version_id,
            'total_elements': len(flats) + len(rooms),
            'flats': flats,
            'rooms': rooms,
            'elements_by_floor': elements_by_floor
        })
        
    except Exception as e:
        print(f"Error fetching template elements: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:template_id>/default/elements', methods=['GET'])
def get_default_template_elements(template_id):
    """Get elements from the default version of a template"""
    try:
        # Find default version
        version_query = text("""
            SELECT id FROM template_versions 
            WHERE template_id = :template_id AND is_default = true
            LIMIT 1
        """)
        
        version = db_session.execute(version_query, {'template_id': template_id}).first()
        
        if not version:
            # If no default, get the latest version
            version_query = text("""
                SELECT id FROM template_versions 
                WHERE template_id = :template_id
                ORDER BY version_number DESC
                LIMIT 1
            """)
            version = db_session.execute(version_query, {'template_id': template_id}).first()
            
            if not version:
                return jsonify({'error': 'No versions found for this template'}), 404
        
        # Redirect to the version endpoint
        return get_template_elements(template_id, version[0])
        
    except Exception as e:
        print(f"Error fetching default template: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/types', methods=['GET'])
def get_template_types():
    """Get distinct template types"""
    try:
        query = text("""
            SELECT DISTINCT template_type 
            FROM templates 
            WHERE is_active = true
            ORDER BY template_type
        """)
        
        result = db_session.execute(query)
        types = [row[0] for row in result]
        
        return jsonify(types)
        
    except Exception as e:
        print(f"Error fetching template types: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:template_id>/rooms', methods=['GET'])
def get_template_rooms(template_id):
    """
    Simplified endpoint - just get all rooms from a template
    Useful for quick previews
    """
    try:
        # Get default version
        version_query = text("""
            SELECT tv.id 
            FROM template_versions tv
            WHERE tv.template_id = :template_id
            ORDER BY tv.is_default DESC, tv.version_number DESC
            LIMIT 1
        """)
        
        version = db_session.execute(version_query, {'template_id': template_id}).first()
        
        if not version:
            return jsonify({'error': 'No versions found'}), 404
        
        # Get all rooms
        rooms_query = text("""
            SELECT 
                te.name,
                te.element_type,
                te.floor_number,
                te.width,
                te.length,
                te.metadata,
                parent.name as parent_name
            FROM template_elements te
            LEFT JOIN template_elements parent ON te.parent_element_id = parent.id
            WHERE te.template_version_id = :version_id
            AND te.element_type = 'room'
            ORDER BY te.floor_number, te.id
        """)
        
        rooms_result = db_session.execute(rooms_query, {'version_id': version[0]})
        
        rooms = []
        for row in rooms_result:
            metadata = row[5]
            if metadata and isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            rooms.append({
                'name': row[0],
                'type': row[1],
                'floor': row[2],
                'width': float(row[3]) if row[3] else None,
                'length': float(row[4]) if row[4] else None,
                'metadata': metadata,
                'parent': row[6]
            })
        
        return jsonify({
            'template_id': template_id,
            'version_id': version[0],
            'rooms': rooms,
            'total_rooms': len(rooms)
        })
        
    except Exception as e:
        print(f"Error fetching template rooms: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500