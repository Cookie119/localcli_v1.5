from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
from models.project import DesignElement, Design
from models.audit import AuditLog
from services.rule_engine import RuleEngine

bp = Blueprint('design', __name__, url_prefix='/api/designs')


@bp.route('/<int:design_id>/elements/<int:element_id>', methods=['PATCH'])
def update_design_element(design_id, element_id):
    """
    Manual override of a design element's geometry/metadata (FR-26 backend).

    Expected body can include:
    - width, length (floats)
    - metadata: {x, y, ...}

    Returns updated element and refreshed compliance summary for the design.
    """
    try:
        data = request.json or {}

        elem = (
            db_session.query(DesignElement)
            .filter(
                DesignElement.id == element_id,
                DesignElement.design_id == design_id,
            )
            .first()
        )
        if not elem:
            return jsonify({'error': 'Design element not found'}), 404

        before = {
            'width': float(elem.width) if elem.width is not None else None,
            'length': float(elem.length) if elem.length is not None else None,
            'element_metadata': elem.element_metadata,
        }

        # Apply overrides
        if 'width' in data:
            elem.width = data['width']
        if 'length' in data:
            elem.length = data['length']
        if 'metadata' in data:
            elem.element_metadata = data['metadata']

        db_session.add(elem)
        db_session.commit()

        # Audit manual override
        AuditLog.log(
            project_id=None,
            design_id=design_id,
            entity_type='design_element',
            entity_id=elem.id,
            action='override',
            before_state=before,
            after_state={
                'width': float(elem.width) if elem.width is not None else None,
                'length': float(elem.length) if elem.length is not None else None,
                'element_metadata': elem.element_metadata,
            },
        )

        # Re-evaluate compliance for this design
        design = db_session.query(Design).filter(Design.id == design_id).first()
        if design:
            # Resolve regulation for this design's project via SQL
            reg_query = text("""
                SELECT p.regulation_id, p.authority_id, s.code as state_code
                FROM projects p
                JOIN project_versions pv ON pv.project_id = p.id
                JOIN designs d ON d.project_version_id = pv.id
                JOIN authorities a ON a.id = p.authority_id
                JOIN states s ON s.id = a.state_id
                WHERE d.id = :design_id
                LIMIT 1
            """)
            row = db_session.execute(reg_query, {'design_id': design_id}).first()
        else:
            row = None

        compliance = []
        summary = None
        if row:
            regulation_id = row.regulation_id
            state_code = row.state_code
            try:
                rule_engine = RuleEngine(regulation_id)
                # Simple context for now – can be enriched later with recalculated areas
                ctx = {
                    'design_id': design_id,
                    'total_floors': design.total_floors if design else None,
                    'total_units': design.total_units if design else None,
                    'built_up_area': float(design.built_up_area or 0) if design else None,
                    'state': state_code,
                }
                compliance = rule_engine.evaluate_all(ctx)
                summary = RuleEngine.summarize_results(compliance)
            except Exception as e:
                print(f"Error re-evaluating compliance for design {design_id}: {e}")

        return jsonify({
            'element': {
                'id': elem.id,
                'design_id': elem.design_id,
                'width': float(elem.width) if elem.width is not None else None,
                'length': float(elem.length) if elem.length is not None else None,
                'metadata': elem.element_metadata,
            },
            'compliance': compliance,
            'compliance_summary': summary,
        })
    except Exception as e:
        db_session.rollback()
        return jsonify({'error': str(e)}), 500

# routes/design.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
import traceback

bp = Blueprint('design', __name__, url_prefix='/api/designs')

@bp.route('/<int:design_id>/elements', methods=['GET'])
def get_design_elements(design_id):
    """
    Get all design elements for a specific design_id
    Returns JSON that can be used for preview without CAD packages
    """
    try:
        # First check if design exists
        design_check = db_session.execute(
            text("SELECT id FROM designs WHERE id = :design_id"),
            {'design_id': design_id}
        ).first()
        
        if not design_check:
            return jsonify({'error': 'Design not found'}), 404
        
        # Get all design elements with their parent relationships
        query = text("""
            SELECT 
                de.id,
                de.design_id,
                de.parent_element_id,
                de.element_type,
                de.name,
                de.floor_number,
                de.area,
                de.width,
                de.length,
                de.element_metadata,
                de.created_at,
                de.updated_at,
                -- Get parent name for context
                parent.name as parent_name
            FROM design_elements de
            LEFT JOIN design_elements parent ON de.parent_element_id = parent.id
            WHERE de.design_id = :design_id
            ORDER BY de.floor_number, de.element_type, de.id
        """)
        
        result = db_session.execute(query, {'design_id': design_id})
        elements = []
        
        for row in result:
            # Parse metadata if it exists
            metadata = row[9]
            if metadata and isinstance(metadata, str):
                try:
                    import json
                    metadata = json.loads(metadata)
                except:
                    pass
            
            elements.append({
                'id': row[0],
                'design_id': row[1],
                'parent_element_id': row[2],
                'parent_name': row[12],
                'element_type': row[3],
                'name': row[4],
                'floor_number': row[5],
                'area': float(row[6]) if row[6] else None,
                'width': float(row[7]) if row[7] else None,
                'length': float(row[8]) if row[8] else None,
                'metadata': metadata,
                'created_at': row[10].isoformat() if row[10] else None,
                'updated_at': row[11].isoformat() if row[11] else None
            })
        
        # Also get design summary
        design_query = text("""
            SELECT 
                d.id,
                d.total_floors,
                d.total_units,
                d.built_up_area,
                d.status,
                p.name as project_name,
                p.id as project_id
            FROM designs d
            JOIN project_versions pv ON d.project_version_id = pv.id
            JOIN projects p ON pv.project_id = p.id
            WHERE d.id = :design_id
        """)
        
        design_result = db_session.execute(design_query, {'design_id': design_id})
        design_row = design_result.first()
        
        design_info = None
        if design_row:
            design_info = {
                'id': design_row[0],
                'total_floors': design_row[1],
                'total_units': design_row[2],
                'built_up_area': float(design_row[3]) if design_row[3] else None,
                'status': design_row[4],
                'project_name': design_row[5],
                'project_id': design_row[6]
            }
        
        # Group elements by floor for easier frontend rendering
        floors = {}
        for elem in elements:
            floor_num = elem['floor_number'] or 0
            if floor_num not in floors:
                floors[floor_num] = []
            floors[floor_num].append(elem)
        
        return jsonify({
            'design_id': design_id,
            'design_info': design_info,
            'elements': elements,
            'elements_by_floor': floors,
            'total_elements': len(elements)
        })
        
    except Exception as e:
        print(f"Error fetching design elements: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:design_id>/preview', methods=['GET'])
def preview_design(design_id):
    """
    Simplified preview - just returns flats and rooms in a simple structure
    Perfect for frontend rendering without complex CAD packages
    """
    try:
        # Get flats (parent elements)
        flats_query = text("""
            SELECT 
                id,
                name,
                floor_number,
                width,
                length,
                element_metadata
            FROM design_elements 
            WHERE design_id = :design_id AND element_type = 'flat'
            ORDER BY floor_number, id
        """)
        
        flats_result = db_session.execute(flats_query, {'design_id': design_id})
        flats = []
        
        for flat_row in flats_result:
            flat_id = flat_row[0]
            
            # Get rooms for this flat
            rooms_query = text("""
                SELECT 
                    id,
                    name,
                    width,
                    length,
                    element_metadata
                FROM design_elements 
                WHERE design_id = :design_id 
                AND parent_element_id = :flat_id
                AND element_type = 'room'
                ORDER BY id
            """)
            
            rooms_result = db_session.execute(rooms_query, {
                'design_id': design_id,
                'flat_id': flat_id
            })
            
            rooms = []
            for room_row in rooms_result:
                metadata = room_row[4]
                if metadata and isinstance(metadata, str):
                    try:
                        import json
                        metadata = json.loads(metadata)
                    except:
                        pass
                
                rooms.append({
                    'id': room_row[0],
                    'name': room_row[1],
                    'width': float(room_row[2]) if room_row[2] else 0,
                    'length': float(room_row[3]) if room_row[3] else 0,
                    'x': metadata.get('x', 0) if metadata else 0,
                    'y': metadata.get('y', 0) if metadata else 0
                })
            
            # Parse flat metadata
            flat_metadata = flat_row[5]
            if flat_metadata and isinstance(flat_metadata, str):
                try:
                    flat_metadata = json.loads(flat_metadata)
                except:
                    flat_metadata = {}
            
            flats.append({
                'id': flat_id,
                'name': flat_row[1],
                'floor': flat_row[2],
                'width': float(flat_row[3]) if flat_row[3] else 0,
                'length': float(flat_row[4]) if flat_row[4] else 0,
                'x': flat_metadata.get('x', 0) if flat_metadata else 0,
                'y': flat_metadata.get('y', 0) if flat_metadata else 0,
                'rooms': rooms
            })
        
        return jsonify({
            'design_id': design_id,
            'flats': flats,
            'total_flats': len(flats)
        })
        
    except Exception as e:
        print(f"Error generating preview: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:design_id>/svg', methods=['GET'])
def design_svg(design_id):
    """Generate simple SVG preview"""
    try:
        # Get design elements
        elements_query = text("""
            SELECT element_type, name, floor_number, width, length, element_metadata
            FROM design_elements 
            WHERE design_id = :design_id
            ORDER BY floor_number, element_type
        """)
        
        elements = db_session.execute(elements_query, {'design_id': design_id}).fetchall()
        
        # Calculate bounds
        max_x = 0
        max_y = 0
        for elem in elements:
            metadata = elem[5]
            if metadata and isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            else:
                metadata = {}
            
            x = metadata.get('x', 0)
            y = metadata.get('y', 0)
            w = float(elem[3]) if elem[3] else 0
            l = float(elem[4]) if elem[4] else 0
            
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + l)
        
        # Generate SVG
        svg = [f'<svg width="{max_x * 10 + 50}" height="{max_y * 10 + 50}" xmlns="http://www.w3.org/2000/svg">']
        svg.append(f'<rect x="0" y="0" width="{max_x * 10 + 40}" height="{max_y * 10 + 40}" fill="#f0f0f0" stroke="#ccc"/>')
        
        for elem in elements:
            elem_type, name, floor, width, length, metadata = elem
            
            if not width or not length:
                continue
            
            width = float(width)
            length = float(length)
            
            if metadata and isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            else:
                metadata = {}
            
            x = metadata.get('x', 0) * 10 + 20
            y = metadata.get('y', 0) * 10 + 20
            
            # Color by type
            colors = {
                'flat': '#add8e6',
                'living': '#90ee90',
                'bedroom': '#ffb6c1',
                'kitchen': '#ffd700',
                'bathroom': '#dda0dd',
                'balcony': '#f0e68c'
            }
            color = colors.get(elem_type, '#d3d3d3')
            if elem_type == 'room':
                for key in colors:
                    if key in name.lower():
                        color = colors[key]
                        break
            
            svg.append(f'<rect x="{x}" y="{y}" width="{width * 10}" height="{length * 10}" fill="{color}" stroke="black" stroke-width="1"/>')
            svg.append(f'<text x="{x + width * 5}" y="{y + length * 5}" font-size="8" text-anchor="middle">{name}</text>')
        
        svg.append('</svg>')
        
        return ''.join(svg), 200, {'Content-Type': 'image/svg+xml'}
        
    except Exception as e:
        print(f"Error generating SVG: {e}")
        return str(e), 500