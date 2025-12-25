from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from utils.db_helper import get_db_connection
import pymysql
import uuid
from datetime import datetime, timezone

events = Blueprint('events', __name__)

def _get_user_id(email):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cursor.fetchone()
        return row['id'] if row else None
    finally:
        cursor.close()
        conn.close()

def _get_user_role(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT role FROM user_roles WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        return row['role'] if row else 'user'
    finally:
        cursor.close()
        conn.close()

def _is_admin(user_id):
    return _get_user_role(user_id) == 'admin'

def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def _to_iso(dt):
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + 'Z'

def _ensure_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id VARCHAR(64) PRIMARY KEY,
              title VARCHAR(255) NOT NULL,
              type VARCHAR(100) NOT NULL,
              starts_at DATETIME NOT NULL,
              host VARCHAR(255) NOT NULL,
              status ENUM('upcoming','past') NOT NULL,
              capacity INT DEFAULT NULL,
              created_by INT NOT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_rsvps (
              id INT AUTO_INCREMENT PRIMARY KEY,
              event_id VARCHAR(64) NOT NULL,
              user_id INT NOT NULL,
              status ENUM('going') NOT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY unique_rsvp (event_id, user_id)
            )
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

try:
    _ensure_tables()
except Exception:
    pass

def _event_row_to_json(row):
    return {
        'id': row['id'],
        'title': row['title'],
        'type': row['type'],
        'startsAt': _to_iso(row['starts_at']),
        'host': row['host'],
        'status': row['status'],
        'capacity': row['capacity'],
        'createdBy': row['created_by'],
        'createdAt': _to_iso(row['created_at']),
        'updatedAt': _to_iso(row['updated_at']),
    }

@events.route('/', methods=['GET'])
def list_events():
    status = request.args.get('status', 'upcoming')
    if status not in ['upcoming', 'past']:
        return jsonify({'error': 'Invalid status'}), 400
    limit = request.args.get('limit', '20')
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20
    cursor_param = request.args.get('cursor')
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        params = [status]
        where_cursor = ""
        if cursor_param:
            if '|' in cursor_param:
                cid, cdate = cursor_param.split('|', 1)
                cdt = _parse_iso(cdate)
            else:
                cid = cursor_param
                cur.execute("SELECT starts_at FROM events WHERE id = %s", (cid,))
                r = cur.fetchone()
                cdt = r['starts_at'] if r else None
            if cdt:
                where_cursor = " AND (starts_at < %s OR (starts_at = %s AND id < %s))"
                params.extend([cdt, cdt, cid])
        q = (
            "SELECT id, title, type, starts_at, host, status, capacity, created_by, created_at, updated_at "
            "FROM events WHERE status = %s" + where_cursor +
            " ORDER BY starts_at DESC, id DESC LIMIT %s"
        )
        params.append(limit)
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
        items = [_event_row_to_json(r) for r in rows]
        next_cursor = None
        if len(rows) == limit:
            last = rows[-1]
            next_cursor = f"{last['id']}|{_to_iso(last['starts_at'])}"
        return jsonify({'items': items, 'nextCursor': next_cursor}), 200
    finally:
        cur.close()
        conn.close()

@events.route('/<string:event_id>', methods=['GET'])
def get_event(event_id):
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT id, title, type, starts_at, host, status, capacity, created_by, created_at, updated_at "
            "FROM events WHERE id = %s",
            (event_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(_event_row_to_json(row)), 200
    finally:
        cur.close()
        conn.close()

@events.route('/', methods=['POST'])
@jwt_required()
def create_event():
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json or {}
    title = data.get('title')
    etype = data.get('type')
    starts_at_raw = data.get('startsAt')
    host = data.get('host')
    capacity = data.get('capacity')
    if not title or not etype or not host or not starts_at_raw:
        return jsonify({'error': 'Invalid payload'}), 400
    try:
        if capacity is not None:
            capacity = int(capacity)
            if capacity < 0:
                return jsonify({'error': 'Invalid payload'}), 400
    except Exception:
        return jsonify({'error': 'Invalid payload'}), 400
    starts_at = _parse_iso(starts_at_raw)
    if not isinstance(starts_at, datetime):
        return jsonify({'error': 'Invalid payload'}), 400
    status = 'upcoming' if starts_at > datetime.utcnow() else 'past'
    eid = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            "INSERT INTO events (id, title, type, starts_at, host, status, capacity, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (eid, title, etype, starts_at, host, status, capacity, user_id)
        )
        conn.commit()
        cur.execute(
            "SELECT id, title, type, starts_at, host, status, capacity, created_by, created_at, updated_at "
            "FROM events WHERE id = %s",
            (eid,)
        )
        row = cur.fetchone()
        return jsonify(_event_row_to_json(row)), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Server error'}), 500
    finally:
        cur.close()
        conn.close()

@events.route('/<string:event_id>', methods=['PATCH'])
@jwt_required()
def update_event(event_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json or {}
    fields = []
    values = []
    if 'title' in data:
        fields.append("title = %s")
        values.append(data['title'])
    if 'type' in data:
        fields.append("type = %s")
        values.append(data['type'])
    if 'startsAt' in data:
        dt = _parse_iso(data['startsAt'])
        if not isinstance(dt, datetime):
            return jsonify({'error': 'Invalid payload'}), 400
        fields.append("starts_at = %s")
        values.append(dt)
        if 'status' not in data:
            fields.append("status = %s")
            values.append('upcoming' if dt > datetime.utcnow() else 'past')
    if 'host' in data:
        fields.append("host = %s")
        values.append(data['host'])
    if 'status' in data:
        if data['status'] not in ['upcoming', 'past']:
            return jsonify({'error': 'Invalid payload'}), 400
        fields.append("status = %s")
        values.append(data['status'])
    if 'capacity' in data:
        try:
            cap = data['capacity']
            cap = int(cap) if cap is not None else None
            if cap is not None and cap < 0:
                return jsonify({'error': 'Invalid payload'}), 400
        except Exception:
            return jsonify({'error': 'Invalid payload'}), 400
        fields.append("capacity = %s")
        values.append(cap)
    if not fields:
        return jsonify({'error': 'Invalid payload'}), 400
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        q = "UPDATE events SET " + ", ".join(fields) + " WHERE id = %s"
        values.append(event_id)
        cur.execute(q, tuple(values))
        conn.commit()
        cur.execute(
            "SELECT id, title, type, starts_at, host, status, capacity, created_by, created_at, updated_at "
            "FROM events WHERE id = %s",
            (event_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(_event_row_to_json(row)), 200
    finally:
        cur.close()
        conn.close()

@events.route('/<string:event_id>', methods=['DELETE'])
@jwt_required()
def delete_event(event_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM event_rsvps WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        conn.commit()
        return '', 204
    finally:
        cur.close()
        conn.close()

@events.route('/<string:event_id>/rsvp', methods=['POST'])
@jwt_required()
def create_rsvp(event_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json or {}
    status = data.get('status')
    if status != 'going':
        return jsonify({'error': 'Invalid payload'}), 400
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("SELECT id, capacity, status FROM events WHERE id = %s", (event_id,))
        ev = cur.fetchone()
        if not ev:
            return jsonify({'error': 'Not found'}), 404
        if ev['status'] == 'past':
            return jsonify({'error': 'Invalid payload'}), 400
        cur.execute("SELECT id FROM event_rsvps WHERE event_id = %s AND user_id = %s", (event_id, user_id))
        existing = cur.fetchone()
        if existing:
            return jsonify({'error': 'Conflict'}), 409
        if ev['capacity'] is not None:
            cur.execute("SELECT COUNT(*) AS c FROM event_rsvps WHERE event_id = %s", (event_id,))
            cnt = cur.fetchone()['c']
            if cnt >= ev['capacity']:
                return jsonify({'error': 'Conflict'}), 409
        cur2 = conn.cursor()
        cur2.execute(
            "INSERT INTO event_rsvps (event_id, user_id, status) VALUES (%s, %s, %s)",
            (event_id, user_id, 'going')
        )
        conn.commit()
        return jsonify({'eventId': event_id, 'userId': user_id, 'status': 'going'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Server error'}), 500
    finally:
        cur.close()
        conn.close()

@events.route('/<string:event_id>/rsvp', methods=['DELETE'])
@jwt_required()
def delete_rsvp(event_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM event_rsvps WHERE event_id = %s AND user_id = %s", (event_id, user_id))
        conn.commit()
        return '', 204
    finally:
        cur.close()
        conn.close()
