import os
from datetime import timedelta

class Config:
    """Base configuration"""
    basedir = os.path.abspath(os.path.dirname(__file__))
    # Ensure instance folder exists
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
        
    uri = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(instance_path, 'farm_data.db'))
    if uri and (uri.startswith("postgres://") or uri.startswith("postgresql://")):
        # Handle the legacy postgres:// scheme for SQLAlchemy 1.4+
        uri = uri.replace("postgres://", "postgresql+psycopg://", 1)
        if not uri.startswith("postgresql+psycopg://"):
            uri = uri.replace("postgresql://", "postgresql+psycopg://", 1)
        
        # Ensure SSL is enabled for Neon/Managed DBs
        if "?" not in uri:
            uri += "?sslmode=require"
        elif "sslmode=" not in uri:
            uri += "&sslmode=require"
    
    SQLALCHEMY_DATABASE_URI = uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
