from flask import Flask
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Add CORS and CSP headers to allow fetch requests
    @app.after_request
    def after_request(response):
        # Add CORS headers
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        
        # Add CSP headers that allow same-origin fetch requests
        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' http://127.0.0.1:8080 http://localhost:8080; "
            "frame-src 'self';"
        )
        response.headers.add('Content-Security-Policy', csp_policy)
        
        return response
    
    from app.routes import main_blueprint
    app.register_blueprint(main_blueprint)
    
    return app