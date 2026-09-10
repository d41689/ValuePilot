from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.services import source_reconciliation as service


def test_policy_snapshot_loads_once_per_read_and_reloads_next_read(monkeypatch):
    loaded = []

    def load():
        value = object()
        loaded.append(value)
        return value

    monkeypatch.setattr(service, "load_resolved_value_line_mapping_spec", load)

    @service.with_reconciliation_policy_snapshot
    def read():
        first = service._resolved_mapping_spec()
        assert service._resolved_mapping_spec() is first
        return first

    assert read() is not read()
    assert len(loaded) == 2
    # Direct callers outside a product read retain their existing reload rule.
    assert service._resolved_mapping_spec() is not service._resolved_mapping_spec()


def test_policy_snapshot_resets_on_error_and_nested_reads_share_scope(monkeypatch):
    loaded = []

    def load():
        value = object()
        loaded.append(value)
        return value

    monkeypatch.setattr(service, "load_resolved_value_line_mapping_spec", load)

    @service.with_reconciliation_policy_snapshot
    def nested():
        return service._resolved_mapping_spec()

    @service.with_reconciliation_policy_snapshot
    def failing():
        assert nested() is service._resolved_mapping_spec()
        raise ValueError("read failed")

    with pytest.raises(ValueError, match="read failed"):
        failing()
    assert nested() is not loaded[0]
    assert len(loaded) == 2


def test_concurrent_product_reads_do_not_share_policy_snapshot(monkeypatch):
    barrier = Barrier(2)
    monkeypatch.setattr(service, "load_resolved_value_line_mapping_spec", object)

    @service.with_reconciliation_policy_snapshot
    def read(_):
        first = service._resolved_mapping_spec()
        barrier.wait(timeout=5)
        assert service._resolved_mapping_spec() is first
        return first

    with ThreadPoolExecutor(max_workers=2) as executor:
        left, right = executor.map(read, range(2))
    assert left is not right
