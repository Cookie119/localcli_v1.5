from flask import Blueprint, request, jsonify
from models.base import db_session
from services.layout_ai import LayoutAI
from services.rule_engine import RuleEngine
from models.project import Design
from models.audit import AuditLog
from sqlalchemy import text
import json
import traceback

bp = Blueprint('layout', __name__, url_prefix='/api/layout')

@bp.route('/generate', methods=['POST'])
def generate_layout():
    """Generate layout using AI"""
    try:
        data = request.json
        print(f"📥 Received layout generation request: {json.dumps(data, indent=2)}")
        
        # Get project and regulation
        query = text("""
            SELECT p.regulation_id, p.authority_id, p.project_type_id,
                   pt.name as project_type_name
            FROM projects p
            JOIN project_types pt ON p.project_type_id = pt.id
            WHERE p.id = :project_id
        """)
        
        project = db_session.execute(query, {
            'project_id': data['project_id']
        }).first()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        print(f"📋 Project found: regulation_id={project.regulation_id}, type={project.project_type_name}")

        # Resolve state code for this project via authority (for state-specific rules)
        state_code = None
        try:
            state_query = text("""
                SELECT s.code
                FROM states s
                JOIN authorities a ON a.state_id = s.id
                WHERE a.id = :authority_id
                LIMIT 1
            """)
            state_row = db_session.execute(state_query, {
                'authority_id': project.authority_id
            }).first()
            if state_row:
                state_code = state_row[0]
        except Exception as e:
            print(f"Error resolving state for layout generation: {e}")
        
        # Check if project version exists, if not create one
        version_check = text("""
            SELECT id FROM project_versions 
            WHERE project_id = :project_id AND version_number = :version
        """)
        
        version = db_session.execute(version_check, {
            'project_id': data['project_id'],
            'version': data.get('project_version_id', 1)
        }).first()
        
        if not version:
            # Create project version
            print("📝 Creating project version...")
            version_insert = text("""
                INSERT INTO project_versions (project_id, version_number, change_summary, created_by, is_final)
                VALUES (:project_id, :version, :summary, 1, false)
                RETURNING id
            """)
            
            version_result = db_session.execute(version_insert, {
                'project_id': data['project_id'],
                'version': data.get('project_version_id', 1),
                'summary': f'Initial version for layout generation'
            })
            db_session.commit()
            version_id = version_result.fetchone()[0]
            print(f"✅ Created project version with ID: {version_id}")
        else:
            version_id = version[0]
            print(f"📋 Using existing project version: {version_id}")
        
        # Initialize AI
        ai = LayoutAI()

        # Choose layout strategy based on project type
        project_type_name = (project.project_type_name or "").upper()

        if "COMMERCIAL" in project_type_name or "OFFICE" in project_type_name:
            print("🏢 Generating commercial floorplate layout...")
            building_layout = ai.generate_commercial_building(
                total_floors=data['total_floors'],
                floorplate_depth=data.get('floorplate_depth', data.get('plot_length', 40)),
                requirements=data.get('requirements', {
                    "corridor_width": data.get('corridor_width', 2.4),
                    "core_width": data.get('core_width', 8.0),
                    "core_length": data.get('core_length', 10.0),
                }),
                constraints={
                    'plot_width': data['plot_width'],
                    'plot_length': data['plot_length'],
                    'setbacks': data.get('setbacks', {}),
                    'floor_height': data.get('floor_height', 3.5),
                },
            )
        else:
            # Default to apartment-style multi-unit layout
            print("🏠 Generating apartment building layout...")
            building_layout = ai.generate_apartment_building(
                total_floors=data['total_floors'],
                flats_per_floor=data['flats_per_floor'],
                flat_type=data['flat_type'],
                total_area_per_flat=data['target_area'],
                requirements=data.get('requirements', {}),
                constraints={
                    'plot_width': data['plot_width'],
                    'plot_length': data['plot_length'],
                    'setbacks': data.get('setbacks', {}),
                    'floor_height': data.get('floor_height', 3.0),
                },
            )

        layouts = building_layout.get('floors', [])
        
        # Calculate total built-up area
        total_area = 0
        for floor in layouts:
            for flat in floor.get('flats', []):
                total_area += flat.get('width', 0) * flat.get('length', 0)
        
        print(f"📐 Total built-up area: {total_area} sqm")
        
        # Create design record
        print("💾 Creating design record...")
        design = Design(
            project_version_id=version_id,
            total_floors=data['total_floors'],
            total_units=data['total_floors'] * data['flats_per_floor'],
            built_up_area=total_area,
            status='draft'
        )
        
        saved_design = design.save()
        
        if not saved_design:
            print("❌ Failed to save design")
            return jsonify({'error': 'Failed to save design'}), 500
        
        print(f"✅ Design saved with ID: {saved_design.id}")
        
        # Store design elements
        print("📝 Storing design elements...")
        element_count = 0
        for floor_idx, floor in enumerate(layouts):
            for flat_idx, flat in enumerate(floor.get('flats', [])):
                # Insert flat
                flat_query = text("""
                    INSERT INTO design_elements 
                        (design_id, element_type, name, floor_number, 
                         width, length, element_metadata)
                    VALUES 
                        (:design_id, 'flat', :name, :floor_number,
                         :width, :length, :element_metadata)
                    RETURNING id
                """)
                
                flat_result = db_session.execute(flat_query, {
                    'design_id': saved_design.id,
                    'name': f"Flat {flat_idx + 1}",
                    'floor_number': floor_idx,
                    'width': flat.get('width', 10),
                    'length': flat.get('length', 15),
                    'element_metadata': json.dumps({
                        'x': flat.get('x', 0),
                        'y': flat.get('y', 0)
                    })
                })
                
                flat_id = flat_result.fetchone()[0]
                element_count += 1
                
                # Insert rooms
                for room_idx, room in enumerate(flat.get('rooms', [])):
                    room_query = text("""
                        INSERT INTO design_elements 
                            (design_id, parent_element_id, element_type, name,
                             width, length, element_metadata)
                        VALUES 
                            (:design_id, :parent_id, 'room', :name,
                             :width, :length, :element_metadata)
                    """)
                    
                    db_session.execute(room_query, {
                        'design_id': saved_design.id,
                        'parent_id': flat_id,
                        'name': room.get('name', f'Room {room_idx + 1}'),
                        'width': room.get('width', 4),
                        'length': room.get('length', 5),
                        'element_metadata': json.dumps({
                            'x': room.get('x', 0),
                            'y': room.get('y', 0)
                        })
                    })
                    element_count += 1
        
        db_session.commit()
        print(f"✅ Stored {element_count} design elements")

        # Audit: design creation
        AuditLog.log(
            project_id=None,  # can be derived later via joins if needed
            design_id=saved_design.id,
            entity_type='design',
            entity_id=saved_design.id,
            action='create',
            after_state={
                'total_floors': saved_design.total_floors,
                'total_units': saved_design.total_units,
                'built_up_area': float(saved_design.built_up_area or 0),
            },
        )
        
        # Validate against rules
        print("📋 Evaluating compliance rules...")
        rule_engine = RuleEngine(project.regulation_id)
        
        # Derive additional context for height- and FSI-based rules
        floor_height = data.get('floor_height', 3.0)
        building_height = data['total_floors'] * floor_height
        plot_area = data.get('plot_width', 25) * data.get('plot_length', 20)
        used_fsi = (total_area / plot_area) if plot_area else 0

        design_context = {
            'design_id': saved_design.id,
            'total_floors': data['total_floors'],
            'total_units': data['total_floors'] * data['flats_per_floor'],
            'built_up_area': total_area,
            'plot_area': plot_area,
            'road_width': data.get('road_width', 12),
            'state': state_code,
            'floor_height': floor_height,
            'building_height': building_height,
            'used_fsi': used_fsi,
            'has_fire_access_road': data.get('has_fire_access_road', False),
            'fire_access_width': data.get('fire_access_width', data.get('road_width', 12)),
            'has_refuge_area': data.get('has_refuge_area', False),
        }
        
        compliance = rule_engine.evaluate_all(design_context)
        summary = RuleEngine.summarize_results(compliance)
        print(f"✅ Evaluated {len(compliance)} compliance rules. Overall status: {summary['overall_status']}")
        
        return jsonify({
            'design_id': saved_design.id,
            'layouts': layouts,
            'compliance': compliance,
            'compliance_summary': summary,
            'total_area': total_area
        })
        
    except Exception as e:
        print(f"❌ Error generating layout: {e}")
        import traceback
        traceback.print_exc()
        db_session.rollback()
        return jsonify({'error': str(e)}), 500