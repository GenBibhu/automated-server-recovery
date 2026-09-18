"""
Demo FastAPI service for an AI-agent deployment-recovery presentation.

Current deployment version is read from deployment_state.txt on each
request so the demo can switch v1 ↔ v2 without restarting Uvicorn.

v1 → /health returns 200 (healthy)
v2 → /health returns 500 (simulated bad deployment)
Other endpoints keep working in both versions.
"""

from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Project-root state file; edited live during the recovery demo.
STATE_FILE = Path(__file__).resolve().parent.parent / "deployment_state.txt"

app = FastAPI(
    title="Deployment Recovery Demo API",
    description="Small demo service used to simulate healthy vs failed deployments.",
    version="1.0.0",
)


def get_deployment_version() -> str:
    """Read the live deployment version from disk (no process restart needed)."""
    try:
        if not STATE_FILE.is_file():
            return "v1"
        version = STATE_FILE.read_text(encoding="utf-8").strip()
        return version or "v1"
    except OSError:
        return "v1"


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
    user_id: int = Field(..., gt=0, description="ID of the user placing the order")
    product: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)


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
    """
    Health check used by deployment / recovery demos.

    When deployment_state.txt is v2, this intentionally fails so agents
    can detect and roll back a bad deploy — without restarting Uvicorn.
    """
    version = get_deployment_version()

    if version == "v2":
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "unhealthy",
                "version": "v2",
                "reason": "simulated deployment failure",
            },
        )

    return {"status": "healthy", "version": version}


@app.get("/version", response_model=VersionResponse)
def version():
    return {"version": get_deployment_version()}


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
def list_orders():
    return ORDERS


@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: int):
    for order in ORDERS:
        if order.id == order_id:
            return order
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


@app.post("/api/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate):
    global _next_order_id

    # Ensure the referenced user exists (keeps the demo data consistent).
    if not any(user.id == payload.user_id for user in USERS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} not found",
        )

    order = Order(
        id=_next_order_id,
        user_id=payload.user_id,
        product=payload.product,
        amount=payload.amount,
        status="pending",
    )
    _next_order_id += 1
    ORDERS.append(order)
    return order
