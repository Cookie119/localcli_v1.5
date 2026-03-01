from flask import Blueprint, request, send_file, jsonify
from services.cad_generator import CADGenerator
from models.base import db_session
from sqlalchemy import text
import json
import os
import traceback

bp = Blueprint('export', __name__, url_prefix='/api/export')

@bp.route('/dxf/<int:design_id>', methods=['GET'])
def export_dxf(design_id):
    """Export design as DXF"""
    try:
        # Get design elements - wrap in text()
        query = text("""
            SELECT de.*, d.total_floors
            FROM design_elements de
            JOIN designs d ON de.design_id = d.id
            WHERE de.design_id = :design_id
            ORDER BY de.floor_number, de.id
        """)
        
        elements = db_session.execute(query, {'design_id': design_id}).fetchall()
        
        if not elements:
            return jsonify({'error': 'No design elements found'}), 404
        
        # Build layout data structure
        layout_data = {
            'building_width': 0,
            'building_length': 0,
            'floor_height': 3.0,  # Default floor height
            'floors': []
        }
        
        # Group by floor
        floors = {}
        for elem in elements:
            floor_num = elem.floor_number or 0
            if floor_num not in floors:
                floors[floor_num] = {
                    'flats': []
                }
            
            if elem.element_type == 'flat':
                metadata = elem.element_metadata if hasattr(elem, 'element_metadata') else {}
                floors[floor_num]['flats'].append({
                    'x': float(metadata.get('x', 0)) if metadata else 0,
                    'y': float(metadata.get('y', 0)) if metadata else 0,
                    'width': float(elem.width) if elem.width else 10,
                    'length': float(elem.length) if elem.length else 15,
                    'rooms': []
                })
            elif elem.element_type == 'room':
                # Find parent flat
                metadata = elem.element_metadata if hasattr(elem, 'element_metadata') else {}
                for flat in floors[floor_num]['flats']:
                    flat['rooms'].append({
                        'x': float(metadata.get('x', 0)) if metadata else 0,
                        'y': float(metadata.get('y', 0)) if metadata else 0,
                        'width': float(elem.width) if elem.width else 5,
                        'length': float(elem.length) if elem.length else 6,
                        'name': elem.name or 'Room'
                    })
        
        layout_data['floors'] = list(floors.values())
        
        # Calculate building dimensions
        max_width = 0
        max_length = 0
        for floor in layout_data['floors']:
            for flat in floor['flats']:
                max_width = max(max_width, flat['x'] + flat['width'])
                max_length = max(max_length, flat['y'] + flat['length'])
        
        layout_data['building_width'] = max(max_width, 50)  # Minimum width
        layout_data['building_length'] = max(max_length, 50)  # Minimum length
        
        # Generate DXF
        cad = CADGenerator()
        cad.generate_floor_plan(design_id, layout_data)
        
        # Save to temp file
        filename = f"design_{design_id}.dxf"
        cad.save_dxf(filename)
        
        return send_file(
            filename,
            as_attachment=True,
            download_name=f"nirmaan_design_{design_id}.dxf",
            mimetype='application/dxf'
        )
        
    except Exception as e:
        print(f"Error exporting DXF: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500