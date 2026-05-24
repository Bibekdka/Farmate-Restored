# Input validation and sanitization
import logging
from datetime import datetime
from functools import wraps
from flask import jsonify

logger = logging.getLogger(__name__)


def validate_date(date_str, date_format='%Y-%m-%d'):
    """Validate and parse date string safely."""
    try:
        return datetime.strptime(date_str, date_format).date()
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid date format: {date_str} - {e}")
        return None


def validate_amount(amount_str):
    """Validate and parse amount safely."""
    try:
        amt = float(amount_str)
        if amt < 0:
            return None
        return amt
    except (ValueError, TypeError):
        return None


def validate_crop_id(crop_id_str):
    """Validate and parse crop ID safely."""
    try:
        cid = int(crop_id_str)
        return cid if cid > 0 else None
    except (ValueError, TypeError):
        return None


def validate_string(value, min_len=1, max_len=500, allow_empty=False):
    """Validate string input."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not allow_empty and len(value) < min_len:
        return None
    if len(value) > max_len:
        return None
    return value


def validate_category(category):
    """Validate expense/income category."""
    valid = ['Income', 'Expense']
    return category if category in valid else None


def safe_api_response(func):
    """Decorator to safely handle API responses with error catching."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Validation error in {func.__name__}: {e}")
            return jsonify({"status": "error", "message": "Invalid input"}), 400
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            return jsonify({"status": "error", "message": "Server error"}), 500
    return wrapper
