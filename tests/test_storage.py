"""账号存储测试（内存凭据仓库 + 临时数据目录）。"""

import json

import pytest

from cloudaccess.errors import AccountNotFoundError
from cloudaccess.models import CloudVendor
from cloudaccess.storage import AccountStore


def test_add_and_read_secrets(store, secrets):
    binding = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
    assert binding.vendor is CloudVendor.ALIYUN
    assert binding.name == "演示-阿里云账号"
    assert len(binding.short_id) == 8
    assert store.get_ak(binding) == "demo-ak-0001"
    assert store.get_sk(binding) == "demo-sk-0001"
    assert secrets.data[f"{binding.id}:ak"] == "demo-ak-0001"
    assert secrets.data[f"{binding.id}:sk"] == "demo-sk-0001"


def test_list_newest_first(store):
    first = store.add(CloudVendor.ALIYUN, "演示-一号", "demo-ak-0001", "demo-sk-0001")
    second = store.add(CloudVendor.TENCENT, "演示-二号", "demo-ak-0002", "demo-sk-0002")
    assert store.list() == [second, first]


def test_add_empty_name_falls_back_to_vendor_name(store):
    binding = store.add(CloudVendor.HUAWEI, "   ", "demo-ak-0001", "demo-sk-0001")
    assert binding.name == "华为云"


def test_update_name(store):
    binding = store.add(CloudVendor.ALIYUN, "演示-旧名", "demo-ak-0001", "demo-sk-0001")
    store.update_name(binding.id, "  演示-新名  ")
    assert store.get(binding.id).name == "演示-新名"
    store.update_name(binding.id, "   ")
    assert store.get(binding.id).name == "演示-新名"  # 空名不覆盖


def test_remove_deletes_secrets(store, secrets):
    binding = store.add(CloudVendor.ALIYUN, "演示-待删", "demo-ak-0001", "demo-sk-0001")
    store.remove(binding.id)
    assert store.list() == []
    assert store.get_ak(binding) == ""
    assert store.get_sk(binding) == ""
    assert not secrets.data
    with pytest.raises(AccountNotFoundError):
        store.get(binding.id)


def test_persistence_roundtrip(store, secrets):
    binding = store.add(CloudVendor.TENCENT, "演示-持久化", "demo-ak-0001", "demo-sk-0001")
    reopened = AccountStore(secrets=secrets, data_dir=str(store.path.parent))
    assert [b.id for b in reopened.list()] == [binding.id]
    assert reopened.get_sk(binding) == "demo-sk-0001"


def test_corrupted_metadata_is_ignored(store, secrets):
    store.add(CloudVendor.ALIYUN, "演示-损坏前", "demo-ak-0001", "demo-sk-0001")
    store.path.write_text("{ 这不是 JSON", encoding="utf-8")
    reopened = AccountStore(secrets=secrets, data_dir=str(store.path.parent))
    assert reopened.list() == []
    reopened.add(CloudVendor.ALIYUN, "演示-损坏后", "demo-ak-0002", "demo-sk-0002")
    assert len(reopened.list()) == 1


def test_metadata_file_never_contains_secrets(store):
    """元数据 JSON 只保存绑定信息，AK/SK 必须只存在于凭据服务。"""
    store.add(CloudVendor.ALIYUN, "演示-安全", "demo-ak-0001", "demo-sk-0001")
    raw = store.path.read_text(encoding="utf-8")
    assert "demo-ak-0001" not in raw
    assert "demo-sk-0001" not in raw
    items = json.loads(raw)
    assert list(items[0]) == ["id", "short_id", "vendor", "name", "created_at", "region_hint"]


def test_member_path_blocks_traversal(store):
    with pytest.raises(ValueError):
        store._member_path("../evil.json")
    with pytest.raises(ValueError):
        store._member_path("not-allowed.txt")
