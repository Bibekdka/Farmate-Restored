import os
import datetime
import logging
import subprocess
import sys
from pathlib import Path

# Third-party imports
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from sqlalchemy import func
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

# Local application imports
from extensions import db, migrate, csrf
from models import (
    FarmRecord, Note, Crop, Yield, DiseaseLog, 
    PestLog, Reminder, WeatherLog
)
from config import config
from ai_service import ai_advisor
from utils import (
    setup_logging, load_all_knowledge_bases, convert_to_kg, validate_date,
    validate_amount, validate_crop_id, validate_string, validate_category,
    FARM_LATITUDE, FARM_LONGITUDE, WMO_CODES, RECORDS_PER_PAGE
)
from services.weather_service import (
    get_weather_openmeteo, backfill_weather_history, get_current_weather_simple
)

# Load environment variables FIRST
load_dotenv()

def create_app(config_name=None):
    """
    Application factory pattern to create and configure the Flask app.
    FUTURE EDITING: This makes it easier to run tests with a different config.
    """
    app = Flask(__name__)
    
    if not config_name:
        config_name = os.environ.get('APP_ENV', 'development')
    
    app.config.from_object(config[config_name])
    
    # Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    # csrf.init_app(app) # Enable this if forms include CSRF tokens
    
    # Setup logging
    setup_logging(app)
    logger = logging.getLogger(__name__)
    
    # Security check
    if app.config['SECRET_KEY'] == 'dev-secret-key-change-in-production' and config_name == 'production':
        logger.critical("SECURITY: Using default SECRET_KEY in production!")
        if not os.environ.get('SKIP_SECURITY_CHECK'):
            raise RuntimeError("Must set SECRET_KEY environment variable in production")

    # Load Knowledge Data
    knowledge_bases = load_all_knowledge_bases()
    
    # Register context processors or global variables if needed
    @app.context_processor
    def inject_knowledge_bases():
        return dict(
            pest_etl=knowledge_bases['pest_etl'],
            pest_calendar=knowledge_bases['pest_calendar'],
            crop_calendar=knowledge_bases['crop_calendar'],
            turmeric_db=knowledge_bases['turmeric_data']
        )

    # --- ROUTES ---

    @app.route('/')
    def home():
        """Home/dashboard page with weather and recent activities."""
        backfill_weather_history()
        weather_data = get_weather_openmeteo()
        
        # Auto-archive today's weather
        if weather_data:
            today = datetime.date.today()
            if not WeatherLog.query.filter_by(date=today).first():
                try:
                    todays_weather = weather_data[0]
                    new_log = WeatherLog(
                        date=today,
                        max_temp=todays_weather['temp'],
                        rainfall=todays_weather['rain_prob'],
                        description=todays_weather['desc']
                    )
                    db.session.add(new_log)
                    db.session.commit()
                except Exception as e:
                    logger.error(f"Failed to archive weather: {e}")
                    db.session.rollback()
        
        recent_activities = FarmRecord.query.order_by(FarmRecord.date.desc()).limit(5).all()
        today_reminders = Reminder.query.filter_by(date=datetime.date.today(), completed=False).all()
        return render_template('index.html', weather=weather_data, activities=recent_activities, reminders=today_reminders)

    @app.route('/dashboard')
    def dashboard():
        """Main financial dashboard with aggregation and transaction history."""
        # OPTIMIZED: Use SQL Aggregation instead of fetching all records
        total_income = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Income').scalar() or 0
        total_expense = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Expense').scalar() or 0
        net_profit = total_income - total_expense
        
        # Transactions Table
        records = FarmRecord.query.order_by(FarmRecord.date.desc()).all()
        
        # Expense breakdown by type
        expense_breakdown_query = db.session.query(
            FarmRecord.expense_type, func.sum(FarmRecord.amount)
        ).filter(
            FarmRecord.category == 'Expense', 
            FarmRecord.expense_type != None
        ).group_by(FarmRecord.expense_type).all()
        
        expense_breakdown = {type_: amount for type_, amount in expense_breakdown_query}
        
        return render_template('dashboard.html', income=total_income, expense=total_expense, 
                              profit=net_profit, records=records, expense_breakdown=expense_breakdown)

    @app.route('/add_record', methods=['POST'])
    def add_record():
        """Add a new farm record with validation."""
        try:
            date_obj = validate_date(request.form.get('date'))
            if not date_obj: return redirect(url_for('dashboard'))
            
            activity = validate_string(request.form.get('activity'), min_len=2, max_len=100)
            category = validate_category(request.form.get('category'))
            amount = validate_amount(request.form.get('amount'))
            
            if not activity or not category or amount is None:
                return redirect(url_for('dashboard'))
            
            expense_types = request.form.getlist('expense_type')
            expense_type_str = ", ".join(expense_types) if expense_types else None
            
            new_record = FarmRecord(
                date=date_obj,
                activity_type=activity,
                category=category,
                expense_type=expense_type_str,
                amount=amount,
                description=validate_string(request.form.get('desc'), min_len=0, max_len=200, allow_empty=True)
            )
            db.session.add(new_record)
            db.session.commit()
            logger.info(f"Record created: {activity} - {amount} ({category})")
        except Exception as e:
            logger.error(f"Error adding record: {e}")
            db.session.rollback()
        
        return redirect(url_for('dashboard'))

    @app.route('/edit_record/<int:record_id>', methods=['GET', 'POST'])
    def edit_record(record_id):
        """Update an existing farm record."""
        record = FarmRecord.query.get_or_404(record_id)
        if request.method == 'POST':
            try:
                record.date = datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
                record.activity_type = request.form.get('activity')
                record.category = request.form.get('category')
                
                expense_types = request.form.getlist('expense_type')
                record.expense_type = ", ".join(expense_types) if expense_types else request.form.get('expense_type')
                
                record.amount = float(request.form.get('amount'))
                record.description = request.form.get('desc')
                db.session.commit()
                return redirect(url_for('dashboard'))
            except Exception as e:
                logger.error(f"Error editing record: {e}")
                db.session.rollback()
        return render_template('edit_record.html', record=record)

    @app.route('/delete_record/<int:record_id>', methods=['POST'])
    def delete_record(record_id):
        """Remove a farm record."""
        record = FarmRecord.query.get_or_404(record_id)
        db.session.delete(record)
        db.session.commit()
        return redirect(url_for('dashboard'))

    @app.route('/crops', methods=['GET', 'POST'])
    def crops():
        """Manage farm crops."""
        if request.method == 'POST':
            try:
                crop = Crop(
                    crop_name=request.form.get('crop_name'),
                    variety=request.form.get('variety'),
                    season=request.form.get('season'),
                    area=request.form.get('area'),
                    sowing_date=datetime.datetime.strptime(request.form.get('sowing_date'), '%Y-%m-%d').date() if request.form.get('sowing_date') else None,
                    expected_harvest=datetime.datetime.strptime(request.form.get('expected_harvest'), '%Y-%m-%d').date() if request.form.get('expected_harvest') else None,
                    notes=request.form.get('notes')
                )
                db.session.add(crop)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error adding crop: {e}")
                db.session.rollback()
            return redirect(url_for('crops'))
        all_crops = Crop.query.all()
        return render_template('crops.html', crops=all_crops)

    @app.route('/yield', methods=['GET', 'POST'])
    def yield_tracking():
        """Track crop harvests."""
        if request.method == 'POST':
            try:
                crop_id = request.form.get('crop_id')
                yield_value = float(request.form.get('yield_value'))
                unit = request.form.get('unit')
                yield_in_kg = convert_to_kg(yield_value, unit)
                yield_rec = Yield(
                    date=datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date(),
                    crop_id=crop_id,
                    yield_value=yield_value,
                    unit=unit,
                    yield_in_kg=yield_in_kg,
                    notes=request.form.get('notes')
                )
                db.session.add(yield_rec)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error adding yield: {e}")
                db.session.rollback()
            return redirect(url_for('yield_tracking'))
        crops_list = Crop.query.all()
        yields = Yield.query.all()
        return render_template('yield.html', crops=crops_list, yields=yields)

    @app.route('/disease_log', methods=['GET', 'POST'])
    def disease_log():
        """Monitor and record crop diseases."""
        if request.method == 'POST':
            try:
                disease = DiseaseLog(
                    date=datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date(),
                    crop_id=request.form.get('crop_id'),
                    disease_name=request.form.get('disease_name'),
                    severity=request.form.get('severity'),
                    affected_area=request.form.get('affected_area'),
                    treatment=request.form.get('treatment'),
                    notes=request.form.get('notes')
                )
                db.session.add(disease)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error adding disease log: {e}")
                db.session.rollback()
            return redirect(url_for('disease_log'))
        crops_list = Crop.query.all()
        diseases = DiseaseLog.query.order_by(DiseaseLog.date.desc()).all()
        return render_template('disease_log.html', crops=crops_list, diseases=diseases)

    @app.route('/reminders', methods=['GET', 'POST'])
    def reminders():
        """Task and schedule management."""
        if request.method == 'POST':
            try:
                reminder = Reminder(
                    date=datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date(),
                    title=request.form.get('title'),
                    description=request.form.get('description'),
                    priority=request.form.get('priority', 'Normal')
                )
                db.session.add(reminder)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error adding reminder: {e}")
                db.session.rollback()
            return redirect(url_for('reminders'))
        all_reminders = Reminder.query.order_by(Reminder.date.asc()).all()
        return render_template('reminders.html', reminders=all_reminders)

    @app.route('/reports')
    def reports():
        """Generate operational and financial summaries."""
        total_income = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Income').scalar() or 0
        total_expense = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Expense').scalar() or 0
        net_profit = total_income - total_expense
        
        # Monthly breakdown
        records = FarmRecord.query.all()
        monthly_data = {}
        activity_data = {}
        
        for record in records:
            month_key = record.date.strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = {'income': 0, 'expense': 0}
            if record.category == 'Income':
                monthly_data[month_key]['income'] += record.amount
            else:
                monthly_data[month_key]['expense'] += record.amount
        
        total_yield_kg = db.session.query(func.sum(Yield.yield_in_kg)).scalar() or 0
        disease_count = db.session.query(func.count(DiseaseLog.id)).scalar() or 0
        
        return render_template('reports.html', total_income=total_income, total_expense=total_expense,
                              net_profit=net_profit, monthly_data=monthly_data, activity_data=activity_data,
                              total_yield_kg=total_yield_kg, disease_count=disease_count)

    # --- API ENDPOINTS ---

    @app.route('/api/check-etl', methods=['POST'])
    def api_check_etl():
        """Evaluate pest monitoring values against Economic Threshold Levels (ETL)."""
        data = request.json
        crop_name = data.get('crop')
        pest_name = data.get('pest')
        current_value = float(data.get('value', 0))
        
        if crop_name not in knowledge_bases['pest_etl']:
             return jsonify({"status": "Error", "message": "Crop not found."})
        
        crop_data = knowledge_bases['pest_etl'][crop_name]
        if pest_name not in crop_data:
            return jsonify({"status": "Error", "message": "Pest not found."})
            
        pest_info = crop_data[pest_name]
        is_alert = current_value >= pest_info["threshold"]
        
        # Weather context logic
        weather = get_current_weather_simple()
        weather_risk = ""
        if weather and pest_name == "Tea Mosquito Bug":
             if weather['main']['temp'] > 25 and weather['main']['humidity'] > 80:
                  weather_risk = "High risk weather detected."
                  if not is_alert and current_value >= (pest_info["threshold"] * 0.8):
                      is_alert = True
        
        status_label = "ALERT" if is_alert else "SAFE"
        new_log = PestLog(crop_name=crop_name, pest_name=pest_name, value=current_value, alert_status=status_label, notes=weather_risk)
        db.session.add(new_log)
        db.session.commit()
        
        return jsonify({
            "status": status_label,
            "message": f"⚠️ ALERT: {pest_name} exceeds threshold!" if is_alert else "✅ Safe levels.",
            "recommendation": pest_info["advisory"] if is_alert else "Continue monitoring."
        })

    @app.route('/api/run_backup', methods=['POST'])
    def run_manual_backup():
        """Trigger database backup manually via the UI."""
        try:
            cwd = os.path.dirname(os.path.abspath(__file__))
            result = subprocess.run([sys.executable, 'backup_db.py'], capture_output=True, text=True, cwd=cwd)
            return jsonify({'status': 'success' if result.returncode == 0 else 'error', 'log': result.stdout or result.stderr})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    # FUTURE EDITING: Add more API endpoints for mobile app integration here.

    return app

# Main entry point
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # MAINTENANCE: Debug mode should be False in production
    app.run(debug=True)
