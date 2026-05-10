import datetime
from extensions import db

class FarmRecord(db.Model):
    """Stores financial records (Income/Expense) for the farm."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.date.today)
    activity_type = db.Column(db.String(50))
    category = db.Column(db.String(50))
    expense_type = db.Column(db.String(50))  # Fuel, Labour, Food, Transportation, Misc
    amount = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(200))

class Note(db.Model):
    """Daily logs and quick notes recorded by the farmer."""
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

class Crop(db.Model):
    """Information about crops currently planted or planned."""
    id = db.Column(db.Integer, primary_key=True)
    crop_name = db.Column(db.String(100), nullable=False)
    variety = db.Column(db.String(100))
    season = db.Column(db.String(50))
    area = db.Column(db.String(100))
    sowing_date = db.Column(db.Date)
    expected_harvest = db.Column(db.Date)
    status = db.Column(db.String(50), default='Active')
    notes = db.Column(db.String(500))

class Yield(db.Model):
    """Harvest records for specific crops."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.date.today)
    crop_id = db.Column(db.Integer, db.ForeignKey('crop.id'))
    yield_value = db.Column(db.Float)
    unit = db.Column(db.String(20))
    yield_in_kg = db.Column(db.Float)
    notes = db.Column(db.String(200))
    crop = db.relationship('Crop', backref='yields')

class DiseaseLog(db.Model):
    """Records of pest or disease outbreaks and treatments."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.date.today)
    crop_id = db.Column(db.Integer, db.ForeignKey('crop.id'))
    disease_name = db.Column(db.String(100))
    severity = db.Column(db.String(20))
    affected_area = db.Column(db.String(100))
    treatment = db.Column(db.String(500))
    notes = db.Column(db.String(200))
    crop = db.relationship('Crop', backref='diseases')

class PestLog(db.Model):
    """Log of pest monitoring values compared against ETL thresholds."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.date.today)
    crop_name = db.Column(db.String(50))
    pest_name = db.Column(db.String(50))
    value = db.Column(db.Float)
    alert_status = db.Column(db.String(20)) # SAFE, ALERT, WARNING
    notes = db.Column(db.String(200))

class Reminder(db.Model):
    """Task reminders and agricultural schedule items."""
    # CATEGORIZATION: Added task_type for better filtering (Sowing, Pruning, Fertilizer, etc.)
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    task_type = db.Column(db.String(50), default='General') # Sowing, Pruning, Fertilizer, Harvest, Misc
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(500))
    priority = db.Column(db.String(20), default='Normal')
    completed = db.Column(db.Boolean, default=False)

class WeatherLog(db.Model):
    """Historical weather records for the farm location."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    max_temp = db.Column(db.Float)
    rainfall = db.Column(db.Float)
    description = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

class Inventory(db.Model):
    """Tracks supplies like seeds, fertilizers, and pesticides."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False) # Seed, Fertilizer, Pesticide, Tool, etc.
    quantity = db.Column(db.Float, default=0.0)
    unit = db.Column(db.String(20)) # kg, Liters, Bags, Packets
    min_stock_level = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    notes = db.Column(db.String(200))

class InventoryTransaction(db.Model):
    """Tracks every time stock is added or used."""
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.date.today)
    transaction_type = db.Column(db.String(20)) # Purchase, Usage, Waste, Correction
    quantity = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(200))
    inventory = db.relationship('Inventory', backref='transactions')
