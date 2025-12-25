from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from utils.db_helper import get_db_connection
import pymysql

me = Blueprint('me', __name__)

def _event_row_to_json(row):
    return {
        'id': row['id'],
        'title': row['title'],
        'type': row['type'],
        'startsAt': row['starts_at'].replace(microsecond=0).isoformat() + 'Z' if row['starts_at'] else None,
        'host': row['host'],
        'status': row['status'],
        'capacity': row['capacity'],
        'createdBy': row['created_by'],
        'createdAt': row['created_at'].replace(microsecond=0).isoformat() + 'Z' if row['created_at'] else None,
        'updatedAt': row['updated_at'].replace(microsecond=0).isoformat() + 'Z' if row['updated_at'] else None,
    }

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

@me.route('/rsvps', methods=['GET'])
@jwt_required()
def list_my_rsvps():
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    limit = request.args.get('limit', '50')
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 50
    cursor_param = request.args.get('cursor')
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        params = [user_id]
        where_cursor = ""
        if cursor_param:
            where_cursor = " AND r.id < %s"
            params.append(cursor_param)
        q = (
            "SELECT r.id AS rsvp_id, r.event_id, r.status, r.created_at AS rsvp_created_at, "
            "e.id, e.title, e.type, e.starts_at, e.host, e.status, e.capacity, e.created_by, e.created_at, e.updated_at "
            "FROM event_rsvps r JOIN events e ON e.id = r.event_id "
            "WHERE r.user_id = %s" + where_cursor +
            " ORDER BY r.id DESC LIMIT %s"
        )
        params.append(limit)
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
        items = [{'event': _event_row_to_json(r), 'status': r['status']} for r in rows]
        next_cursor = None
        if len(rows) == limit:
            last = rows[-1]
            next_cursor = str(last['rsvp_id'])
        return jsonify({'items': items, 'nextCursor': next_cursor}), 200
    finally:
        cur.close()
        conn.close()
