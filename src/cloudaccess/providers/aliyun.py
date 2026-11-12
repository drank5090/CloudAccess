"""阿里云适配器：ECS（云服务器）+ SWAS（轻量应用服务器）。

- ECS：安全组（Security Group）管理，使用中心化区域枚举 + 分区域客户端；
  放通规则为 IpProtocol=ALL / PortRange=-1/-1 的入方向规则。
- SWAS：防火墙（Firewall）管理，TCP/UDP 各建 1/65535 全端口规则；
  区域复用 ECS 区域列表逐个探测，不可用区域自动跳过。
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_swas_open20200601 import models as swas_models
from alibabacloud_swas_open20200601.client import Client as SwasClient
from alibabacloud_tea_openapi import models as open_api_models
from Tea.exceptions import TeaException

from ..errors import CredentialsInvalidError, FirewallOpError, ProviderError
from ..models import CloudVendor, FirewallRuleInfo, ServerInfo, ServerKind
from .base import CloudProvider

_ECS_ENDPOINT_FMT = "ecs.{region}.aliyuncs.com"
_SWAS_ENDPOINT_FMT = "swas.{region}.aliyuncs.com"
_REGION_BOOTSTRAP = "cn-hangzhou"
_PAGE_SIZE = 100
_MAX_WORKERS = 8

_INVALID_CRED_HINTS = ("InvalidAccessKeyId", "SignatureDoesNotMatch", "Forbidden.RAM")


def _tea_message(exc: TeaException) -> str:
    data = getattr(exc, "data", None)
    if isinstance(data, dict):
        return str(data.get("Message") or data.get("message") or exc)
    return str(exc.message or exc)


def _region_ids(body: Any) -> list[str]:
    """从 DescribeRegions 响应体安全取出区域 ID 列表。

    SDK 结构：``body.regions`` 是包装对象（DescribeRegionsResponseBodyRegions），
    真正的列表在 ``body.regions.region``；直接对 ``body.regions`` 做 len()/迭代
    会抛 ``TypeError: object of type ... has no len()``。
    """
    regions = getattr(body, "regions", None)
    if regions is None:
        return []
    items = getattr(regions, "region", None) or []
    return [str(r.region_id) for r in items if getattr(r, "region_id", None)]


class AliyunProvider(CloudProvider):
    """阿里云（ECS + 轻量应用服务器）。"""

    vendor = CloudVendor.ALIYUN

    # ---------- 客户端 ----------

    def _ecs_client(self, region: str) -> EcsClient:
        config = open_api_models.Config(
            access_key_id=self._ak,
            access_key_secret=self._sk,
            region_id=region,
            endpoint=_ECS_ENDPOINT_FMT.format(region=region),
        )
        return EcsClient(config)

    def _swas_client(self, region: str) -> SwasClient:
        config = open_api_models.Config(
            access_key_id=self._ak,
            access_key_secret=self._sk,
            region_id=region,
            endpoint=_SWAS_ENDPOINT_FMT.format(region=region),
        )
        return SwasClient(config)

    @staticmethod
    def _is_invalid_credentials(exc: TeaException) -> bool:
        msg = _tea_message(exc)
        return any(hint in msg for hint in _INVALID_CRED_HINTS)

    # ---------- 在线验证 ----------

    def validate_credentials(self) -> str:
        try:
            req = ecs_models.DescribeRegionsRequest()
            resp = self._ecs_client(_REGION_BOOTSTRAP).describe_regions(req)
            count = len(_region_ids(resp.body))
        except TeaException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("阿里云", f"凭据无效：{_tea_message(exc)}") from exc
            raise ProviderError("阿里云", f"区域列表获取失败：{_tea_message(exc)}") from exc
        return f"阿里云 · {count} 个可用区域"

    # ---------- 服务器列表 ----------

    def list_servers(self) -> list[ServerInfo]:
        region_ids = self._list_regions()
        servers: list[ServerInfo] = []
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = [pool.submit(self._list_region_servers, r) for r in region_ids]
            for fut in futures:
                servers.extend(fut.result())
        return servers

    def _list_regions(self) -> list[str]:
        try:
            req = ecs_models.DescribeRegionsRequest()
            resp = self._ecs_client(_REGION_BOOTSTRAP).describe_regions(req)
            return _region_ids(resp.body)
        except TeaException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("阿里云", f"凭据无效：{_tea_message(exc)}") from exc
            raise ProviderError("阿里云", f"区域列表获取失败：{_tea_message(exc)}") from exc

    def _list_region_servers(self, region: str) -> list[ServerInfo]:
        servers: list[ServerInfo] = []
        # ECS
        try:
            page = 1
            while True:
                req = ecs_models.DescribeInstancesRequest(
                    region_id=region, page_size=_PAGE_SIZE, page_number=page
                )
                resp = self._ecs_client(region).describe_instances(req)
                instances = resp.body.instances.instance or []
                for inst in instances:
                    servers.append(self._ecs_to_server(region, inst))
                total = int(resp.body.total_count or 0)
                if page * _PAGE_SIZE >= total or not instances:
                    break
                page += 1
        except TeaException as exc:
            if self._is_invalid_credentials(exc):
                raise
            # 单区域失败不阻塞整体列表
        # SWAS 轻量应用服务器（区域不支持时静默跳过）
        try:
            swas = self._swas_client(region)
            page = 1
            while True:
                req = swas_models.ListInstancesRequest(page_number=page, page_size=_PAGE_SIZE)
                resp = swas.list_instances(req)
                instances = resp.body.instances or []
                for inst in instances:
                    servers.append(self._swas_to_server(region, inst))
                total = int(resp.body.total_count or 0)
                if page * _PAGE_SIZE >= total or not instances:
                    break
                page += 1
        except Exception:  # noqa: BLE001 — 区域无 SWAS 服务等一律跳过
            pass
        return servers

    def _ecs_to_server(self, region: str, inst: Any) -> ServerInfo:
        public_ips = [ip for ip in (inst.public_ip_address or []) if ip]
        if not public_ips and inst.eip_address and inst.eip_address.ip_address:
            public_ips = [inst.eip_address.ip_address]
        return ServerInfo(
            instance_id=inst.instance_id,
            name=inst.instance_name or inst.instance_id,
            region=region,
            public_ip=public_ips[0] if public_ips else "",
            kind=ServerKind.ECS,
            extra={"security_group_ids": ",".join(inst.security_group_ids or [])},
        )

    def _swas_to_server(self, region: str, inst: Any) -> ServerInfo:
        return ServerInfo(
            instance_id=inst.instance_id,
            name=inst.instance_name or inst.instance_id,
            region=region,
            public_ip=inst.public_ip_address or "",
            kind=ServerKind.LIGHTHOUSE,
        )

    # ---------- 防火墙规则 ----------

    def _ecs_rules(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        req = ecs_models.DescribeSecurityGroupAttributeRequest(
            region_id=region, security_group_id=sg_id, direction="ingress", page_size=_PAGE_SIZE
        )
        resp = self._ecs_client(region).describe_security_group_attribute(req)
        rules: list[FirewallRuleInfo] = []
        for p in resp.body.permissions.permission or []:
            desc = p.description or ""
            rules.append(
                FirewallRuleInfo(
                    rule_id=sg_id,
                    protocol=str(p.ip_protocol or ""),
                    port=str(p.port_range or ""),
                    source_cidr=str(p.source_cidr_ip or ""),
                    description=desc,
                    is_created_by_app=desc.startswith("CA|"),
                )
            )
        return rules

    def _swas_rules(self, region: str, instance_id: str) -> list[FirewallRuleInfo]:
        req = swas_models.ListFirewallRulesRequest(instance_id=instance_id)
        resp = self._swas_client(region).list_firewall_rules(req)
        rules: list[FirewallRuleInfo] = []
        for r in resp.body.firewall_rules or []:
            remark = r.remark or ""
            rules.append(
                FirewallRuleInfo(
                    rule_id=str(r.rule_id),
                    protocol=str(r.rule_protocol or ""),
                    port=str(r.port or ""),
                    source_cidr=str(r.source_cidr_ip or ""),
                    description=remark,
                    is_created_by_app=remark.startswith("CA|"),
                )
            )
        return rules

    def attach_firewall_rules(self, servers: list[ServerInfo]) -> None:
        """为服务器列表补充防火墙规则（ECS 安全组去重查询）。"""
        sg_cache: dict[tuple[str, str], list[FirewallRuleInfo]] = {}
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {}
            for s in servers:
                if s.kind is ServerKind.ECS:
                    for sg in self._sg_ids(s):
                        key = (s.region, sg)
                        if key not in futures and key not in sg_cache:
                            futures[key] = pool.submit(self._fetch_ecs_rules_safe, *key)
                else:
                    futures[(s.region, f"swas:{s.instance_id}")] = pool.submit(
                        self._fetch_swas_rules_safe, s.region, s.instance_id
                    )
            for s in servers:
                if s.kind is ServerKind.ECS:
                    for sg in self._sg_ids(s):
                        key = (s.region, sg)
                        if key not in sg_cache:
                            sg_cache[key] = futures[key].result()
                        s.firewall_rules.extend(sg_cache[key])
                else:
                    key = (s.region, f"swas:{s.instance_id}")
                    s.firewall_rules.extend(futures[key].result())

    def _fetch_ecs_rules_safe(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        try:
            return self._ecs_rules(region, sg_id)
        except TeaException:
            return []

    def _fetch_swas_rules_safe(self, region: str, instance_id: str) -> list[FirewallRuleInfo]:
        try:
            return self._swas_rules(region, instance_id)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _sg_ids(server: ServerInfo) -> list[str]:
        raw = server.extra.get("security_group_ids", "")
        return [x for x in raw.split(",") if x]

    # ---------- 授权 / 撤销 ----------

    def authorize(self, server: ServerInfo, cidr: str, marker: str) -> None:
        try:
            if server.kind is ServerKind.ECS:
                for sg in self._sg_ids(server):
                    self._ecs_authorize(server.region, sg, cidr, marker)
            else:
                self._swas_authorize(server.region, server.instance_id, cidr, marker)
        except TeaException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("阿里云", _tea_message(exc)) from exc
            raise FirewallOpError("阿里云", f"授权失败：{_tea_message(exc)}") from exc

    def _ecs_authorize(self, region: str, sg_id: str, cidr: str, marker: str) -> None:
        existing = self._ecs_rules(region, sg_id)
        for r in existing:
            if r.is_created_by_app and r.description == marker:
                return  # 已存在完全相同的规则
        req = ecs_models.AuthorizeSecurityGroupRequest(
            region_id=region,
            security_group_id=sg_id,
            ip_protocol="ALL",
            port_range="-1/-1",
            source_cidr_ip=cidr,
            description=marker,
            policy="accept",
            priority="1",
        )
        self._ecs_client(region).authorize_security_group(req)

    def _swas_authorize(self, region: str, instance_id: str, cidr: str, marker: str) -> None:
        existing = self._swas_rules(region, instance_id)
        protocols = []
        for proto, port in (("TCP", "1/65535"), ("UDP", "1/65535")):
            if any(
                r.is_created_by_app and r.description == marker and r.protocol == proto for r in existing
            ):
                continue
            protocols.append(
                swas_models.CreateFirewallRulesRequestFirewallRules(
                    rule_protocol=proto, port=port, source_cidr_ip=cidr, remark=marker
                )
            )
        if protocols:
            req = swas_models.CreateFirewallRulesRequest(
                instance_id=instance_id, firewall_rules=protocols
            )
            self._swas_client(region).create_firewall_rules(req)

    def revoke(self, server: ServerInfo, marker_prefix: str) -> None:
        try:
            if server.kind is ServerKind.ECS:
                for sg in self._sg_ids(server):
                    self._ecs_revoke(server.region, sg, marker_prefix)
            else:
                self._swas_revoke(server.region, server.instance_id, marker_prefix)
        except TeaException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("阿里云", _tea_message(exc)) from exc
            raise FirewallOpError("阿里云", f"撤销授权失败：{_tea_message(exc)}") from exc

    def _ecs_revoke(self, region: str, sg_id: str, marker_prefix: str) -> None:
        for r in self._ecs_rules(region, sg_id):
            if not r.description.startswith(marker_prefix):
                continue
            req = ecs_models.RevokeSecurityGroupRequest(
                region_id=region,
                security_group_id=sg_id,
                ip_protocol=r.protocol,
                port_range=r.port,
                source_cidr_ip=r.source_cidr,
                description=r.description,
                policy="accept",
            )
            self._ecs_client(region).revoke_security_group(req)

    def _swas_revoke(self, region: str, instance_id: str, marker_prefix: str) -> None:
        rules = [r for r in self._swas_rules(region, instance_id) if r.description.startswith(marker_prefix)]
        if not rules:
            return
        req = swas_models.DeleteFirewallRulesRequest(
            instance_id=instance_id,
            rule_ids=[r.rule_id for r in rules],
        )
        self._swas_client(region).delete_firewall_rules(req)
