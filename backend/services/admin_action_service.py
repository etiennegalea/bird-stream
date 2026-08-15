from sqlalchemy import select
from sqlalchemy.orm import joinedload

from models.orm import AdminAction


def record_admin_action(
    session,
    admin_user_id: int,
    action_type: str,
    target_type: str,
    target_id: str | int | None = None,
    details: dict | None = None,
) -> AdminAction:
    """Append an audit row. The caller owns and commits the transaction."""
    action = AdminAction(
        admin_user_id=admin_user_id,
        action_type=action_type[:80],
        target_type=target_type[:40],
        target_id=str(target_id)[:255] if target_id is not None else None,
        details=details or None,
    )
    session.add(action)
    return action


def record_admin_action_with_factory(db_factory, **kwargs) -> None:
    with db_factory() as session:
        record_admin_action(session, **kwargs)
        session.commit()


def list_admin_actions(db_factory, limit: int = 100) -> list[dict]:
    with db_factory() as session:
        rows = session.execute(
            select(AdminAction)
            .options(joinedload(AdminAction.admin))
            .order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
            .limit(max(1, min(limit, 500)))
        ).scalars().all()
        return [
            {
                "id": action.id,
                "admin_user_id": action.admin_user_id,
                "admin_username": action.admin.username if action.admin else None,
                "action_type": action.action_type,
                "target_type": action.target_type,
                "target_id": action.target_id,
                "details": action.details,
                "created_at": action.created_at.isoformat(),
            }
            for action in rows
        ]
