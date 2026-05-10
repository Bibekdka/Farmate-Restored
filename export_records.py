import os
import datetime
import pandas as pd
from sqlalchemy import func

from extensions import db
from models import FarmRecord, WeatherLog


def export_records(app, output_dir='exports'):
    """Export all farm records to Excel with summary sheets and dashboard."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(output_dir, f'farm_records_{timestamp}.xlsx')

    with app.app_context():
        # Calculate totals for summary
        total_income = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Income').scalar() or 0
        total_expense = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Expense').scalar() or 0
        net_profit = total_income - total_expense
        
        # Get category breakdown
        expense_breakdown = db.session.query(
            FarmRecord.expense_type, func.sum(FarmRecord.amount)
        ).filter(
            FarmRecord.category == 'Expense',
            FarmRecord.expense_type != None
        ).group_by(FarmRecord.expense_type).all()
        
        # Income records (without ID)
        income_q = FarmRecord.query.filter(FarmRecord.category == 'Income').order_by(FarmRecord.date.asc()).all()
        income_records = [
            {
                'Date': r.date.isoformat() if r.date else None,
                'Activity': r.activity_type,
                'Amount (₹)': f"{r.amount:,.2f}",
                'Description': r.description or '-'
            }
            for r in income_q
        ]
        
        # Expense records (without ID)
        expenses_q = FarmRecord.query.filter(FarmRecord.category == 'Expense').order_by(FarmRecord.date.asc()).all()
        expense_records = [
            {
                'Date': r.date.isoformat() if r.date else None,
                'Activity': r.activity_type,
                'Type': r.expense_type or '-',
                'Amount (₹)': f"{r.amount:,.2f}",
                'Description': r.description or '-'
            }
            for r in expenses_q
        ]

        # All records combined (without ID)
        all_q = FarmRecord.query.order_by(FarmRecord.date.asc()).all()
        all_records = [
            {
                'Date': r.date.isoformat() if r.date else None,
                'Activity': r.activity_type,
                'Category': r.category,
                'Type': r.expense_type or '-' if r.category == 'Expense' else '-',
                'Amount (₹)': f"{r.amount:,.2f}",
                'Description': r.description or '-'
            }
            for r in all_q
        ]

        # Weather logs (without ID)
        weather_q = WeatherLog.query.order_by(WeatherLog.date.asc()).all()
        weather_records = [
            {
                'Date': w.date.isoformat() if w.date else None,
                'Max Temp (°C)': f"{w.max_temp:.1f}" if w.max_temp else '-',
                'Rainfall (mm)': f"{w.rainfall:.1f}" if w.rainfall else '-',
                'Condition': w.description or '-'
            }
            for w in weather_q
        ]

    # Create Excel writer with optimizations
    writer = pd.ExcelWriter(out_path, engine='openpyxl')
    
    # --- DASHBOARD SHEET (Summary) ---
    summary_data = {
        'Metric': ['Total Income', 'Total Investment', 'Net Profit', 'Expense Count', 'Income Count'],
        'Value': [
            f"₹{total_income:,.2f}",
            f"₹{total_expense:,.2f}",
            f"₹{net_profit:,.2f}",
            len(expenses_q),
            len(income_q)
        ]
    }
    df_summary = pd.DataFrame(summary_data)
    df_summary.to_excel(writer, sheet_name='Dashboard', index=False)
    
    # --- CATEGORY BREAKDOWN SHEET ---
    category_data = {
        'Expense Category': [item[0] for item in expense_breakdown],
        'Total (₹)': [f"{item[1]:,.2f}" for item in expense_breakdown],
        'Percentage': [f"{(item[1]/total_expense*100):.1f}%" if total_expense > 0 else '0%' for item in expense_breakdown]
    }
    df_category = pd.DataFrame(category_data)
    df_category.to_excel(writer, sheet_name='Category Summary', index=False)
    
    # --- ALL RECORDS SHEET ---
    if all_records:
        df_all = pd.DataFrame(all_records)
        df_all.to_excel(writer, sheet_name='All Transactions', index=False)
    else:
        pd.DataFrame([], columns=['Date', 'Activity', 'Category', 'Type', 'Amount (₹)', 'Description']).to_excel(writer, sheet_name='All Transactions', index=False)
    
    # --- INCOME SHEET ---
    if income_records:
        df_income = pd.DataFrame(income_records)
        df_income.to_excel(writer, sheet_name='Income', index=False)
    else:
        pd.DataFrame([], columns=['Date', 'Activity', 'Amount (₹)', 'Description']).to_excel(writer, sheet_name='Income', index=False)
    
    # --- EXPENSES SHEET ---
    if expense_records:
        df_expenses = pd.DataFrame(expense_records)
        df_expenses.to_excel(writer, sheet_name='Expenses', index=False)
    else:
        pd.DataFrame([], columns=['Date', 'Activity', 'Type', 'Amount (₹)', 'Description']).to_excel(writer, sheet_name='Expenses', index=False)
    
    # --- WEATHER SHEET ---
    if weather_records:
        df_weather = pd.DataFrame(weather_records)
        df_weather.to_excel(writer, sheet_name='Weather History', index=False)
    else:
        pd.DataFrame([], columns=['Date', 'Max Temp (°C)', 'Rainfall (mm)', 'Condition']).to_excel(writer, sheet_name='Weather History', index=False)
    
    # Optimize column widths for all sheets
    for sheet in writer.sheets.values():
        for column in sheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 30)  # Cap at 30
            sheet.column_dimensions[column_letter].width = adjusted_width
    
    writer.close()
    return out_path


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        db.create_all()
    path = export_records(app)
    print(f'Export written to: {path}')
