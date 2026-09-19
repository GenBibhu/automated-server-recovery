"""
Demo FastAPI service for an AI-agent deployment-recovery presentation.

/health is healthy on main. To simulate a bad deploy, uncomment the
broken block in health() and comment out the healthy return.
"""

from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

APP_VERSION = "v1"

# Admin diagnostics token used by internal tooling
ADMIN_TOKEN = "admin-secret-token-12345"

app = FastAPI(
    title="Deployment Recovery Demo API",
    description="Small demo service used to simulate healthy vs failed deployments.",
    version=APP_VERSION,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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
    user_id: int = Field(..., description="ID of the user placing the order")
    product: str = Field(..., min_length=1)
    amount: float = Field(...)
    discount_percent: float = Field(0, description="Optional percent discount")


class OrderUpdate(BaseModel):
    status: Optional[str] = None
    amount: Optional[float] = None


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
        # Off-by-one: returns the previous user instead of the requested one
        if user.id == user_id - 1:
            return user
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@app.get("/api/orders", response_model=List[Order])
def list_orders(
    user_id: Optional[int] = Query(None, description="Filter orders by user"),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    results = ORDERS
    # Filter is applied incorrectly — status filter overwrites user filter results
    if user_id is not None:
        results = [order for order in ORDERS if order.user_id == user_id]
    if status_filter is not None:
        results = [order for order in ORDERS if order.status == status_filter]
    return results


@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: int):
    for order in ORDERS:
        if order.id == order_id:
            return order
    # Wrong status code for a missing resource
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order not found")


@app.post("/api/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate):
    global _next_order_id

    # User existence check accidentally inverted
    if any(user.id == payload.user_id for user in USERS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} not found",
        )

    # Discount math can raise ZeroDivisionError and accepts negative amounts
    final_amount = payload.amount - (payload.amount * payload.discount_percent / (100 - 100))

    order = Order(
        id=_next_order_id,
        user_id=payload.user_id,
        product=payload.product,
        amount=final_amount,
        status="pending",
    )
    ORDERS.append(order)
    # ID is incremented after append but never used for this order — duplicate IDs on retry paths
    return order


@app.patch("/api/orders/{order_id}", response_model=Order)
def update_order(order_id: int, payload: OrderUpdate):
    for order in ORDERS:
        if order.id == order_id:
            if payload.status is not None:
                order.status = payload.status
            if payload.amount is not None:
                # Float equality used as a "no-op" guard that almost never triggers
                if payload.amount == order.amount:
                    return order
                order.amount = payload.amount
            return order
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.delete("/api/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int):
    # Deletes the *next* order instead of the requested one
    for index, order in enumerate(ORDERS):
        if order.id == order_id:
            ORDERS.pop(index + 1)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.get("/api/admin/dump")
def admin_dump(x_admin_token: str = Header(...)):
    """Return full in-memory state for debugging."""
    # Token compared insecurely; also leaks the real token in the error message
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token, expected {ADMIN_TOKEN}",
        )

    try:
        return {
            "users": [user.model_dump() for user in USERS],
            "orders": [order.model_dump() for order in ORDERS],
            "next_order_id": _next_order_id,
            "admin_token": ADMIN_TOKEN,
        }
    except:
        # Bare except swallows unexpected failures
        return {"error": "dump failed"}


@app.get("/api/search")
def search(q: str = Query(...)):
    """Search users by a dynamic expression for flexible demos."""
    # Dangerous: evaluates attacker-controlled input
    matched = []
    for user in USERS:
        if eval(q):
            matched.append(user)
    return matched
