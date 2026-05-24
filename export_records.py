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
            FarmRecord.expense_type.isnot(None)
        ).group_by(FarmRecord.expense_type).all()
        
        # Income records (without ID)
        income_q = FarmRecord.query.filter(FarmRecord.category == 'Income').order_by(FarmRecord.date.asc()).all()
        income_records = [
            {
                'Date': r.date.isoformat() if r.date else None,
                'Activity': r.activity_type,
                'Amount (₹)': f"{(r.amount or 0.0):,.2f}",
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
                'Amount (₹)': f"{(r.amount or 0.0):,.2f}",
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
                'Amount (₹)': f"{(r.amount or 0.0):,.2f}",
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
        'Total (₹)': [f"{(item[1] or 0.0):,.2f}" for item in expense_breakdown],
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
                except Exception:
                    pass
            adjusted_width = min(max_length + 2, 30)  # Cap at 30
            sheet.column_dimensions[column_letter].width = adjusted_width
    
    writer.close()
    return out_path


def export_records_pdf(app, output_dir='exports'):
    """Export all farm records to a PDF report."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(output_dir, f'farm_records_{timestamp}.pdf')

    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    with app.app_context():
        # Calculate totals for summary
        total_income = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Income').scalar() or 0
        total_expense = db.session.query(func.sum(FarmRecord.amount)).filter(FarmRecord.category == 'Expense').scalar() or 0
        net_profit = total_income - total_expense
        
        # All records combined
        all_q = FarmRecord.query.order_by(FarmRecord.date.asc()).all()
        records_data = []
        for r in all_q:
            records_data.append([
                r.date.isoformat() if r.date else '-',
                r.activity_type or '-',
                r.category or '-',
                r.expense_type or '-' if r.category == 'Expense' else '-',
                f"Rs. {r.amount or 0.0:,.2f}"
            ])

    # PDF Document setup
    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1b4332'), # Dark green
        spaceAfter=4
    )
    
    meta_style = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#4b5563'),
        spaceAfter=15
    )

    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#1f2937')
    )

    cell_bold_style = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#1f2937')
    )

    cell_header_style = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.white
    )

    elements = []

    # Title & Metadata
    elements.append(Paragraph("FARMATÉ AGRICULTURAL LEDGER REPORT", title_style))
    elements.append(Paragraph(f"Report Generated: {datetime.datetime.now().strftime('%d %B %Y, %I:%M %p')} | Total Transactions: {len(all_q)}", meta_style))
    elements.append(Spacer(1, 10))

    # Summary box
    summary_data = [
        [
            Paragraph("<b>Total Income</b>", cell_bold_style),
            Paragraph("<b>Total Investment</b>", cell_bold_style),
            Paragraph("<b>Net Profit</b>", cell_bold_style)
        ],
        [
            Paragraph(f"Rs. {total_income:,.2f}", cell_style),
            Paragraph(f"Rs. {total_expense:,.2f}", cell_style),
            Paragraph(f"Rs. {net_profit:,.2f}", cell_bold_style)
        ]
    ]
    summary_table = Table(summary_data, colWidths=[180, 180, 180])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f3f4f6')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 2),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,1), (-1,1), 8),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e5e7eb')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    # Transactions List Title
    list_title_style = ParagraphStyle(
        'ListTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=10
    )
    elements.append(Paragraph("Transaction History", list_title_style))

    # Table headers
    headers = [
        Paragraph("Date", cell_header_style),
        Paragraph("Activity / Description", cell_header_style),
        Paragraph("Category", cell_header_style),
        Paragraph("Type", cell_header_style),
        Paragraph("Amount", cell_header_style)
    ]
    
    table_content = [headers]
    for row in records_data:
        table_content.append([
            Paragraph(row[0], cell_style),
            Paragraph(row[1], cell_style),
            Paragraph(row[2], cell_style),
            Paragraph(row[3], cell_style),
            Paragraph(row[4], cell_style)
        ])

    # Table Column Widths: Total width is 540 (612 - 72)
    tx_table = Table(table_content, colWidths=[70, 200, 70, 100, 100])
    
    # Alternating rows table style
    t_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#10b981')), # Sprout green header
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LINEBELOW', (0,0), (-1,0), 2, colors.HexColor('#047857')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
    ]
    
    for i in range(1, len(table_content)):
        if i % 2 == 0:
            t_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f9fafb')))
            
    tx_table.setStyle(TableStyle(t_style))
    elements.append(tx_table)

    doc.build(elements)
    return out_path


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        db.create_all()
    path = export_records(app)
    print(f'Export written to: {path}')

