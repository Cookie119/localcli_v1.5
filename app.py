from flask import Flask, render_template, jsonify, request, g
from models import db_session, engine
from models.location import State, District
from models.project import ProjectType
from routes import project, layout, export, cost, design, report, audit, auth, authorities , zones, plots
import traceback
import os
import time
from sqlalchemy import text
from flask_cors import CORS 

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

        # Configure CORS - allow requests from Next.js dev server
    CORS(app, origins=[
        'http://localhost:3000',  # Next.js default
        'http://127.0.0.1:3000',
        'http://localhost:5000',   # Your Flask server
        'http://127.0.0.1:5000',
    ], supports_credentials=True)
    
    # Register blueprints
    app.register_blueprint(project.bp)
    app.register_blueprint(layout.bp)
    app.register_blueprint(export.bp)
    app.register_blueprint(cost.bp)
    app.register_blueprint(design.bp)
    app.register_blueprint(report.bp)
    app.register_blueprint(audit.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(authorities.bp)
    app.register_blueprint(zones.bp)
    app.register_blueprint(plots.bp)
    

    @app.before_request
    def _start_timer():
        """Simple request timing for basic performance insight (NFR-39)."""
        g._start_time = time.time()

    @app.after_request
    def _log_timing(response):
        try:
            if hasattr(g, "_start_time"):
                elapsed = (time.time() - g._start_time) * 1000.0
                response.headers["X-Request-Time-ms"] = f"{elapsed:.1f}"
        except Exception:
            pass
        return response
    
    @app.route('/not_home')
    def index():
        return render_template('preview.html')
    

    @app.route('/layout_preview')
    def layout_preview():
        return render_template('layout.html')

    @app.route('/api/states', methods=['GET'])
    def get_states():
        """Get all active states"""
        try:
            if not db_session:
                return jsonify({'error': 'Database connection not available'}), 500
            
            states = State.get_all_active()
            return jsonify([{
                'id': s.id,
                'name': s.name,
                'code': s.code
            } for s in states])
        except Exception as e:
            print(f"Error in /api/states: {e}")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/districts/<int:state_id>', methods=['GET'])
    def get_districts(state_id):
        """Get districts for a state"""
        try:
            if not db_session:
                return jsonify({'error': 'Database connection not available'}), 500
            
            districts = District.get_by_state(state_id)
            return jsonify([{
                'id': d.id,
                'name': d.name,
                'code': d.code
            } for d in districts])
        except Exception as e:
            print(f"Error in /api/districts: {e}")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/project-types', methods=['GET'])
    def get_project_types():
        """Get all project types"""
        try:
            if not db_session:
                return jsonify({'error': 'Database connection not available'}), 500
            
            project_types = ProjectType.get_all_active()
            result = []
            for pt in project_types:
                result.append({
                    'id': pt.id,
                    'name': pt.name,
                    'code': pt.code,
                    'description': pt.description
                })
            return jsonify(result)
        except Exception as e:
            print(f"Error in /api/project-types: {e}")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/debug/project/<int:project_id>', methods=['GET'])
    def debug_project(project_id):
        """Debug endpoint to check project details"""
        try:
            from sqlalchemy import text  # or import at the top of file
            
            # Check project
            project = db_session.execute(
                text("SELECT * FROM projects WHERE id = :id"),
                {'id': project_id}
            ).first()
            
            # Check plots
            plots = db_session.execute(
                text("SELECT * FROM plots WHERE project_id = :project_id"),
                {'project_id': project_id}
            ).fetchall()
            
            # Convert to dict for JSON response
            project_dict = dict(project._mapping) if project else None
            plots_list = [dict(p._mapping) for p in plots]
            
            return jsonify({
                'project': project_dict,
                'plots': plots_list
            })
        except Exception as e:
            print(f"Debug error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        status = {
            'database': 'connected' if db_session else 'disconnected',
            'app': 'running'
        }
        return jsonify(status)
    
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            db_session.remove()
    
    return app

if __name__ == '__main__':
    app = create_app()
    print("Starting Nirmaan.AI server...")
    print("Health check: http://localhost:5000/api/health")
    print("Main interface: http://localhost:5000")
    app.run(debug=True, port=5000)