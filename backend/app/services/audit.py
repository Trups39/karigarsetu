from sqlmodel import Session

from ..core.models import AuditLog


def log(
    session: Session,
    actor: str,
    action: str,
    detail: str = "",
    maker_id: int | None = None,
    order_code: str | None = None,
) -> None:
    session.add(AuditLog(actor=actor, action=action, detail=detail, maker_id=maker_id, order_code=order_code))
