# routes/plots.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from models.base import db_session
import traceback

bp = Blueprint('plots', __name__, url_prefix='/api')

@bp.route('/projects/<int:project_id>/plots', methods=['GET'])
def get_project_plots(project_id):
    """Get all plots for a project"""
    try:
        query = text("""
            SELECT p.id, p.project_id, p.zone_id, p.length_m, p.width_m, 
                   p.area_sqm, p.shape, p.road_width_m, p.road_category_id,
                   p.orientation_angle, p.corner_plot, p.created_at, p.updated_at,
                   z.name as zone_name, z.zone_type
            FROM plots p
            LEFT JOIN zones z ON p.zone_id = z.id
            WHERE p.project_id = :project_id
            ORDER BY p.id
        """)
        
        result = db_session.execute(query, {'project_id': project_id})
        plots = []
        
        for row in result:
            plots.append({
                'id': row[0],
                'project_id': row[1],
                'zone_id': row[2],
                'length_m': float(row[3]) if row[3] else None,
                'width_m': float(row[4]) if row[4] else None,
                'area_sqm': float(row[5]) if row[5] else None,
                'shape': row[6],
                'road_width_m': float(row[7]) if row[7] else None,
                'road_category_id': row[8],
                'orientation_angle': float(row[9]) if row[9] else 0,
                'corner_plot': row[10],
                'created_at': row[11].isoformat() if row[11] else None,
                'updated_at': row[12].isoformat() if row[12] else None,
                'zone_name': row[13],
                'zone_type': row[14]
            })
        
        print(f"Found {len(plots)} plots for project {project_id}")
        return jsonify(plots)
        
    except Exception as e:
        print(f"Error fetching plots for project {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/projects/<int:project_id>/plots', methods=['POST'])
def create_plot(project_id):
    """Create a new plot for a project"""
    try:
        data = request.json
        print(f"Creating plot for project {project_id} with data: {data}")
        
        # Validate required fields
        required_fields = ['zone_id', 'length_m', 'width_m']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Calculate area
        area_sqm = float(data['length_m']) * float(data['width_m'])
        
        # Insert plot
        query = text("""
            INSERT INTO plots (
                project_id, zone_id, length_m, width_m, area_sqm,
                shape, road_width_m, road_category_id, orientation_angle, corner_plot
            ) VALUES (
                :project_id, :zone_id, :length_m, :width_m, :area_sqm,
                :shape, :road_width_m, :road_category_id, :orientation_angle, :corner_plot
            ) RETURNING id
        """)
        
        result = db_session.execute(query, {
            'project_id': project_id,
            'zone_id': data['zone_id'],
            'length_m': data['length_m'],
            'width_m': data['width_m'],
            'area_sqm': area_sqm,
            'shape': data.get('shape', 'Rectangle'),
            'road_width_m': data.get('road_width_m'),
            'road_category_id': data.get('road_category_id'),
            'orientation_angle': data.get('orientation_angle', 0),
            'corner_plot': data.get('corner_plot', False)
        })
        
        db_session.commit()
        plot_id = result.fetchone()[0]
        
        print(f"Plot created with ID: {plot_id}")
        return jsonify({
            'id': plot_id,
            'message': 'Plot created successfully'
        }), 201
        
    except Exception as e:
        db_session.rollback()
        print(f"Error creating plot: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/plots/<int:plot_id>', methods=['GET'])
def get_plot(plot_id):
    """Get a specific plot by ID"""
    try:
        query = text("""
            SELECT p.id, p.project_id, p.zone_id, p.length_m, p.width_m, 
                   p.area_sqm, p.shape, p.road_width_m, p.road_category_id,
                   p.orientation_angle, p.corner_plot, p.created_at, p.updated_at,
                   z.name as zone_name, z.zone_type
            FROM plots p
            LEFT JOIN zones z ON p.zone_id = z.id
            WHERE p.id = :plot_id
        """)
        
        result = db_session.execute(query, {'plot_id': plot_id})
        row = result.first()
        
        if not row:
            return jsonify({'error': 'Plot not found'}), 404
        
        plot = {
            'id': row[0],
            'project_id': row[1],
            'zone_id': row[2],
            'length_m': float(row[3]) if row[3] else None,
            'width_m': float(row[4]) if row[4] else None,
            'area_sqm': float(row[5]) if row[5] else None,
            'shape': row[6],
            'road_width_m': float(row[7]) if row[7] else None,
            'road_category_id': row[8],
            'orientation_angle': float(row[9]) if row[9] else 0,
            'corner_plot': row[10],
            'created_at': row[11].isoformat() if row[11] else None,
            'updated_at': row[12].isoformat() if row[12] else None,
            'zone_name': row[13],
            'zone_type': row[14]
        }
        
        return jsonify(plot)
        
    except Exception as e:
        print(f"Error fetching plot {plot_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/plots/<int:plot_id>', methods=['PATCH'])
def update_plot(plot_id):
    """Update an existing plot"""
    try:
        data = request.json
        print(f"Updating plot {plot_id} with data: {data}")
        
        # Check if plot exists
        check = db_session.execute(
            text("SELECT id FROM plots WHERE id = :id"),
            {'id': plot_id}
        ).first()
        
        if not check:
            return jsonify({'error': 'Plot not found'}), 404
        
        # Build update query dynamically
        updates = []
        params = {'id': plot_id}
        
        update_fields = [
            'zone_id', 'length_m', 'width_m', 'shape', 
            'road_width_m', 'road_category_id', 'orientation_angle', 'corner_plot'
        ]
        
        for field in update_fields:
            if field in data:
                updates.append(f"{field} = :{field}")
                params[field] = data[field]
        
        # Recalculate area if dimensions changed
        if 'length_m' in data or 'width_m' in data:
            # Get current dimensions
            current = db_session.execute(
                text("SELECT length_m, width_m FROM plots WHERE id = :id"),
                {'id': plot_id}
            ).first()
            
            length = data.get('length_m', current[0])
            width = data.get('width_m', current[1])
            area_sqm = float(length) * float(width)
            
            updates.append("area_sqm = :area_sqm")
            params['area_sqm'] = area_sqm
        
        if updates:
            query = f"UPDATE plots SET {', '.join(updates)} WHERE id = :id"
            db_session.execute(text(query), params)
            db_session.commit()
            print(f"Plot {plot_id} updated successfully")
        
        return jsonify({'message': 'Plot updated successfully'})
        
    except Exception as e:
        db_session.rollback()
        print(f"Error updating plot {plot_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/plots/<int:plot_id>', methods=['DELETE'])
def delete_plot(plot_id):
    """Delete a plot"""
    try:
        # Check if plot exists
        check = db_session.execute(
            text("SELECT id FROM plots WHERE id = :id"),
            {'id': plot_id}
        ).first()
        
        if not check:
            return jsonify({'error': 'Plot not found'}), 404
        
        # Delete plot
        db_session.execute(
            text("DELETE FROM plots WHERE id = :id"),
            {'id': plot_id}
        )
        db_session.commit()
        
        print(f"Plot {plot_id} deleted successfully")
        return jsonify({'message': 'Plot deleted successfully'})
        
    except Exception as e:
        db_session.rollback()
        print(f"Error deleting plot {plot_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500