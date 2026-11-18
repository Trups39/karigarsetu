"""Database tables."""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrderStatus(str, Enum):
    awaiting_maker = "awaiting_maker"  # AI drafted it; maker must decide
    counter_offered = "counter_offered"  # maker proposed a change; retailer must reply
    approved = "approved"  # stock reserved, production booked
    in_production = "in_production"
    ready = "ready"
    delivered = "delivered"
    rejected = "rejected"


# Orders whose "to make" pairs still occupy production capacity
ACTIVE_PRODUCTION = (OrderStatus.approved, OrderStatus.in_production)


class Maker(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True, unique=True)  # digits only, with country code, e.g. 919800000001
    place: str = ""
    buffer_days: int = 3
    min_order: int = 20
    language: str = "Marathi"  # for fixed WhatsApp messages: Marathi, Hindi or English


class Retailer(SQLModel, table=True):
    """A shop that orders from makers (the customer)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True, unique=True)  # digits only, with country code
    city: str = ""
    language: str = ""  # preferred: Marathi, Hindi or English
    created_at: datetime = Field(default_factory=utcnow)


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    maker_id: int = Field(foreign_key="maker.id", index=True)
    code: str  # short id the AI uses, e.g. "classic"
    name: str
    price_per_pair: int  # rupees
    pairs_per_day: int = 5  # production capacity for this design
    sizes: str = "6,7,8,9,10"

    def size_list(self) -> list[int]:
        return [int(s) for s in self.sizes.split(",") if s.strip()]


class Stock(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("product_id", "size"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    size: int
    ready: int = 0


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "KS-1042"
    maker_id: int = Field(foreign_key="maker.id", index=True)
    product_id: int = Field(foreign_key="product.id")
    retailer_id: Optional[int] = Field(default=None, foreign_key="retailer.id", index=True)
    retailer_name: str
    retailer_phone: str
    city: str = ""
    language: str = ""
    price_per_pair: int
    status: OrderStatus = OrderStatus.awaiting_maker
    proposed_date: Optional[date] = None  # from the feasibility check
    due_date: Optional[date] = None  # agreed date (after approval or counter-offer)
    reserved_ready: int = 0  # pairs taken from stock on approval
    to_make: int = 0  # pairs booked into production on approval
    created_at: datetime = Field(default_factory=utcnow)


class OrderLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    size: int
    qty: int


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    maker_id: Optional[int] = Field(default=None, index=True)
    order_code: Optional[str] = Field(default=None, index=True)
    actor: str  # "AI agent", "System", "Maker", "Retailer"
    action: str  # short machine-readable verb, e.g. "order.approved"
    detail: str = ""


class Message(SQLModel, table=True):
    """Outbox and inbox of WhatsApp messages (stored even when WhatsApp sending is off)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    direction: str  # "in" or "out"
    phone: str = Field(index=True)
    body: str
    order_code: Optional[str] = None
    delivered: bool = False


class Conversation(SQLModel, table=True):
    """Agent chat memory, one row per agent and phone: "sales:<phone>" or "ops:<phone>" (JSON messages)."""

    phone: str = Field(primary_key=True)
    maker_id: Optional[int] = None
    history: str = "[]"
    updated_at: datetime = Field(default_factory=utcnow)


class MakerSession(SQLModel, table=True):
    """A logged-in supplier. token = SHA-256 of the token the browser holds (never the token itself)."""

    token: str = Field(primary_key=True)
    maker_id: int = Field(foreign_key="maker.id")
    created_at: datetime = Field(default_factory=utcnow)


class AccountStatus(str, Enum):
    pending = "pending"  # signed up, waiting for the KarigarSetu team
    approved = "approved"  # can log in; linked to a Maker
    rejected = "rejected"


class SupplierAccount(SQLModel, table=True):
    """Website login for a maker (supplier): email + password, approved by an admin."""

    __tablename__ = "supplier_account"
    id: Optional[int] = Field(default=None, primary_key=True)
    maker_id: Optional[int] = Field(default=None, foreign_key="maker.id", index=True)  # set on approval
    name: str  # the person's name
    business_name: str  # becomes Maker.name on approval
    craft: str = ""
    town: str = ""  # becomes Maker.place
    phone: str = Field(index=True, unique=True)  # WhatsApp number, digits with country code
    email: str = Field(index=True, unique=True)  # lowercase
    password_hash: str  # bcrypt
    status: AccountStatus = AccountStatus.pending
    failed_logins: int = 0
    locked_until: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    reviewed_at: Optional[datetime] = None


class ContactMessage(SQLModel, table=True):
    """Messages from the website contact form (also emailed to CONTACT_TO)."""

    __tablename__ = "contact_message"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
    phone: str = ""
    message: str
    emailed: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class AdminSession(SQLModel, table=True):
    __tablename__ = "admin_session"
    token: str = Field(primary_key=True)  # SHA-256 of the cookie value
    created_at: datetime = Field(default_factory=utcnow)
