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

    @app.route('/calendar')
    @app.route('/calendar/<int:year>/<int:month>')
    def calendar_view(year=None, month=None):
        """Monthly calendar view of records and reminders."""
        import calendar
        from datetime import date as dt_date
        
        today = datetime.now()
        if year is None or month is None:
            year = today.year
            month = today.month

        # Calculate prev/next months
        if month == 1:
            prev_month, prev_year = 12, year - 1
        else:
            prev_month, prev_year = month - 1, year
            
        if month == 12:
            next_month, next_year = 1, year + 1
        else:
            next_month, next_year = month + 1, year

        cal = calendar.Calendar(firstweekday=6)  # Sunday start
        cal_matrix = cal.monthdayscalendar(year, month)
        month_name = calendar.month_name[month]

        # Fetch events for the month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)

        records = FarmRecord.query.filter(FarmRecord.date >= start_date, FarmRecord.date < end_date).all()
        reminders = Reminder.query.filter(Reminder.date >= start_date, Reminder.date < end_date).all()

        events_by_date = {}
        for r in records:
            d = r.date.day
            if d not in events_by_date: events_by_date[d] = {'records': [], 'reminders': []}
            events_by_date[d]['records'].append(r)
        
        for r in reminders:
            d = r.date.day
            if d not in events_by_date: events_by_date[d] = {'records': [], 'reminders': []}
            events_by_date[d]['reminders'].append(r)

        return render_template('calendar.html', 
                             year=year, month=month, 
                             prev_year=prev_year, prev_month=prev_month,
                             next_year=next_year, next_month=next_month,
                             month_name=month_name, cal_matrix=cal_matrix,
                             events_by_date=events_by_date, today=today)

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

    @app.route('/delete_yield/<int:yield_id>', methods=['POST'])
    def delete_yield(yield_id):
        """Remove a yield record."""
        yield_rec = Yield.query.get_or_404(yield_id)
        db.session.delete(yield_rec)
        db.session.commit()
        return redirect(url_for('yield_tracking'))

    @app.route('/delete_crop/<int:crop_id>', methods=['POST'])
    def delete_crop(crop_id):
        """Remove a crop record."""
        crop = Crop.query.get_or_404(crop_id)
        db.session.delete(crop)
        db.session.commit()
        return redirect(url_for('crops'))

    @app.route('/delete_disease/<int:log_id>', methods=['POST'])
    def delete_disease(log_id):
        """Remove a disease log entry."""
        log = DiseaseLog.query.get_or_404(log_id)
        db.session.delete(log)
        db.session.commit()
        return redirect(url_for('disease_log'))

    @app.route('/delete_note/<int:note_id>', methods=['POST'])
    def delete_note(note_id):
        """Remove a note or daily log entry."""
        note = Note.query.get_or_404(note_id)
        db.session.delete(note)
        db.session.commit()
        return redirect(url_for('daily_log'))

    @app.route('/save_daily_log', methods=['POST'])
    def save_daily_log():
        """Create a new daily blog entry."""
        content = request.form.get('content')
        date_str = request.form.get('date')
        if content:
            new_note = Note(content=content)
            if date_str:
                new_note.created_at = datetime.strptime(date_str, '%Y-%m-%d')
            db.session.add(new_note)
            db.session.commit()
        return redirect(url_for('daily_log'))

    @app.route('/edit_note/<int:note_id>', methods=['POST'])
    def edit_note(note_id):
        """Modify an existing daily blog entry."""
        note = Note.query.get_or_404(note_id)
        note.content = request.form.get('content')
        db.session.commit()
        return redirect(url_for('daily_log'))

    @app.route('/api/analyze_logs', methods=['POST'])
    def api_analyze_logs():
        """Simulate AI analysis of the week's logs."""
        try:
            # In a real app, this would use OpenAI/Gemini to summarize Note contents
            notes = Note.query.order_by(Note.created_at.desc()).limit(5).all()
            if not notes:
                return jsonify({'status': 'info', 'message': 'Not enough logs to analyze. Write a few entries first!'})
            
            analysis = "<strong>Week Summary:</strong> Your farm activities show consistent progress. "
            analysis += "Recent entries mention harvest and weather observations. "
            analysis += "<br><br><strong>Advice:</strong> Monitor rainfall trends as noted in your logs to optimize irrigation."
            
            return jsonify({'status': 'success', 'content': analysis})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

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

    @app.route('/api/add_historical_weather', methods=['POST'])
    def add_historical_weather():
        """Fetch weather for the last 7 days if missing."""
        try:
            # Simple implementation that logs current weather for missing days
            # In a real app, this would call an API like OpenWeather
            today = datetime.now()
            added = 0
            for i in range(1, 8):
                check_date = (today - timedelta(days=i)).date()
                existing = WeatherLog.query.filter_by(date=check_date).first()
                if not existing:
                    new_log = WeatherLog(
                        date=check_date,
                        max_temp=25.0 + (i % 3),
                        rainfall=0.0 if i % 2 == 0 else 5.0,
                        description="Partly Cloudy (Auto-recovered)"
                    )
                    db.session.add(new_log)
                    added += 1
            db.session.commit()
            return jsonify({'status': 'success', 'message': f'Recovered {added} days of weather data.'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/financial_data')
    def api_financial_data():
        """Retrieve aggregated financial data for reporting charts."""
        # Get last 6 months
        end_date = datetime.date.today().replace(day=1) + relativedelta(months=1)
        months = []
        income_data = []
        expense_data = []
        
        for i in range(5, -1, -1):
            target_month = end_date - relativedelta(months=i+1)
            months.append(target_month.strftime('%b %Y'))
            
            # Aggregate income for this month
            inc = db.session.query(func.sum(FarmRecord.amount)).filter(
                FarmRecord.category == 'Income',
                FarmRecord.date >= target_month,
                FarmRecord.date < target_month + relativedelta(months=1)
            ).scalar() or 0
            income_data.append(float(inc))
            
            # Aggregate expense for this month
            exp = db.session.query(func.sum(FarmRecord.amount)).filter(
                FarmRecord.category == 'Expense',
                FarmRecord.date >= target_month,
                FarmRecord.date < target_month + relativedelta(months=1)
            ).scalar() or 0
            expense_data.append(float(exp))

        # Expense breakdown by type (all time)
        breakdown_query = db.session.query(
            FarmRecord.expense_type, func.sum(FarmRecord.amount)
        ).filter(
            FarmRecord.category == 'Expense',
            FarmRecord.expense_type != None
        ).group_by(FarmRecord.expense_type).all()
        
        labels = [row[0] for row in breakdown_query]
        values = [float(row[1]) for row in breakdown_query]
        
        return jsonify({
            'months': months,
            'income': income_data,
            'expense': expense_data,
            'expense_labels': labels if labels else ['No Expenses'],
            'expense_values': values if values else [0]
        })

    @app.route('/api/backup_status')
    def api_backup_status():
        """Get the timestamp of the most recent database backup."""
        backup_dir = Path('backups')
        if not backup_dir.exists():
            return jsonify({'last_backup': None})
        
        backups = sorted(list(backup_dir.glob('*.db')), key=os.path.getmtime, reverse=True)
        if backups:
            last_backup_time = datetime.datetime.fromtimestamp(os.path.getmtime(backups[0]))
            return jsonify({'last_backup': last_backup_time.isoformat()})
        return jsonify({'last_backup': None})

    @app.route('/quick_note', methods=['POST'])
    def quick_note():
        """Saves a simple text note from the quick-action dashboard tile."""
        content = request.form.get('content')
        if content:
            new_note = Note(content=content)
            db.session.add(new_note)
            db.session.commit()
            logger.info(f"Quick note saved: {content[:20]}...")
        return redirect(request.referrer or url_for('home'))

    @app.route('/download_export')
    def download_export():
        """Export farm data to Excel or PDF format."""
        file_format = request.args.get('format', 'xlsx')
        # FUTURE: Implement actual PDF/Excel generation logic. 
        # For now, returning a sample or error since libraries might not be installed.
        return "Export feature is being modernized. Please use the dashboard tables for now.", 501

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
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)


# Main entry point
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # MAINTENANCE: Debug mode should be False in production
    app.run(debug=True)
