import hashlib
import json
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..domain.models import User, IdempotencyRecord
from ..domain.schemas import (
    SignupIn, LoginIn, AuthOut, UserOut, ItemCreate, ItemOut,
    MovementCreate, MovementOut, DashboardOut,
)
from ..core.security import hash_password, verify_password, create_access_token, get_current_user
from ..core.upstash import get_redis
from ..services.stock_service import StockService

router = APIRouter()
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
RESERVE_SCRIPT = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1
end
return 0
"""
DELETE_IF_OWNER_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _hash_payload(payload) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _redis_idempotency_key(user_id: int, scope: str, key: str) -> str:
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"agrostock:idempotency:{user_id}:{scope}:{key_hash}"


def _cached_record(redis, redis_key: str, request_hash: str):
    value = redis.get(redis_key)
    if not value:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return None
    if parsed.get("request_hash") != request_hash:
        raise HTTPException(status_code=409, detail="This Idempotency-Key was already used with a different request")
    if parsed.get("status") == "completed":
        return parsed.get("response_body")
    return None


def _idempotent(db: Session, user_id: int, scope: str, key: str | None, payload, operation, request_id: str):
    if not key or len(key) > 128 or not key.strip():
        raise HTTPException(status_code=400, detail="A valid Idempotency-Key header is required for this operation")

    digest = _hash_payload(payload)
    redis = get_redis()
    redis_key = _redis_idempotency_key(user_id, scope, key)

    # PostgreSQL is the transactionally authoritative record. Redis is the shared
    # cross-worker reservation/cache, so a retry can recover after an API process restarts.
    existing = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.scope == scope,
        IdempotencyRecord.key == key,
    ))
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(status_code=409, detail="This Idempotency-Key was already used with a different request")
        if existing.response_body is None:
            raise HTTPException(status_code=409, detail="Request with this key is still processing; retry shortly")
        completed = {"status": "completed", "request_hash": digest, "response_body": existing.response_body}
        try:
            redis.set(redis_key, json.dumps(completed, separators=(",", ":")), ex=IDEMPOTENCY_TTL_SECONDS)
        except Exception:
            pass  # SQL retains the completed response if Redis cache refresh fails.
        return existing.response_body

    reservation = {"status": "processing", "request_hash": digest, "request_id": request_id}
    reservation_json = json.dumps(reservation, separators=(",", ":"))
    reserved = redis.eval(RESERVE_SCRIPT, [redis_key], [reservation_json, str(IDEMPOTENCY_TTL_SECONDS)])
    if not int(reserved):
        cached = _cached_record(redis, redis_key, digest)
        if cached is not None:
            return cached
        # A concurrent request may have committed to SQL just before its Redis cache update.
        existing = db.scalar(select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        ))
        if existing and existing.request_hash == digest and existing.response_body is not None:
            completed = {"status": "completed", "request_hash": digest, "response_body": existing.response_body}
            try:
                redis.set(redis_key, json.dumps(completed, separators=(",", ":")), ex=IDEMPOTENCY_TTL_SECONDS)
            except Exception:
                pass
            return existing.response_body
        raise HTTPException(status_code=409, detail="This operation is already processing; retry with the same Idempotency-Key")

    try:
        record = IdempotencyRecord(
            user_id=user_id, scope=scope, key=key, request_hash=digest,
            response_status=201, response_body=None,
        )
        db.add(record)
        db.flush()
        result = operation()
        body = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        record.response_body = body
        # The inventory mutation and durable idempotency response commit atomically.
        db.commit()
        completed = {"status": "completed", "request_hash": digest, "response_body": body}
        try:
            redis.set(redis_key, json.dumps(completed, separators=(",", ":")), ex=IDEMPOTENCY_TTL_SECONDS)
        except Exception:
            # The SQL idempotency row and stock mutation already committed atomically.
            # A retry will recover the cached response from PostgreSQL.
            pass
        return body
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        ))
        if existing and existing.request_hash == digest and existing.response_body is not None:
            completed = {"status": "completed", "request_hash": digest, "response_body": existing.response_body}
            try:
                redis.set(redis_key, json.dumps(completed, separators=(",", ":")), ex=IDEMPOTENCY_TTL_SECONDS)
            except Exception:
                pass
            return existing.response_body
        try:
            redis.eval(DELETE_IF_OWNER_SCRIPT, [redis_key], [reservation_json])
        except Exception:
            pass
        raise HTTPException(status_code=409, detail="Concurrent request used this Idempotency-Key; retry with the same key")
    except Exception:
        db.rollback()
        # Only the request that created the reservation may remove it.
        try:
            redis.eval(DELETE_IF_OWNER_SCRIPT, [redis_key], [reservation_json])
        except Exception:
            pass
        raise


@router.post("/auth/signup", response_model=AuthOut, status_code=201)
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        name=payload.name, email=payload.email, password_hash=hash_password(payload.password),
        business_name=payload.business_name, business_type=payload.business_type,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    return AuthOut(access_token=create_access_token(user.id), user=user)


@router.post("/auth/login", response_model=AuthOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return AuthOut(access_token=create_access_token(user.id), user=user)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/items", response_model=list[ItemOut])
def list_items(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return StockService(db).repo.items(user.id)


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(
    payload: ItemCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _idempotent(
        db, user.id, "create-item", idempotency_key, payload,
        lambda: ItemOut.model_validate(StockService(db).create_item(user.id, payload)),
        getattr(request.state, "request_id", str(uuid.uuid4())),
    )


@router.get("/movements", response_model=list[MovementOut])
def list_movements(limit: int = Query(default=100, ge=1, le=200), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = StockService(db).repo.movements(user.id, limit)
    return [MovementOut(
        id=m.id, item_id=m.item_id, item_name=m.item.name, unit=m.item.unit,
        movement_type=m.movement_type, quantity=m.quantity, balance_after=m.balance_after,
        reason=m.reason, reference=m.reference, created_at=m.created_at,
    ) for m in rows]


@router.post("/movements", response_model=MovementOut, status_code=201)
def create_movement(
    payload: MovementCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def operation():
        movement = StockService(db).create_movement(user.id, payload)
        return MovementOut(
            id=movement.id, item_id=movement.item_id, item_name=movement.item.name,
            unit=movement.item.unit, movement_type=movement.movement_type,
            quantity=movement.quantity, balance_after=movement.balance_after,
            reason=movement.reason, reference=movement.reference, created_at=movement.created_at,
        )
    return _idempotent(
        db, user.id, "create-movement", idempotency_key, payload, operation,
        getattr(request.state, "request_id", str(uuid.uuid4())),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raw = StockService(db).dashboard(user.id)
    raw["recent_movements"] = [MovementOut(
        id=m.id, item_id=m.item_id, item_name=m.item.name, unit=m.item.unit,
        movement_type=m.movement_type, quantity=m.quantity, balance_after=m.balance_after,
        reason=m.reason, reference=m.reference, created_at=m.created_at,
    ) for m in raw["recent_movements"]]
    return raw
