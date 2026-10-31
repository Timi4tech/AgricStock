from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from ..domain.models import InventoryItem, StockMovement

class StockRepository:
    def __init__(self, db: Session): self.db = db
    def items(self, user_id: int):
        return list(self.db.scalars(select(InventoryItem).where(InventoryItem.user_id == user_id).order_by(InventoryItem.name.asc())).all())
    def item_for_update(self, user_id: int, item_id: int):
        return self.db.scalar(select(InventoryItem).where(InventoryItem.user_id == user_id, InventoryItem.id == item_id).with_for_update())
    def movements(self, user_id: int, limit: int = 100):
        return list(self.db.scalars(select(StockMovement).options(joinedload(StockMovement.item)).where(StockMovement.user_id == user_id).order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(limit)).all())
