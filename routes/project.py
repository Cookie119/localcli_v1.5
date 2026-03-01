from flask import Blueprint, request, jsonify
from models.base import db_session
from models.project import (
    Project,
    Design,
    ProjectVersion,
    DesignElement,
    ProjectStatus,
)
from models.audit import AuditLog
from models.location import State, District
from services.rule_engine import RuleEngine
from sqlalchemy import text
import traceback

bp = Blueprint('project', __name__, url_prefix='/api/projects')

# routes/project.py - Fix create_project endpoint

@bp.route('/create', methods=['POST'])
def create_project():
    """Create new project with initial version"""
    try:
        data = request.json
        
        # Get or create default user
        user_check = db_session.execute(
            text("SELECT id FROM users LIMIT 1")
        ).first()
        
        if user_check:
            user_id = user_check[0]
        else:
            # Create default user if none exists
            role_check = db_session.execute(
                text("SELECT id FROM roles WHERE name = 'admin' LIMIT 1")
            ).first()
            
            if not role_check:
                result = db_session.execute(
                    text("INSERT INTO roles (name, description) VALUES ('admin', 'Administrator') RETURNING id")
                )
                role_id = result.fetchone()[0]
            else:
                role_id = role_check[0]
            
            result = db_session.execute(
                text("""
                    INSERT INTO users (full_name, email, password_hash, role_id, status) 
                    VALUES ('System User', 'system@nirmaan.ai', 'no-auth-mvp', :role_id, 'active')
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                """),
                {'role_id': role_id}
            )
            user_row = result.fetchone()
            user_id = user_row[0] if user_row else 1
        
        # Get regulation for project type
        query = text("""
            SELECT r.id 
            FROM regulations r
            WHERE r.authority_id = (
                SELECT authority_id 
                FROM project_types 
                WHERE id = :project_type_id
            )
            AND r.is_active = true
            ORDER BY r.effective_from DESC
            LIMIT 1
        """)
        
        regulation = db_session.execute(query, {
            'project_type_id': data['project_type_id']
        }).first()
        
        if not regulation:
            return jsonify({'error': 'No active regulation found'}), 400
        
        # Create project
        project_result = db_session.execute(
            text("""
                INSERT INTO projects (
                    name, project_type_id, authority_id, regulation_id, 
                    client_name, tentative_budget, created_by, status
                ) VALUES (
                    :name, :project_type_id, :authority_id, :regulation_id,
                    :client_name, :tentative_budget, :created_by, 'draft'
                ) RETURNING id, created_at
            """),
            {
                'name': data['name'],
                'project_type_id': data['project_type_id'],
                'authority_id': data['authority_id'],
                'regulation_id': regulation[0],
                'client_name': data.get('client_name'),
                'tentative_budget': data.get('tentative_budget'),
                'created_by': user_id
            }
        )
        
        project_row = project_result.first()
        project_id = project_row[0]
        
        # 🔴 IMPORTANT: Create initial project version
        version_result = db_session.execute(
            text("""
                INSERT INTO project_versions (
                    project_id, version_number, change_summary, created_by, is_final
                ) VALUES (
                    :project_id, 1, 'Initial version', :created_by, false
                ) RETURNING id
            """),
            {
                'project_id': project_id,
                'created_by': user_id
            }
        )
        
        version_id = version_result.fetchone()[0]
        
        db_session.commit()
        
        print(f"✅ Project {project_id} created with version {version_id}")
        
        return jsonify({
            'id': project_id,
            'name': data['name'],
            'status': 'draft',
            'version_id': version_id,
            'message': 'Project created successfully'
        })
        
    except Exception as e:
        db_session.rollback()
        print(f"❌ Error creating project: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:project_id>/calculate-far', methods=['POST'])
def calculate_far(project_id):
    """Calculate FAR based on plot and rules"""
    try:
        data = request.json
        
        # First, check if plot exists
        plot_query = text("""
            SELECT p.area_sqm, p.road_width_m 
            FROM plots p
            WHERE p.project_id = :project_id
        """)
        
        result = db_session.execute(plot_query, {'project_id': project_id})
        plot = result.first()
        
        # If no plot exists, create a default plot
        if not plot:
            print(f"No plot found for project {project_id}, creating default plot...")
            
            # Get plot area from request or use default
            plot_area = data.get('plot_area', 500) if data else 500
            road_width = data.get('road_width', 12) if data else 12
            
            # Get a default zone (first active zone)
            zone_query = text("SELECT id FROM zones WHERE is_active = true LIMIT 1")
            zone_result = db_session.execute(zone_query)
            zone = zone_result.first()
            zone_id = zone[0] if zone else None
            
            # Calculate dimensions (square root for a square plot)
            import math
            side = math.sqrt(plot_area)
            
            # Create default plot
            insert_query = text("""
                INSERT INTO plots (
                    project_id, zone_id, length_m, width_m, area_sqm, 
                    shape, road_width_m, corner_plot
                ) VALUES (
                    :project_id, :zone_id, :length, :width, :area,
                    'Rectangle', :road_width, false
                )
                RETURNING area_sqm, road_width_m
            """)
            
            insert_result = db_session.execute(insert_query, {
                'project_id': project_id,
                'zone_id': zone_id,
                'length': side,
                'width': side,
                'area': plot_area,
                'road_width': road_width
            })
            db_session.commit()
            
            plot = insert_result.first()
            print(f"Created default plot with area {plot[0] if plot else plot_area} sqm")
        
        # Get plot values safely
        if plot:
            plot_area = float(plot[0]) if plot[0] is not None else 500
            plot_road_width = float(plot[1]) if len(plot) > 1 and plot[1] is not None else 12
        else:
            plot_area = 500
            plot_road_width = 12
        
        # Get project details
        project = Project.get_by_id(project_id)
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404

        # Resolve state code for this project via authority
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
            print(f"Error resolving state for project {project_id}: {e}")
        
        # Get regulations for this project type and authority
        reg_query = text("""
            SELECT r.id, r.name 
            FROM regulations r
            WHERE r.authority_id = :authority_id
            AND r.is_active = true
            ORDER BY r.effective_from DESC
            LIMIT 1
        """)
        
        reg_result = db_session.execute(reg_query, {
            'authority_id': project.authority_id
        })
        regulation = reg_result.first()
        
        if not regulation:
            # Try to get any regulation
            reg_fallback = text("SELECT id FROM regulations WHERE is_active = true LIMIT 1")
            reg_result = db_session.execute(reg_fallback)
            regulation = reg_result.first()
            
            if not regulation:
                return jsonify({'error': 'No active regulations found in database'}), 404
        
        # Initialize rule engine
        try:
            rule_engine = RuleEngine(regulation[0])
        except Exception as e:
            print(f"Error initializing rule engine: {e}")
            rule_engine = None
        
        # Derive optional building metrics if provided
        total_floors = (data or {}).get('total_floors')
        floor_height = (data or {}).get('floor_height', 3.0)
        built_up_area = (data or {}).get('built_up_area')

        try:
            building_height = float(total_floors) * float(floor_height) if total_floors else None
        except Exception:
            building_height = None

        try:
            used_fsi = (float(built_up_area) / float(plot_area)) if built_up_area and plot_area else None
        except Exception:
            used_fsi = None

        # Prepare context for rules
        context = {
            'design_id': data.get('design_id', 0) if data else 0,
            'plot_area': plot_area,
            'road_width': plot_road_width,
            'project_type': project.project_type_id,
            'state': state_code,
            'total_floors': total_floors,
            'floor_height': floor_height,
            'building_height': building_height,
            'used_fsi': used_fsi,
            'has_fire_access_road': (data or {}).get('has_fire_access_road', False),
            'fire_access_width': (data or {}).get('fire_access_width', plot_road_width),
            'has_refuge_area': (data or {}).get('has_refuge_area', False),
            'has_premium_fsi': (data or {}).get('has_premium_fsi', False),
        }
        
        # Evaluate rules if engine exists
        if rule_engine:
            try:
                results = rule_engine.evaluate_all(context)
                summary = RuleEngine.summarize_results(results)
            except Exception as e:
                print(f"Error evaluating rules: {e}")
                results = []
                summary = None
        else:
            results = []
            summary = None
        
        # Calculate FAR (default to 2.0)
        max_far = 2.0
        for rule in results:
            if rule and isinstance(rule, dict):
                rule_code = rule.get('rule_code', '')
                if rule_code and 'FAR' in rule_code:
                    if rule.get('passed'):
                        max_far = float(rule.get('expected', 2.0))
                    break
        
        buildable_area = plot_area * max_far
        
        return jsonify({
            'plot_area': plot_area,
            'max_far': max_far,
            'buildable_area': buildable_area,
            'compliance': results,
            'compliance_summary': summary
        })
        
    except Exception as e:
        print(f"Error calculating FAR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:project_id>/archive', methods=['POST'])
def archive_project(project_id):
    """Archive a project by marking its status as completed or rejected.
    
    This is a backend implementation for project archival (FR-15).
    """
    try:
        project = Project.get_by_id(project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404

        data = request.json or {}
        reason = (data.get('reason') or '').lower()

        # Map simple reasons to status; default to completed
        if reason in ('abandoned', 'rejected', 'cancelled', 'canceled'):
            new_status = ProjectStatus.rejected
        else:
            new_status = ProjectStatus.completed

        before = {
            'status': project.status.value if hasattr(project.status, 'value') else project.status
        }

        project.status = new_status
        db_session.add(project)
        db_session.commit()

        # Audit log
        AuditLog.log(
            project_id=project.id,
            entity_type='project',
            entity_id=project.id,
            action='archive',
            before_state=before,
            after_state={'status': project.status.value if hasattr(project.status, 'value') else project.status},
            metadata={'reason': reason},
        )

        return jsonify({
            'id': project.id,
            'status': project.status.value if hasattr(project.status, 'value') else project.status,
        })
    except Exception as e:
        print(f"Error archiving project {project_id}: {e}")
        traceback.print_exc()
        db_session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:project_id>/clone', methods=['POST'])
def clone_project(project_id):
    """Clone an existing project, including its latest version and designs.
    
    Covers project cloning functionality from FR-15/16 (backend side).
    """
    try:
        from sqlalchemy.orm import joinedload

        original = Project.get_by_id(project_id)
        if not original:
            return jsonify({'error': 'Project not found'}), 404

        data = request.json or {}

        # Create cloned project
        cloned_project = Project(
            name=data.get('name') or f"{original.name} (Copy)",
            project_type_id=original.project_type_id,
            authority_id=original.authority_id,
            regulation_id=original.regulation_id,
            client_name=data.get('client_name', original.client_name),
            tentative_budget=data.get('tentative_budget', original.tentative_budget),
            status=ProjectStatus.draft,
            created_by=original.created_by,
        )

        db_session.add(cloned_project)
        db_session.flush()  # get ID

        # Get latest version of original project
        latest_version = (
            db_session.query(ProjectVersion)
            .filter(ProjectVersion.project_id == original.id)
            .order_by(ProjectVersion.version_number.desc())
            .options(joinedload(ProjectVersion.designs).joinedload(Design.elements))
            .first()
        )

        if latest_version:
            # Start cloned project at version 1
            cloned_version = ProjectVersion(
                project_id=cloned_project.id,
                version_number=1,
                change_summary=f"Cloned from project {original.id}, version {latest_version.version_number}",
                created_by=latest_version.created_by,
                is_final=False,
            )
            db_session.add(cloned_version)
            db_session.flush()

            # Clone designs and elements
            for design in latest_version.designs:
                cloned_design = Design(
                    project_version_id=cloned_version.id,
                    template_version_id=design.template_version_id,
                    total_floors=design.total_floors,
                    total_units=design.total_units,
                    parking_required=design.parking_required,
                    lift_required=design.lift_required,
                    built_up_area=design.built_up_area,
                    status=design.status,
                )
                db_session.add(cloned_design)
                db_session.flush()

                # Map old element IDs to new ones for parent-child relationships
                id_map = {}
                # Clone parent elements first
                for elem in design.elements:
                    cloned_elem = DesignElement(
                        design_id=cloned_design.id,
                        parent_element_id=None,  # temporary; fix after mapping
                        element_type=elem.element_type,
                        name=elem.name,
                        floor_number=elem.floor_number,
                        area=elem.area,
                        width=elem.width,
                        length=elem.length,
                        element_metadata=elem.element_metadata,
                    )
                    db_session.add(cloned_elem)
                    db_session.flush()
                    id_map[elem.id] = cloned_elem.id

                # Second pass: fix parent relationships using id_map
                for elem in design.elements:
                    if elem.parent_element_id and elem.parent_element_id in id_map:
                        new_id = id_map[elem.id]
                        new_parent_id = id_map.get(elem.parent_element_id)
                        if new_parent_id:
                            (
                                db_session.query(DesignElement)
                                .filter(DesignElement.id == new_id)
                                .update({'parent_element_id': new_parent_id})
                            )

        db_session.commit()

        # Audit log
        AuditLog.log(
            project_id=cloned_project.id,
            entity_type='project',
            entity_id=cloned_project.id,
            action='clone',
            metadata={'source_project_id': original.id},
        )

        return jsonify({
            'id': cloned_project.id,
            'name': cloned_project.name,
        })
    except Exception as e:
        print(f"Error cloning project {project_id}: {e}")
        traceback.print_exc()
        db_session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:project_id>/versions/<int:version_id>/finalise', methods=['POST'])
def finalise_version(project_id, version_id):
    """Mark a project version as final (FR-16 final version marking).
    
    Prevents accidental changes by clearly flagging the version as final.
    """
    try:
        version = (
            db_session.query(ProjectVersion)
            .filter(
                ProjectVersion.id == version_id,
                ProjectVersion.project_id == project_id,
            )
            .first()
        )
        if not version:
            return jsonify({'error': 'Project version not found'}), 404

        before = {'is_final': version.is_final}
        version.is_final = True
        db_session.add(version)

        # Optionally mark associated designs as completed
        db_session.query(Design).filter(
            Design.project_version_id == version.id
        ).update({'status': 'completed'})

        db_session.commit()

        # Audit log
        AuditLog.log(
            project_id=project_id,
            entity_type='project_version',
            entity_id=version.id,
            action='finalise',
            before_state=before,
            after_state={'is_final': version.is_final},
        )

        return jsonify({
            'project_id': project_id,
            'version_id': version.id,
            'is_final': version.is_final,
        })
    except Exception as e:
        print(f"Error finalising version {version_id} for project {project_id}: {e}")
        traceback.print_exc()
        db_session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route('/authorities', methods=['GET'])
def get_authorities():
    """
    Get authorities filtered by district and/or state
    Query params:
    - district_id (optional): Filter by district
    - state_id (optional): Filter by state
    - include_inactive (optional): Include inactive authorities
    """
    try:
        district_id = request.args.get('district_id')
        state_id = request.args.get('state_id')
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        
        query = """
            SELECT a.id, a.name, a.authority_type, a.is_active,
                   s.id as state_id, s.name as state_name,
                   d.id as district_id, d.name as district_name
            FROM authorities a
            JOIN states s ON a.state_id = s.id
            JOIN districts d ON a.district_id = d.id
            WHERE 1=1
        """
        params = {}
        
        if district_id:
            query += " AND a.district_id = :district_id"
            params['district_id'] = district_id
        elif state_id:
            query += " AND a.state_id = :state_id"
            params['state_id'] = state_id
            
        if not include_inactive:
            query += " AND a.is_active = true"
            query += " AND s.is_active = true"
            query += " AND d.is_active = true"
            
        query += " ORDER BY a.name"
        
        result = db_session.execute(text(query), params)
        authorities = []
        for row in result:
            authorities.append({
                'id': row[0],
                'name': row[1],
                'authority_type': row[2],
                'is_active': row[3],
                'state': {
                    'id': row[4],
                    'name': row[5]
                },
                'district': {
                    'id': row[6],
                    'name': row[7]
                }
            })
        
        return jsonify(authorities)
        
    except Exception as e:
        print(f"Error fetching authorities: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/regulations', methods=['GET'])
def get_regulations():
    """
    Get regulations filtered by authority and/or state
    Query params:
    - authority_id (optional): Filter by authority
    - state_id (optional): Filter by state
    - include_inactive (optional): Include inactive regulations
    - current_only (optional): Only return currently effective regulations
    """
    try:
        authority_id = request.args.get('authority_id')
        state_id = request.args.get('state_id')
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        current_only = request.args.get('current_only', 'true').lower() == 'true'
        
        query = """
            SELECT r.id, r.name, r.version_number, 
                   r.effective_from, r.effective_to, r.is_active,
                   a.id as authority_id, a.name as authority_name,
                   s.id as state_id, s.name as state_name
            FROM regulations r
            JOIN authorities a ON r.authority_id = a.id
            JOIN states s ON a.state_id = s.id
            WHERE 1=1
        """
        params = {}
        
        if authority_id:
            query += " AND r.authority_id = :authority_id"
            params['authority_id'] = authority_id
        elif state_id:
            query += " AND a.state_id = :state_id"
            params['state_id'] = state_id
            
        if not include_inactive:
            query += " AND r.is_active = true"
            query += " AND a.is_active = true"
            query += " AND s.is_active = true"
            
        if current_only:
            query += " AND (r.effective_from <= CURRENT_DATE AND (r.effective_to IS NULL OR r.effective_to >= CURRENT_DATE))"
            
        query += " ORDER BY r.effective_from DESC, r.name"
        
        result = db_session.execute(text(query), params)
        regulations = []
        for row in result:
            regulations.append({
                'id': row[0],
                'name': row[1],
                'version_number': row[2],
                'effective_from': row[3].isoformat() if row[3] else None,
                'effective_to': row[4].isoformat() if row[4] else None,
                'is_active': row[5],
                'authority': {
                    'id': row[6],
                    'name': row[7]
                },
                'state': {
                    'id': row[8],
                    'name': row[9]
                }
            })
        
        return jsonify(regulations)
        
    except Exception as e:
        print(f"Error fetching regulations: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/regulations/<int:regulation_id>/rules', methods=['GET'])
def get_regulation_rules(regulation_id):
    """
    Get all rules for a specific regulation
    """
    try:
        query = text("""
            SELECT r.id, r.rule_code, r.title, r.category, 
                   r.rule_type, r.expression_logic, r.description,
                   r.is_active
            FROM rules r
            WHERE r.regulation_id = :regulation_id
            AND r.is_active = true
            ORDER BY r.category, r.rule_code
        """)
        
        result = db_session.execute(query, {'regulation_id': regulation_id})
        rules = []
        for row in result:
            rules.append({
                'id': row[0],
                'rule_code': row[1],
                'title': row[2],
                'category': row[3],
                'rule_type': row[4],
                'expression_logic': row[5],
                'description': row[6],
                'is_active': row[7]
            })
        
        return jsonify(rules)
        
    except Exception as e:
        print(f"Error fetching rules: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/authorities/<int:authority_id>/regulations', methods=['GET'])
def get_authority_regulations(authority_id):
    """
    Get all regulations for a specific authority
    """
    try:
        query = text("""
            SELECT r.id, r.name, r.version_number, 
                   r.effective_from, r.effective_to, r.is_active
            FROM regulations r
            WHERE r.authority_id = :authority_id
            AND r.is_active = true
            ORDER BY r.effective_from DESC
        """)
        
        result = db_session.execute(query, {'authority_id': authority_id})
        regulations = []
        for row in result:
            regulations.append({
                'id': row[0],
                'name': row[1],
                'version_number': row[2],
                'effective_from': row[3].isoformat() if row[3] else None,
                'effective_to': row[4].isoformat() if row[4] else None,
                'is_active': row[5]
            })
        
        return jsonify(regulations)
        
    except Exception as e:
        print(f"Error fetching regulations: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# routes/project.py - Add these endpoints

@bp.route('', methods=['GET'])
def get_projects():
    """Get all projects (with optional filters)"""
    try:
        # Optional query parameters
        status = request.args.get('status')
        limit = request.args.get('limit', 100)
        
        query = """
            SELECT p.id, p.name, p.project_type_id, p.authority_id, 
                   p.regulation_id, p.client_name, p.tentative_budget,
                   p.status, p.created_by, p.created_at, p.updated_at,
                   pt.name as project_type_name,
                   a.name as authority_name
            FROM projects p
            LEFT JOIN project_types pt ON p.project_type_id = pt.id
            LEFT JOIN authorities a ON p.authority_id = a.id
            WHERE 1=1
        """
        params = {}
        
        if status:
            query += " AND p.status = :status"
            params['status'] = status
            
        query += " ORDER BY p.created_at DESC LIMIT :limit"
        params['limit'] = limit
        
        result = db_session.execute(text(query), params)
        projects = []
        
        for row in result:
            projects.append({
                'id': row[0],
                'name': row[1],
                'project_type_id': row[2],
                'authority_id': row[3],
                'regulation_id': row[4],
                'client_name': row[5],
                'tentative_budget': float(row[6]) if row[6] else None,
                'status': row[7],
                'created_by': row[8],
                'created_at': row[9].isoformat() if row[9] else None,
                'updated_at': row[10].isoformat() if row[10] else None,
                'project_type_name': row[11],
                'authority_name': row[12]
            })
        
        return jsonify(projects)
        
    except Exception as e:
        print(f"Error fetching projects: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# routes/project.py - Add this endpoint

# routes/project.py - Update get_project_designs

@bp.route('/<int:project_id>/designs', methods=['GET'])
def get_project_designs(project_id):
    """Get all designs for a project"""
    try:
        # First check if project exists
        project = db_session.execute(
            text("SELECT id FROM projects WHERE id = :project_id"),
            {'project_id': project_id}
        ).first()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # Get all versions for this project
        versions = db_session.execute(
            text("SELECT id FROM project_versions WHERE project_id = :project_id"),
            {'project_id': project_id}
        ).fetchall()
        
        if not versions:
            # No versions yet - return empty array, not 404
            print(f"ℹ️ No versions found for project {project_id}")
            return jsonify([])
        
        version_ids = [v[0] for v in versions]
        
        # Get designs for all versions
        query = text("""
            SELECT d.id, d.project_version_id, d.template_version_id,
                   d.total_floors, d.total_units, d.parking_required,
                   d.lift_required, d.built_up_area, d.status,
                   d.created_at, d.updated_at,
                   pv.version_number
            FROM designs d
            JOIN project_versions pv ON d.project_version_id = pv.id
            WHERE pv.project_id = :project_id
            ORDER BY d.created_at DESC
        """)
        
        result = db_session.execute(query, {'project_id': project_id})
        designs = []
        
        for row in result:
            designs.append({
                'id': row[0],
                'project_version_id': row[1],
                'template_version_id': row[2],
                'total_floors': row[3],
                'total_units': row[4],
                'parking_required': row[5],
                'lift_required': row[6],
                'built_up_area': float(row[7]) if row[7] else None,
                'status': row[8],
                'created_at': row[9].isoformat() if row[9] else None,
                'updated_at': row[10].isoformat() if row[10] else None,
                'version_number': row[11]
            })
        
        print(f"📊 Found {len(designs)} designs for project {project_id}")
        return jsonify(designs)
        
    except Exception as e:
        print(f"❌ Error fetching designs for project {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# Add to your backend
@bp.route('/api/templates', methods=['GET'])
def get_templates():
    """Get all active templates"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Optional filtering
    template_type = request.args.get('type')
    is_active = request.args.get('is_active', 'true').lower() == 'true'
    
    query = "SELECT id, name, code, template_type, description FROM templates WHERE is_active = %s"
    params = [is_active]
    
    if template_type:
        query += " AND template_type = %s"
        params.append(template_type)
    
    query += " ORDER BY name"
    
    cur.execute(query, params)
    templates = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(templates)