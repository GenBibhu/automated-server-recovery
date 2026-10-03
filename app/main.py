"""
Demo FastAPI service for an AI-agent deployment-recovery presentation.

/health is healthy on main. To simulate a bad deploy, uncomment the
broken block in health() and comment out the healthy return.
"""

import os
import secrets
from enum import Enum
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

APP_VERSION = "v1"

app = FastAPI(
    title="Deployment Recovery Demo API",
    description="Small demo service used to simulate healthy vs failed deployments.",
    version=APP_VERSION,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OrderStatus(str, Enum):
    """Allowed order statuses. Existing records use pending/shipped/delivered."""

    pending = "pending"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class User(BaseModel):
    id: int
    name: str
    email: str


class Order(BaseModel):
    id: int
    user_id: int
    product: str
    amount: float
    status: str


class OrderCreate(BaseModel):
    user_id: int = Field(..., gt=0, description="ID of the user placing the order")
    product: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    discount_percent: float = Field(
        0,
        ge=0,
        le=100,
        description="Optional percent discount",
    )


class OrderUpdate(BaseModel):
    status: Optional[OrderStatus] = None
    amount: Optional[float] = Field(None, gt=0)


class HealthResponse(BaseModel):
    status: str
    version: str
    reason: str | None = None


class VersionResponse(BaseModel):
    version: str


# ---------------------------------------------------------------------------
# In-memory demo data
# ---------------------------------------------------------------------------

USERS: List[User] = [
    User(id=1, name="Alice Johnson", email="alice@example.com"),
    User(id=2, name="Bob Smith", email="bob@example.com"),
    User(id=3, name="Carol Lee", email="carol@example.com"),
]

ORDERS: List[Order] = [
    Order(id=1, user_id=1, product="Laptop", amount=1299.99, status="shipped"),
    Order(id=2, user_id=2, product="Keyboard", amount=79.50, status="pending"),
    Order(id=3, user_id=1, product="Monitor", amount=349.00, status="delivered"),
]

_next_order_id = 4


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Authorize admin routes with ADMIN_TOKEN from the environment.

    The token is read on each request. Access is denied when the variable is
    unset or empty, and the configured value is never included in a response.
    """
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        )
    provided = x_admin_token or ""
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
def health():
    """Health check used by deployment / recovery demos."""
    # --- HEALTHY (active on main) ---
    # return {"status": "healthy", "version": APP_VERSION}

    # --- BROKEN (uncomment for bad-deploy demo; comment out the healthy return above) ---
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "unhealthy",
            "version": "broken",
            "reason": "simulated deployment failure",
        },
    )


@app.get("/version", response_model=VersionResponse)
def version():
    return {"version": APP_VERSION}


@app.get("/api/users", response_model=List[User])
def list_users():
    return USERS


@app.get("/api/users/{user_id}", response_model=User)
def get_user(user_id: int):
    for user in USERS:
        if user.id == user_id:
            return user
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@app.get("/api/orders", response_model=List[Order])
def list_orders(
    user_id: Optional[int] = Query(None, description="Filter orders by user"),
    status_filter: Optional[OrderStatus] = Query(None, alias="status"),
):
    results = list(ORDERS)
    if user_id is not None:
        results = [order for order in results if order.user_id == user_id]
    if status_filter is not None:
        results = [order for order in results if order.status == status_filter.value]
    return results


@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: int):
    for order in ORDERS:
        if order.id == order_id:
            return order
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.post("/api/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate):
    global _next_order_id

    if not any(user.id == payload.user_id for user in USERS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} not found",
        )

    final_amount = payload.amount * (1 - payload.discount_percent / 100)
    if final_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Final amount must be greater than 0",
        )

    order = Order(
        id=_next_order_id,
        user_id=payload.user_id,
        product=payload.product,
        amount=final_amount,
        status=OrderStatus.pending.value,
    )
    _next_order_id += 1
    ORDERS.append(order)
    return order


@app.patch(
    "/api/orders/{order_id}",
    response_model=Order,
    dependencies=[Depends(require_admin)],
)
def update_order(order_id: int, payload: OrderUpdate):
    for order in ORDERS:
        if order.id == order_id:
            if payload.status is not None:
                order.status = payload.status.value
            if payload.amount is not None:
                order.amount = payload.amount
            return order
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.delete(
    "/api/orders/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_order(order_id: int):
    for index, order in enumerate(ORDERS):
        if order.id == order_id:
            ORDERS.pop(index)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.get("/api/admin/dump", dependencies=[Depends(require_admin)])
def admin_dump():
    """Return full in-memory state for debugging."""
    return {
        "users": [user.model_dump() for user in USERS],
        "orders": [order.model_dump() for order in ORDERS],
        "next_order_id": _next_order_id,
    }


@app.get("/api/search", response_model=List[User])
def search(q: str = Query(...)):
    """Search users by case-insensitive substring match on name."""
    needle = q.casefold()
    return [user for user in USERS if needle in user.name.casefold()]
