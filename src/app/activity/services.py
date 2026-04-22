from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta, date

from src.app.activity.model import UserActivity, UserActivityLog
from src.app.activity.schema import ActivityOut, DayCount
from src.app.user.model import User  # ✅ Fixed: top-level import instead of dynamic __import__

ACTIVE_WINDOW_HOURS = 24
SPARKLINE_DAYS = 30


async def _get_sparkline(db: AsyncSession, user_id: int) -> list[DayCount]:
    """Return daily action counts for the last SPARKLINE_DAYS days."""
    since = date.today() - timedelta(days=SPARKLINE_DAYS - 1)
    result = await db.execute(
        select(UserActivityLog)
        .where(
            UserActivityLog.user_id == user_id,
            UserActivityLog.date >= since,
        )
        .order_by(UserActivityLog.date.asc())
    )
    rows = result.scalars().all()
    count_map = {r.date: r.action_count for r in rows}

    sparkline: list[DayCount] = []
    for i in range(SPARKLINE_DAYS):
        d = since + timedelta(days=i)
        sparkline.append(DayCount(date=d, count=count_map.get(d, 0)))
    return sparkline


def _build_out_sync(record: UserActivity, sparkline: list[DayCount]) -> ActivityOut:
    """Build ActivityOut from a record + pre-fetched sparkline."""
    now = datetime.now(timezone.utc)
    last_seen = record.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    delta = now - last_seen
    is_active = delta <= timedelta(hours=ACTIVE_WINDOW_HOURS)
    days_ago = delta.days

    updated_at = record.updated_at
    if updated_at and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    return ActivityOut(
        user_id=record.user_id,
        last_seen=last_seen,
        last_action=record.last_action,
        updated_at=updated_at or last_seen,
        is_active=is_active,
        days_ago=days_ago,
        sparkline=sparkline,
    )


async def build_activity_out(db: AsyncSession, record: UserActivity) -> ActivityOut:
    sparkline = await _get_sparkline(db, record.user_id)
    return _build_out_sync(record, sparkline)


async def upsert_log(db: AsyncSession, user_id: int) -> None:
    """Increment today's action count in user_activity_log (upsert)."""
    today = date.today()
    result = await db.execute(
        select(UserActivityLog).where(
            UserActivityLog.user_id == user_id,
            UserActivityLog.date == today,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.action_count += 1
    else:
        db.add(UserActivityLog(user_id=user_id, date=today, action_count=1))
    await db.flush()


async def ping_user(
    db: AsyncSession,
    user_id: int,
    action: str = "active",
) -> ActivityOut:
    """Upsert the user_activity row and increment today's log count."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(UserActivity).where(UserActivity.user_id == user_id)
    )
    record = result.scalar_one_or_none()

    if record:
        record.last_seen = now
        record.last_action = action
        record.updated_at = now
    else:
        record = UserActivity(
            user_id=user_id,
            last_seen=now,
            last_action=action,
            updated_at=now,
        )
        db.add(record)

    await db.flush()
    await upsert_log(db, user_id)

    return await build_activity_out(db, record)


async def get_all_activity(db: AsyncSession) -> list[ActivityOut]:
    result = await db.execute(select(UserActivity))
    records = result.scalars().all()
    return [await build_activity_out(db, r) for r in records]


async def get_activity_by_user(db: AsyncSession, user_id: int) -> ActivityOut | None:
    result = await db.execute(
        select(UserActivity).where(UserActivity.user_id == user_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        return None
    return await build_activity_out(db, record)


async def get_activity_stats(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    cutoff_30 = now - timedelta(days=30)
    cutoff_24 = now - timedelta(hours=ACTIVE_WINDOW_HOURS)

    # ✅ Fixed: use the top-level User import
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar() or 0

    all_result = await db.execute(select(UserActivity))
    all_records = all_result.scalars().all()

    total_tracked = len(all_records)
    never_active = total_users - total_tracked
    active_30d = 0
    active_24h = 0

    for r in all_records:
        last_seen = r.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen >= cutoff_30:
            active_30d += 1
        if last_seen >= cutoff_24:
            active_24h += 1

    return {
        "total_users": total_users,
        "total_tracked": total_tracked,
        "never_active": never_active,
        "active_30d": active_30d,
        "active_24h": active_24h,
        "inactive": (total_tracked - active_30d) + never_active,
    }


async def get_new_users(db: AsyncSession) -> dict:
    """
    ✅ Fixed: use User.created_at to identify genuinely new users,
    not last_action which can be 'login' for a returning user.
    Also correctly separate google (no hashed_password) vs email signups.
    """
    NEW_USER_DAYS = 7
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=NEW_USER_DAYS)

    result = await db.execute(
        select(User).where(User.created_at >= cutoff)
    )
    new_users = result.scalars().all()

    new_ids: list[int] = []
    google_ids: list[int] = []
    email_ids: list[int] = []

    for u in new_users:
        new_ids.append(u.id)
        if u.hashed_password is None:
            google_ids.append(u.id)
        else:
            email_ids.append(u.id)

    return {
        "total_new": len(new_ids),
        "google_new": len(google_ids),
        "email_new": len(email_ids),
        "user_ids": new_ids,
        "window_days": NEW_USER_DAYS,
    }


async def backfill_activity(db: AsyncSession) -> dict:
    """Create a user_activity row for every user who doesn't have one yet."""
    result = await db.execute(select(User.id))
    user_ids = [row[0] for row in result.all()]

    existing_result = await db.execute(select(UserActivity.user_id))
    existing_ids = {row[0] for row in existing_result.all()}

    created = 0
    now = datetime.now(timezone.utc)
    for uid in user_ids:
        if uid not in existing_ids:
            db.add(UserActivity(
                user_id=uid,
                last_seen=now,
                last_action="backfill",
                updated_at=now,
            ))
            created += 1

    await db.flush()
    return {"backfilled": created, "message": f"Created {created} missing activity rows"}