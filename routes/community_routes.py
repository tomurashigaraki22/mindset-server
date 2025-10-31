from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from utils.db_helper import get_db_connection
import pymysql

community = Blueprint('community', __name__)

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
        return row['role'] if row else 'member'
    finally:
        cursor.close()
        conn.close()

def _is_mod_or_admin(user_id):
    role = _get_user_role(user_id)
    return role in ('moderator', 'admin')

@community.route('/channels', methods=['GET'])
def list_channels():
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT id, name, description, created_at FROM channels ORDER BY created_at DESC")
        channels = cursor.fetchall()
        return jsonify({'channels': channels}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/channels', methods=['POST'])
@jwt_required()
def create_channel():
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_mod_or_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json or {}
    name = data.get('name')
    description = data.get('description', '')

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO channels (name, description, created_by) VALUES (%s, %s, %s)",
            (name, description, user_id)
        )
        conn.commit()
        return jsonify({'message': 'Channel created'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Could not create channel'}), 500
    finally:
        cursor.close()
        conn.close()
@community.route('/channels/<int:channel_id>/posts', methods=['GET'])
@jwt_required()
def list_posts(channel_id):
    identity = get_jwt_identity()  # Get the email of the logged-in user
    user_id = _get_user_id(identity)  # Get the user_id from the email
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        # Fetch all posts for the specified channel with likes and dislikes counts
        cursor.execute(
            "SELECT id, title, body, user_id, created_at, likes, dislikes FROM posts "
            "WHERE channel_id = %s AND is_deleted = 0 ORDER BY created_at DESC",
            (channel_id,)
        )
        posts = cursor.fetchall()

        # Fetch author information for all posts
        user_ids = list({p['user_id'] for p in posts})
        authors = {}
        if user_ids:
            placeholders = ','.join(['%s'] * len(user_ids))
            cursor.execute(
                f"SELECT id, name, email FROM users WHERE id IN ({placeholders})",
                tuple(user_ids)
            )
            for row in cursor.fetchall():
                authors[row['id']] = {
                    'id': row['id'],
                    'name': row['name'],
                    'email': row['email'],
                }

        # Fetch the user's own reaction to each post (like, dislike, or none)
        user_reactions = {}
        post_ids = list({p['id'] for p in posts})
        if post_ids:  # Ensure we have posts to check for the user's reactions
            placeholders = ','.join(['%s'] * len(post_ids))  # Create placeholders for post_ids
            cursor.execute(
                f"SELECT post_id, reaction FROM likes WHERE user_id = %s AND post_id IN ({placeholders})",
                [user_id] + post_ids  # Pass user_id first, then post_ids as separate parameters
            )
            for row in cursor.fetchall():
                user_reactions[row['post_id']] = row['reaction']

        # Enrich the posts with author, reactions, and user's own reaction
        enriched_posts = []
        for post in posts:
            enriched_post = {
                **post,
                'author': authors.get(post['user_id'], None),
                'user_reaction': user_reactions.get(str(post['id']), None)  # user's own reaction (like, dislike, or None)
            }
            enriched_posts.append(enriched_post)

        return jsonify({'posts': enriched_posts}), 200

    finally:
        cursor.close()
        conn.close()



@community.route('/channels/<int:channel_id>/posts', methods=['POST'])
@jwt_required()
def create_post(channel_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    title = data.get('title')
    body = data.get('body')

    if not all([title, body]):
        return jsonify({'error': 'Title and body required'}), 400

    # Prevent posting to locked channels by checking channel-level locks if needed
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO posts (channel_id, user_id, title, body) VALUES (%s, %s, %s, %s)",
            (channel_id, user_id, title, body)
        )
        conn.commit()
        return jsonify({'message': 'Post created'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Could not create post'}), 500
    finally:
        cursor.close()
        conn.close()

@community.route('/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT id, channel_id, user_id, title, body, is_locked, created_at "
            "FROM posts WHERE id = %s AND is_deleted = 0",
            (post_id,)
        )
        post = cursor.fetchone()
        if not post:
            return jsonify({'error': 'Not found'}), 404

        # Attach author for the post
        cursor.execute("SELECT id, name, email FROM users WHERE id = %s", (post['user_id'],))
        author = cursor.fetchone()
        post['author'] = (
            {'id': author['id'], 'name': author['name'], 'email': author['email']}
            if author else None
        )

        cursor.execute(
            "SELECT id, user_id, body, created_at FROM comments "
            "WHERE post_id = %s AND is_deleted = 0 ORDER BY created_at ASC",
            (post_id,)
        )
        comments = cursor.fetchall()
        return jsonify({'post': post, 'comments': comments}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/posts/<int:post_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    body = data.get('body')
    if not body:
        return jsonify({'error': 'Body is required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT is_locked FROM posts WHERE id = %s AND is_deleted = 0",
            (post_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Post not found'}), 404
        if row['is_locked'] == 1:
            return jsonify({'error': 'Post is locked'}), 403

        cursor = conn.cursor()  # plain cursor for insert
        cursor.execute(
            "INSERT INTO comments (post_id, user_id, body) VALUES (%s, %s, %s)",
            (post_id, user_id, body)
        )
        conn.commit()
        return jsonify({'message': 'Comment added'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Could not add comment'}), 500
    finally:
        cursor.close()
        conn.close()

@community.route('/reports', methods=['POST'])
@jwt_required()
def report_content():
    identity = get_jwt_identity()
    reporter_id = _get_user_id(identity)
    if not reporter_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    entity_type = data.get('entity_type')  # 'post' or 'comment'
    entity_id = data.get('entity_id')
    reason = data.get('reason', '')

    if entity_type not in ('post', 'comment') or not entity_id:
        return jsonify({'error': 'Invalid report'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO reports (entity_type, entity_id, reporter_id, reason) VALUES (%s, %s, %s, %s)",
            (entity_type, entity_id, reporter_id, reason)
        )
        conn.commit()
        return jsonify({'message': 'Report submitted'}), 201
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Could not submit report'}), 500
    finally:
        cursor.close()
        conn.close()

@community.route('/mod/posts/<int:post_id>/delete', methods=['POST'])
@jwt_required()
def mod_delete_post(post_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_mod_or_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE posts SET is_deleted = 1 WHERE id = %s", (post_id,))
        conn.commit()
        return jsonify({'message': 'Post deleted'}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/mod/comments/<int:comment_id>/delete', methods=['POST'])
@jwt_required()
def mod_delete_comment(comment_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_mod_or_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE comments SET is_deleted = 1 WHERE id = %s", (comment_id,))
        conn.commit()
        return jsonify({'message': 'Comment deleted'}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/mod/posts/<int:post_id>/lock', methods=['POST'])
@jwt_required()
def mod_lock_post(post_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_mod_or_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE posts SET is_locked = 1 WHERE id = %s", (post_id,))
        conn.commit()
        return jsonify({'message': 'Post locked'}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/mod/reports/<int:report_id>/resolve', methods=['POST'])
@jwt_required()
def mod_resolve_report(report_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id or not _is_mod_or_admin(user_id):
        return jsonify({'error': 'Forbidden'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
        conn.commit()
        return jsonify({'message': 'Report resolved'}), 200
    finally:
        cursor.close()
        conn.close()


@community.route('/posts/<int:post_id>/react', methods=['POST'])
@jwt_required()
def react_to_post(post_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    reaction = data.get('reaction')  # 1 for like, -1 for dislike

    if reaction not in [1, -1]:
        return jsonify({'error': 'Invalid reaction'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the user has already reacted to the post
        cursor.execute(
            "SELECT id, reaction FROM likes WHERE post_id = %s AND user_id = %s",
            (post_id, user_id)
        )
        existing_reaction = cursor.fetchone()

        if existing_reaction:
            # If a reaction exists, update it
            old_reaction = existing_reaction['reaction']
            if old_reaction == 1 and reaction == -1:
                # If the user was previously liking and now dislikes
                cursor.execute(
                    "UPDATE posts SET likes = likes - 1, dislikes = dislikes + 1 WHERE id = %s",
                    (post_id,)
                )
            elif old_reaction == -1 and reaction == 1:
                # If the user was previously disliking and now likes
                cursor.execute(
                    "UPDATE posts SET likes = likes + 1, dislikes = dislikes - 1 WHERE id = %s",
                    (post_id,)
                )
            
            cursor.execute(
                "UPDATE likes SET reaction = %s WHERE id = %s",
                (reaction, existing_reaction['id'])
            )

        else:
            # If no reaction exists, insert a new record
            cursor.execute(
                "INSERT INTO likes (post_id, user_id, reaction) VALUES (%s, %s, %s)",
                (post_id, user_id, reaction)
            )
            if reaction == 1:
                cursor.execute(
                    "UPDATE posts SET likes = likes + 1 WHERE id = %s",
                    (post_id,)
                )
            elif reaction == -1:
                cursor.execute(
                    "UPDATE posts SET dislikes = dislikes + 1 WHERE id = %s",
                    (post_id,)
                )

        conn.commit()
        return jsonify({'message': 'Reaction updated'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': 'Could not update reaction', "error string": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@community.route('/posts/<int:post_id>/reactions', methods=['GET'])
def get_post_reactions(post_id):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT reaction, COUNT(*) AS count FROM likes WHERE post_id = %s GROUP BY reaction",
            (post_id,)
        )
        reactions = cursor.fetchall()

        # Prepare response for likes and dislikes count
        reaction_count = {
            'likes': 0,
            'dislikes': 0
        }
        for reaction in reactions:
            if reaction['reaction'] == 1:
                reaction_count['likes'] = reaction['count']
            elif reaction['reaction'] == -1:
                reaction_count['dislikes'] = reaction['count']

        return jsonify({'reactions': reaction_count}), 200
    finally:
        cursor.close()
        conn.close()

@community.route('/posts/<int:post_id>/my_reaction', methods=['GET'])
@jwt_required()
def get_user_reaction(post_id):
    identity = get_jwt_identity()
    user_id = _get_user_id(identity)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT reaction FROM likes WHERE post_id = %s AND user_id = %s",
            (post_id, user_id)
        )
        user_reaction = cursor.fetchone()

        if not user_reaction:
            return jsonify({'message': 'No reaction found'}), 404

        return jsonify({'reaction': user_reaction['reaction']}), 200
    finally:
        cursor.close()
        conn.close()
