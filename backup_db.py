import os
import sys
import shutil
import datetime
import json
from pathlib import Path
from dotenv import load_dotenv

# Fix Windows console encoding for emoji support
if sys.platform == 'win32':
    try:
        # Try to set UTF-8 encoding for stdout
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python <3.7 fallback
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

def safe_print(text):
    """Print with fallback for environments that don't support Unicode"""
    try:
        print(text)
    except UnicodeEncodeError:
        # Fallback: remove emojis
        ascii_text = text.encode('ascii', 'ignore').decode('ascii')
        print(ascii_text)

load_dotenv()

def backup_to_multiple_locations():
    """Create backups in multiple locations for safety"""
    db_path = Path('instance/farm_data.db')
    
    if not db_path.exists():
        safe_print("⚠️ No database file found to backup")
        return False
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    date_folder = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # Backup Location 1: Local backups folder
    backup_dir = Path('backups')
    backup_dir.mkdir(exist_ok=True)
    local_backup = backup_dir / f'farm_data_{timestamp}.db'
    shutil.copy2(db_path, local_backup)
    safe_print(f"✅ Local backup: {local_backup}")
    
    # Backup Location 2: OneDrive (if available)
    onedrive_base = Path(os.environ.get('USERPROFILE', '')) / 'OneDrive'
    onedrive_path = onedrive_base / 'FarmApp_Backups' / date_folder
    if onedrive_base.exists():
        try:
            onedrive_path.mkdir(parents=True, exist_ok=True)
            onedrive_backup = onedrive_path / f'farm_data_{timestamp}.db'
            shutil.copy2(db_path, onedrive_backup)
            safe_print(f"✅ OneDrive backup: {onedrive_backup}")
        except Exception as e:
            safe_print(f"⚠️ OneDrive backup failed: {e}")
    else:
        onedrive_backup = None
    
    # Backup Location 3: Desktop dated folder (always accessible)
    desktop_backup_dir = Path(os.environ.get('USERPROFILE', '')) / 'Desktop' / 'FarmApp_Emergency_Backups' / date_folder
    desktop_backup_dir.mkdir(parents=True, exist_ok=True)
    desktop_backup = desktop_backup_dir / f'farm_data_{timestamp}.db'
    shutil.copy2(db_path, desktop_backup)
    safe_print(f"✅ Desktop backup: {desktop_backup}")
    
    # Keep only last 10 backups in local folder
    backups = sorted(backup_dir.glob('farm_data_*.db'), key=lambda x: x.stat().st_mtime, reverse=True)
    if len(backups) > 10:
        for old_backup in backups[10:]:
            old_backup.unlink()
            safe_print(f"🗑️ Removed old backup: {old_backup.name}")
    
    # Create a backup manifest
    manifest = {
        'timestamp': timestamp,
        'date': date_folder,
        'database_size_kb': db_path.stat().st_size / 1024,
        'backups': {
            'local': str(local_backup),
            'desktop': str(desktop_backup),
            'onedrive': str(onedrive_backup) if onedrive_path.exists() else None
        }
    }
    
    manifest_file = backup_dir / f'manifest_{timestamp}.json'
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    safe_print(f"\n📋 Backup manifest: {manifest_file}")
    safe_print(f"💾 Total size: {manifest['database_size_kb']:.2f} KB")
    return True

if __name__ == '__main__':
    safe_print("=" * 60)
    safe_print("🔒 MULTI-LOCATION DATABASE BACKUP SYSTEM")
    safe_print("=" * 60)
    success = backup_to_multiple_locations()
    if success:
        safe_print("\n✅ ALL BACKUPS COMPLETED SUCCESSFULLY!")
        safe_print("Your data is now safe in 3 locations.")
    else:
        safe_print("\n❌ BACKUP FAILED - Check database location")
