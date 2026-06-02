from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from config import settings
from models.base import Base

db_path = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    from models import Character, Project, SceneAsset, Shot  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Small additive migration for existing local SQLite databases."""
    inspector = inspect(engine)
    if "shots" in inspector.get_table_names():
        _add_missing_columns(
            "shots",
            {
                "confirmed": "BOOLEAN DEFAULT 0",
                "parent_version_id": "VARCHAR DEFAULT ''",
                "scene_asset_id": "VARCHAR DEFAULT ''",
                "character_asset_ids": "TEXT DEFAULT '[]'",
                "storyboard_path": "VARCHAR DEFAULT ''",
                "storyboard_status": "VARCHAR DEFAULT 'pending'",
                "video_path": "VARCHAR DEFAULT ''",
                "visual_notes": "TEXT DEFAULT ''",
                "scene_group_id": "VARCHAR DEFAULT ''",
                "consistency_context": "TEXT DEFAULT ''",
                "reference_weights": "TEXT DEFAULT '{}'",
                "continuity_profile": "TEXT DEFAULT '{}'",
                "continuity_reference_path": "VARCHAR DEFAULT ''",
                "pose_reference_path": "VARCHAR DEFAULT ''",
                "depth_reference_path": "VARCHAR DEFAULT ''",
                "last_frame_path": "VARCHAR DEFAULT ''",
            },
        )
    if "projects" in inspector.get_table_names():
        _add_missing_columns(
            "projects",
            {
                "output_format": "VARCHAR DEFAULT '9:16'",
                "resolution": "VARCHAR DEFAULT '1080p'",
                "platform": "VARCHAR DEFAULT 'douyin'",
                "parent_project_id": "VARCHAR DEFAULT ''",
                "project_type": "VARCHAR DEFAULT 'series'",
                "episode_number": "INTEGER DEFAULT 0",
                "consistency_config": "TEXT DEFAULT '{}'",
            },
        )
    if "characters" in inspector.get_table_names():
        _add_missing_columns(
            "characters",
            {
                "reference_images": "TEXT DEFAULT '[]'",
                "default_outfit": "TEXT DEFAULT ''",
                "lora_profile": "TEXT DEFAULT ''",
                "ip_adapter_profile": "TEXT DEFAULT ''",
                "wardrobe_lock": "TEXT DEFAULT ''",
            },
        )
    if "scene_assets" in inspector.get_table_names():
        _add_missing_columns(
            "scene_assets",
            {
                "scene_group_key": "VARCHAR DEFAULT ''",
                "time_of_day": "VARCHAR DEFAULT ''",
                "baseline_image_path": "VARCHAR DEFAULT ''",
                "consistency_profile": "TEXT DEFAULT '{}'",
                "prop_lock": "TEXT DEFAULT ''",
            },
        )


def _add_missing_columns(table: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns(table)}
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
