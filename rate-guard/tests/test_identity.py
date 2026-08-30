from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest

from app.identity import load_or_create_instance_id


def test_identity_is_created_once_and_persists(tmp_path: Path) -> None:
    first = load_or_create_instance_id(tmp_path)
    second = load_or_create_instance_id(tmp_path)

    assert second == first
    assert str(uuid.UUID(first)) == first
    identity_path = tmp_path / "instance_id"
    assert identity_path.read_text(encoding="ascii").strip() == first
    assert os.stat(identity_path).st_mode & 0o777 == 0o600


def test_invalid_persisted_identity_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "instance_id").write_text("not-an-instance-id\n", encoding="ascii")

    with pytest.raises(RuntimeError, match="invalid Rate Guard instance identity"):
        load_or_create_instance_id(tmp_path)
