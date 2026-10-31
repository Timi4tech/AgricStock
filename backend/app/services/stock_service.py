from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from ..domain.models import InventoryItem, StockMovement
from ..domain.schemas import ItemCreate, MovementCreate
from ..repositories.stock_repository import StockRepository

class StockService:
    def __init__(self, db: Session): self.db = db; self.repo = StockRepository(db)
    def create_item(self, user_id: int, payload: ItemCreate):
        try:
            item = InventoryItem(user_id=user_id, name=payload.name.strip(), category=payload.category.strip(), unit=payload.unit.strip(), quantity=payload.opening_quantity, unit_cost=payload.unit_cost, reorder_level=payload.reorder_level, notes=payload.notes)
            self.db.add(item); self.db.flush()
            if payload.opening_quantity > 0:
                self.db.add(StockMovement(user_id=user_id, item_id=item.id, movement_type="stock_in", quantity=payload.opening_quantity, balance_after=payload.opening_quantity, reason="Opening balance"))
            self.db.flush(); return item
        except Exception:
            self.db.rollback(); raise
    def create_movement(self, user_id: int, payload: MovementCreate):
        try:
            item = self.repo.item_for_update(user_id, payload.item_id)
            if item is None: raise HTTPException(status_code=404, detail="Stock item not found")
            amount = payload.quantity
            if payload.movement_type == "adjustment":
                new_balance = amount; recorded_amount = abs(new_balance - item.quantity)
            elif payload.movement_type == "stock_in":
                new_balance = item.quantity + amount; recorded_amount = amount
            else:
                new_balance = item.quantity - amount; recorded_amount = amount
                if new_balance < 0: raise HTTPException(status_code=409, detail=f"Insufficient stock. Available: {item.quantity} {item.unit}")
            item.quantity = new_balance
            movement = StockMovement(user_id=user_id, item=item, movement_type=payload.movement_type, quantity=recorded_amount, balance_after=new_balance, reason=payload.reason, reference=payload.reference)
            self.db.add(movement); self.db.flush()
            # Ensure item fields are available after commit/refresh.
            return movement
        except Exception:
            self.db.rollback(); raise
    def dashboard(self, user_id: int):
        items = self.repo.items(user_id)
        total_value = sum((Decimal(item.quantity) * Decimal(item.unit_cost) for item in items), Decimal("0"))
        recent = self.repo.movements(user_id, 8)
        return {"item_count": len(items), "low_stock_count": sum(1 for i in items if i.quantity <= i.reorder_level), "total_stock_value": total_value, "recent_movements": recent}
