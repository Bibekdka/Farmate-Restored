import time
from app import create_app, db
from models import Inventory, InventoryTransaction

def test_inventory_performance():
    app = create_app('development')
    with app.app_context():
        print("--- Inventory Performance Test ---")
        
        # 1. Test Insert Performance
        start_time = time.time()
        for i in range(100):
            item = Inventory(
                name=f"Test Item {i}",
                category="Test",
                quantity=100.0,
                unit="kg",
                min_stock_level=10.0
            )
            db.session.add(item)
        db.session.commit()
        insert_time = time.time() - start_time
        print(f"Inserted 100 items in: {insert_time:.4f}s")
        
        # 2. Test Query Performance
        start_time = time.time()
        items = Inventory.query.all()
        query_time = time.time() - start_time
        print(f"Queried {len(items)} items in: {query_time:.4f}s")
        
        # 3. Test Transaction Filter Performance
        if items:
            item_id = items[0].id
            start_time = time.time()
            trans = InventoryTransaction.query.filter_by(inventory_id=item_id).all()
            filter_time = time.time() - start_time
            print(f"Filtered transactions for item {item_id} in: {filter_time:.4f}s")
        
        # Cleanup
        print("Cleaning up test data...")
        Inventory.query.filter(Inventory.category == "Test").delete()
        db.session.commit()
        print("Test Complete.")

if __name__ == "__main__":
    test_inventory_performance()
