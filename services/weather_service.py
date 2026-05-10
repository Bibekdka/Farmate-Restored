import os
import requests
import datetime
import logging
from extensions import db
from models import WeatherLog
from utils.constants import FARM_LATITUDE, FARM_LONGITUDE, WMO_CODES

logger = logging.getLogger(__name__)

# Simple in-memory cache for weather
_weather_cache = {
    'data': None,
    'expiry': None
}

def get_weather_openmeteo():
    """Fetch weather forecast from Open-Meteo API with 30-minute caching."""
    global _weather_cache
    
    # Return cached data if still valid (30 minute cache)
    now = datetime.datetime.now()
    if _weather_cache['data'] and _weather_cache['expiry'] > now:
        return _weather_cache['data']

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": FARM_LATITUDE,
            "longitude": FARM_LONGITUDE,
            "daily": ["weather_code", "temperature_2m_max", "precipitation_sum"],
            "timezone": "auto"
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        forecast = []
        if response.status_code == 200:
            daily = data.get('daily', {})
            for i in range(len(daily.get('time', []))):
                code = daily['weather_code'][i]
                desc = WMO_CODES.get(code, f"Code: {code}")
                
                day_data = {
                    'date': daily['time'][i],
                    'temp': daily['temperature_2m_max'][i],
                    'desc': desc,
                    'rain_prob': daily['precipitation_sum'][i]
                }
                forecast.append(day_data)
            
            # Update cache on success
            _weather_cache['data'] = forecast
            _weather_cache['expiry'] = datetime.datetime.now() + datetime.timedelta(minutes=30)
        
        return forecast
    except Exception as e:
        logger.error(f"Weather Forecast Error: {e}")
        return _weather_cache['data'] or [] # Fallback to stale cache if available

def fetch_historical_weather(start_date, end_date):
    """Fetch historical weather data from Open-Meteo Archive API."""
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": FARM_LATITUDE,
            "longitude": FARM_LONGITUDE,
            "start_date": start_date.strftime('%Y-%m-%d'),
            "end_date": end_date.strftime('%Y-%m-%d'),
            "daily": ["weather_code", "temperature_2m_max", "precipitation_sum"],
            "timezone": "auto"
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('daily')
    except Exception as e:
        logger.error(f"Historical Weather API Error: {e}")
        return None

def backfill_weather_history():
    """Fetch missing weather data for past 30 days and save to database."""
    try:
        today = datetime.date.today()
        # Default start date for this version of the app
        feb_start_2026 = datetime.date(2026, 2, 1)
        thirty_days_ago = today - datetime.timedelta(days=30)
        start_date = min(feb_start_2026, thirty_days_ago)
        end_date = today - datetime.timedelta(days=1)
        
        # Check which dates already have logs
        existing_logs = WeatherLog.query.filter(
            WeatherLog.date >= start_date,
            WeatherLog.date <= end_date
        ).all()
        existing_dates = {log.date for log in existing_logs}
        
        # Find gaps in the timeline
        current_date = start_date
        missing_ranges = []
        range_start = None
        
        while current_date <= end_date:
            if current_date not in existing_dates:
                if range_start is None:
                    range_start = current_date
            else:
                if range_start is not None:
                    missing_ranges.append((range_start, current_date - datetime.timedelta(days=1)))
                    range_start = None
            current_date += datetime.timedelta(days=1)
        
        if range_start is not None:
            missing_ranges.append((range_start, end_date))
        
        if not missing_ranges:
            return
        
        total_added = 0
        for range_start, range_end in missing_ranges:
            daily_data = fetch_historical_weather(range_start, range_end)
            
            if daily_data and 'time' in daily_data:
                for i in range(len(daily_data['time'])):
                    try:
                        d_str = daily_data['time'][i]
                        d_obj = datetime.datetime.strptime(d_str, '%Y-%m-%d').date()
                        
                        if not WeatherLog.query.filter_by(date=d_obj).first():
                            code = daily_data['weather_code'][i]
                            new_log = WeatherLog(
                                date=d_obj,
                                max_temp=daily_data['temperature_2m_max'][i],
                                rainfall=daily_data['precipitation_sum'][i],
                                description=WMO_CODES.get(code, f"Code: {code}")
                            )
                            db.session.add(new_log)
                            total_added += 1
                    except Exception as e:
                        continue
        
        if total_added > 0:
            db.session.commit()
            logger.info(f"Backfilled {total_added} weather logs")
            
    except Exception as e:
        logger.error(f"Weather Backfill Error: {e}")
        db.session.rollback()

def get_current_weather_simple():
    """Fetch current weather using OpenWeatherMap if key is available."""
    api_key = os.environ.get('OPENWEATHERMAP_API_KEY')
    if not api_key:
        return None
    try:
        # Use constants for LAT/LON
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={FARM_LATITUDE}&lon={FARM_LONGITUDE}&appid={api_key}&units=metric"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None
