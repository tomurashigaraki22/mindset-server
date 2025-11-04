from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from utils.db_helper import get_db_connection
import pymysql
import stripe
from dotenv import load_dotenv
from datetime import timedelta, datetime
import requests

import os
load_dotenv()
import google.generativeai as genai

auth = Blueprint('auth', __name__)
PAYPAL_CLIENT_ID = "AU4cjGgjCzRvANikWUNe_4U-km4mK1PodmfLnxzipXh49Rubk4Au89h9TbLirHmeY5NMrQmVqtJ99ioN"
PAYPAL_SECRET = "EPBa65CjR833nRpu5vJEBLmrvdJT8_uaeCv97q0LxEvo8vI0PIk58i_w1fLvUt7UIDkBe-jaw4fZx9Jk"
PAYPAL_API = "https://api-m.sandbox.paypal.com"  # Switch to live API for production
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')



@auth.route('/create-payment-intent-10', methods=['POST'])
def create_payment_intent_10():
    try:
        # Create a PaymentIntent for $10 (1000 cents)
        payment_intent = stripe.PaymentIntent.create(
            amount=1000,  # Amount in cents ($10.00)
            currency='usd'
        )

        # Return the client secret to the frontend
        return jsonify({
            'client_secret': payment_intent.client_secret
        }), 200

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@auth.route('/create-payment-intent-18', methods=['POST'])
def create_payment_intent_18():
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=1800,
            currency='usd'
        )

        return jsonify({
            'client_secret': payment_intent.client_secret
        }), 200

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@auth.route('/get-publishable-key', methods=['GET'])
def get_publishable_key():
    publishable_key = os.getenv('SANDBOX_PUBLISHABLE_KEY_STRIPE')

    if not publishable_key:
        return jsonify({'error': 'Publishable key not found'}), 404

    return jsonify({'publishable_key': publishable_key}), 200



@auth.route('/create-paypal-order', methods=['POST'])
@jwt_required()
def create_paypal_order():
    """Create a PayPal order for the chosen subscription."""
    user_email = get_jwt_identity()
    data = request.json
    subscription_type = data.get('subscription_type')

    if subscription_type not in ['pro', 'premium']:
        return jsonify({'error': 'Invalid subscription type'}), 400

    amount = 10.00 if subscription_type == 'pro' else 18.00

    try:
        # Get OAuth2 token from PayPal
        auth_response = requests.post(
            f"{PAYPAL_API}/v1/oauth2/token",
            headers={'Accept': 'application/json', 'Accept-Language': 'en_US'},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={'grant_type': 'client_credentials'}
        )
        access_token = auth_response.json().get('access_token')

        # Create PayPal order
        order_payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": "USD",
                        "value": str(amount)
                    },
                    "description": f"{subscription_type.capitalize()} Plan Subscription"
                }
            ],
            "application_context": {
                "return_url": "https://example.com/return",
                "cancel_url": "https://example.com/cancel"
            }
        }

        order_response = requests.post(
            f"{PAYPAL_API}/v2/checkout/orders",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            },
            json=order_payload
        )

        return jsonify(order_response.json()), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth.route('/capture-paypal-order', methods=['POST'])
@jwt_required()
def capture_paypal_order():
    """Capture the PayPal order and update subscription."""
    user_email = get_jwt_identity()
    data = request.json
    order_id = data.get('orderID')

    if not order_id:
        return jsonify({'error': 'Missing orderID'}), 400

    try:
        # Get PayPal access token again
        auth_response = requests.post(
            f"{PAYPAL_API}/v1/oauth2/token",
            headers={'Accept': 'application/json', 'Accept-Language': 'en_US'},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={'grant_type': 'client_credentials'}
        )
        access_token = auth_response.json().get('access_token')

        # Capture order
        capture_response = requests.post(
            f"{PAYPAL_API}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
        )
        capture_data = capture_response.json()

        # Extract amount and description safely
        purchase = capture_data.get("purchase_units", [{}])[0]
        amount_value = float(purchase.get("payments", {}).get("captures", [{}])[0].get("amount", {}).get("value", 0))
        description = purchase.get("description", "")
        subscription_type = 'pro' if 'Pro' in description else 'premium'

        # Find user ID
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        user_id = user['id']

        # Update or insert subscription
        cursor.execute("SELECT * FROM subscriptions WHERE user_id = %s", (user_id,))
        sub = cursor.fetchone()

        new_expiry = datetime.utcnow() + timedelta(days=30)
        if sub:
            cursor.execute("""
                UPDATE subscriptions 
                SET subscription_type = %s, amount = %s, expires_at = %s 
                WHERE user_id = %s
            """, (subscription_type, amount_value, new_expiry, user_id))
        else:
            cursor.execute("""
                INSERT INTO subscriptions (user_id, subscription_type, amount, expires_at)
                VALUES (%s, %s, %s, %s)
            """, (user_id, subscription_type, amount_value, new_expiry))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            'message': 'Subscription updated successfully!',
            'subscription_type': subscription_type,
            'amount': amount_value,
            'expires_at': new_expiry.isoformat()
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500





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

    token = create_access_token(identity=email, expires_delta=timedelta(days=7))
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
