from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from utils.db_helper import get_db_connection
import pymysql

import os
import google.generativeai as genai

auth = Blueprint('auth', __name__)

@auth.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not all([name, email, password]):
        return jsonify({'error': 'All fields are required'}), 400

    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'error': 'Email already registered'}), 409

        hashed_password = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
            (name, email, hashed_password)
        )
        conn.commit()
        return jsonify({'message': 'Registration successful 🌿'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Registration failed'}), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()

@auth.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({'error': 'Email and password required'}), 400

    conn = get_db_connection()
    cursor = None
    try:
        # Use DictCursor so we can reference fields by name
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        conn.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid email or password'}), 401

    token = create_access_token(identity=email)
    return jsonify({
        'message': 'Login successful 🌱',
        'token': token,
        'user': {'name': user['name'], 'email': user['email']}
    }), 200

@auth.route('/affirmation', methods=['GET'])
def daily_affirmation():
    fallback_affirmation = "I am worthy of all the good things life has to offer."
    api_key = os.getenv('GOOGLE_API_KEY')

    # If no key, return a safe fallback instead of 500
    if not api_key:
        return jsonify({'affirmation': fallback_affirmation, 'source': 'fallback'}), 200

    try:
        genai.configure(api_key=api_key)
        # Try 2.5 flash; gracefully fallback to 1.5 flash if unavailable
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception:
            model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = (
            "Return one short motivational affirmation (max 2 lines). "
            "Plain text only, no quotes or emojis."
        )
        response = model.generate_content(prompt)

        # Extract text robustly across SDK versions
        text = (getattr(response, 'text', '') or '').strip()
        if not text and getattr(response, 'candidates', None):
            candidate = response.candidates[0]
            content = getattr(candidate, 'content', None)
            parts = getattr(content, 'parts', None)
            if parts and hasattr(parts[0], 'text'):
                text = parts[0].text.strip()

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        affirmation = "\n".join(lines[:2]) if lines else fallback_affirmation

        return jsonify({'affirmation': affirmation, 'source': 'gemini'}), 200
    except Exception:
        # Any error returns a friendly fallback instead of 500
        return jsonify({'affirmation': fallback_affirmation, 'source': 'fallback'}), 200

@auth.route('/me', methods=['GET'])
@jwt_required()
def me():
    identity = get_jwt_identity()  # email set in create_access_token(identity=email)
    conn = get_db_connection()
    cursor = None
    try:
        # Use DictCursor for predictable key-based access
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Fetch user by email
        cursor.execute("SELECT id, name, email FROM users WHERE email = %s", (identity,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Fetch role; default to 'member' if none
        cursor.execute("SELECT role FROM user_roles WHERE user_id = %s", (user['id'],))
        role_row = cursor.fetchone()
        if role_row:
            role = role_row['role'] if isinstance(role_row, dict) else role_row[0]
        else:
            role = 'member'

        return jsonify({
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'role': role
        }), 200
    finally:
        if cursor:
            cursor.close()
        conn.close()
