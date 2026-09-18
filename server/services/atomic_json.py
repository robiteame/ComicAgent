"""配置文件的安全读写：原子替换 + 进程内锁 + 损坏恢复。

复用 model_config_service 已验证的写入模式（同目录临时文件 -> flush -> fsync
-> os.replace），并补上两件在实践中必要的事：

- 同一路径的进程内锁：把「读 -> 改 -> 写」整段串行化，避免并发保存互相覆盖；
- 读取损坏 JSON 时记录警告，并把原文件备份成 .corrupt，而不是静默当成空配置。

写入失败时目标文件保持原样；日志只记录文件名，不记录配置内容。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def path_lock(path: str | Path) -> threading.RLock:
    """返回某个配置文件对应的进程内可重入锁（同一路径共用一把）。"""

    key = str(Path(path).expanduser().resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def atomic_write_text(path: str | Path, text: str, *, mode: int | None = None) -> Path:
    """原子写入文本：同目录临时文件 + fsync + os.replace。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        # 失败时只清理临时文件，原文件保持不变。
        temporary.unlink(missing_ok=True)
    return target


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    mode: int | None = None,
) -> Path:
    """原子写入 JSON，编码与缩进格式与既有配置文件保持一致。"""

    payload = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    return atomic_write_text(path, payload, mode=mode)


def backup_corrupt_file(path: str | Path) -> Path | None:
    """把损坏的配置文件移到 .corrupt 备份，成功返回备份路径。"""

    source = Path(path)
    if not source.exists():
        return None
    backup = source.with_name(f"{source.name}.corrupt")
    if backup.exists():
        backup = source.with_name(f"{source.name}.{uuid.uuid4().hex[:8]}.corrupt")
    try:
        os.replace(source, backup)
    except OSError:
        logger.warning("配置文件损坏且无法备份: %s", source.name)
        return None
    return backup


def read_json_file(path: str | Path, *, default: Any = None) -> Any:
    """读取 JSON 配置。

    文件不存在时返回 default；内容损坏时记录警告、备份为 .corrupt 并返回
    default，让调用方用默认配置继续运行而不是静默吞掉问题。
    """

    source = Path(path)
    if not source.exists():
        return default
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("配置文件无法读取 (%s): %s", source.name, type(exc).__name__)
        return default
    if not raw.strip():
        return default
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("配置文件 JSON 损坏，已备份为 .corrupt 并使用默认配置: %s", source.name)
        backup_corrupt_file(source)
        return default
