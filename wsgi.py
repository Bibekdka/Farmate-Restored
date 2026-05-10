import os
from app import create_app, db

# Create the application instance
app = create_app()

# Ensure tables are created in production environments (like Render)
# FUTURE EDITING: For larger databases, use 'flask db upgrade' instead of 'create_all'.
# with app.app_context():
#     db.create_all()

if __name__ == "__main__":
    app.run()
