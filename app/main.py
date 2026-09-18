"""
Demo FastAPI service for an AI-agent deployment-recovery presentation.

APP_VERSION=v1 → /health returns 200 (healthy)
APP_VERSION=v2 → /health returns 500 (simulated bad deployment)
Other endpoints keep working in both versions.
"""

import os
from typing import List

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

APP_VERSION = os.getenv("APP_VERSION", "v1")

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

    APP_VERSION=v2 intentionally fails so agents can detect and roll back
    a bad deploy (a new process started with APP_VERSION=v1).
    """
    if APP_VERSION == "v2":
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "unhealthy",
                "version": "v2",
                "reason": "simulated deployment failure",
            },
        )

    return {"status": "healthy", "version": APP_VERSION}


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
