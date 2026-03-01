from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app, g
import jwt
from passlib.hash import bcrypt

from models.base import db_session
from models.auth import User, Role

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _get_secret_key():
    # Reuse Flask SECRET_KEY if set; otherwise fall back to env
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        secret = current_app.config.get('JWT_SECRET_KEY') or 'changeme-in-prod'
    return secret


def generate_token(user: User, expires_in_minutes: int = 60):
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role_id": user.role_id,
        "exp": datetime.utcnow() + timedelta(minutes=expires_in_minutes),
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, _get_secret_key(), algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


@bp.route('/login', methods=['POST'])
def login():
    """
    Basic login endpoint (NFR-40 starter).

    Body:
    - email
    - password

    Returns JWT token and basic user info. This is optional for now – you can
    continue using the system user for MVP flows.
    """
    try:
        data = request.json or {}
        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not email or not password:
            return jsonify({'error': 'email and password are required'}), 400

        user = User.get_by_email(email)
        if not user or user.status != 'active':
            return jsonify({'error': 'Invalid credentials'}), 401

        # For now, accept either bcrypt-hashed or plain 'no-auth-mvp'
        valid = False
        if user.password_hash == 'demo123':
            valid = (password == 'demo123')
        else:
            try:
                valid = bcrypt.verify(password, user.password_hash)
            except Exception:
                valid = False

        if not valid:
            return jsonify({'error': 'Invalid credentials'}), 401

        token = generate_token(user)
        return jsonify({
            'token': token,
            'user': {
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email,
                'role_id': user.role_id,
            }
        })
    except Exception as e:
        db_session.rollback()
        return jsonify({'error': str(e)}), 500


def require_auth(roles=None):
    """
    Decorator factory to protect endpoints with optional role-based access.
    Usage:
        @require_auth()
        def some_route(...):
            ...

        @require_auth(roles=['admin'])
    """
    roles = roles or []

    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({'error': 'Authorization header missing or invalid'}), 401

            token = auth_header.split(' ', 1)[1].strip()
            try:
                payload = jwt.decode(token, _get_secret_key(), algorithms=['HS256'])
                user_id = int(payload.get('sub'))
                user = db_session.query(User).filter(User.id == user_id).first()
                if not user or user.status != 'active':
                    return jsonify({'error': 'User disabled or not found'}), 401

                g.current_user = user

                if roles:
                    role = db_session.query(Role).filter(Role.id == user.role_id).first()
                    role_name = (role.name or '').lower() if role else ''
                    if role_name not in [r.lower() for r in roles]:
                        return jsonify({'error': 'Insufficient permissions'}), 403
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except Exception as e:
                return jsonify({'error': f'Invalid token: {e}'}), 401

            return fn(*args, **kwargs)

        return wrapper

    return decorator

