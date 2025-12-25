from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from routes.auth_routes import auth
from routes.community_routes import community
from routes.events_routes import events
from routes.me_routes import me

app = Flask(__name__)
CORS(app)

app.config['JWT_SECRET_KEY'] = 'mindset-app-tyshii'
jwt = JWTManager(app)

app.register_blueprint(auth, url_prefix='/auth')
app.register_blueprint(community, url_prefix='/community')
app.register_blueprint(events, url_prefix='/events')
app.register_blueprint(me, url_prefix='/me')

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=1345, use_reloader=True)
