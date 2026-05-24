from app import create_app, db

# Create the application instance
app = create_app()

# Ensure tables are created in production environments (like Render)
with app.app_context():
    try:
        db.create_all()
        print("Database tables verified/created successfully.")
    except Exception as e:
        print(f"Failed to auto-create database tables: {e}")
        # We don't raise here, so the app can at least start and serve the 500 page or health check

if __name__ == "__main__":
    app.run()
