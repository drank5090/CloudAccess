"""华为云适配器：ECS（含云耀云服务器 HECS/L 实例）。

- 区域/项目：通过 IAM ``keystone_list_projects`` 获取账号全部项目（项目名即区域 ID）；
- 服务器：ECS ListServersDetails 分页查询；
- 防火墙：VPC v2 安全组规则。放通 = 为 tcp/udp/icmp 各建一条"全端口"入方向规则
  （华为云安全组规则的端口区间留空即代表该协议所有端口）。
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions.exceptions import SdkException
from huaweicloudsdkecs.v2 import ListServersDetailsRequest
from huaweicloudsdkiam.v3 import model as iam_models
from huaweicloudsdkiam.v3.iam_client import IamClient
from huaweicloudsdkvpc.v2 import model as vpc_models
from huaweicloudsdkvpc.v2.vpc_client import VpcClient

from ..errors import CredentialsInvalidError, FirewallOpError, ProviderError
from ..models import CloudVendor, FirewallRuleInfo, ServerInfo, ServerKind
from .base import CloudProvider

_IAM_ENDPOINT = "https://iam.myhuaweicloud.com"
_PAGE_SIZE = 200
_MAX_WORKERS = 8

_UNAUTHORIZED_HINTS = ("401", "403", " unauthorized", "forbidden", "signature")


def _err_message(exc: SdkException) -> str:
    return str(getattr(exc, "error_msg", None) or exc)


def _is_invalid_credentials(exc: SdkException) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    msg = _err_message(exc).lower()
    return any(h in msg for h in _UNAUTHORIZED_HINTS)


class HuaweiProvider(CloudProvider):
    """华为云（ECS / 云耀云服务器）。"""

    vendor = CloudVendor.HUAWEI

    # ---------- 客户端 ----------

    def _cred(self, project_id: str = "") -> BasicCredentials:
        cred = BasicCredentials(self._ak, self._sk)
        return cred.with_project_id(project_id) if project_id else cred

    def _iam(self) -> IamClient:
        return IamClient.new_builder().with_credentials(self._cred()).with_endpoint(_IAM_ENDPOINT).build()

    def _ecs(self, region: str, project_id: str) -> EcsClient:
        endpoint = f"https://ecs.{region}.myhuaweicloud.com"
        return EcsClient.new_builder().with_credentials(self._cred(project_id)).with_endpoint(endpoint).build()

    def _vpc(self, region: str, project_id: str) -> VpcClient:
        endpoint = f"https://vpc.{region}.myhuaweicloud.com"
        return VpcClient.new_builder().with_credentials(self._cred(project_id)).with_endpoint(endpoint).build()

    # ---------- 在线验证 ----------

    def validate_credentials(self) -> str:
        try:
            resp = self._iam().keystone_list_projects(iam_models.KeystoneListProjectsRequest())
            count = len(resp.projects or [])
        except SdkException as exc:
            if _is_invalid_credentials(exc):
                raise CredentialsInvalidError("华为云", f"凭据无效：{_err_message(exc)}") from exc
            raise ProviderError("华为云", f"项目列表获取失败：{_err_message(exc)}") from exc
        if count == 0:
            raise CredentialsInvalidError("华为云", "凭据有效但账号下没有任何区域项目")
        return f"华为云 · {count} 个区域项目"

    # ---------- 服务器列表 ----------

    def list_servers(self) -> list[ServerInfo]:
        projects = self._list_projects()
        servers: list[ServerInfo] = []
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = [pool.submit(self._list_project_servers, p) for p in projects]
            for fut in futures:
                servers.extend(fut.result())
        return servers

    def _list_projects(self) -> list[tuple[str, str]]:
        """返回 (region, project_id) 列表。"""
        try:
            resp = self._iam().keystone_list_projects(iam_models.KeystoneListProjectsRequest())
        except SdkException as exc:
            if _is_invalid_credentials(exc):
                raise CredentialsInvalidError("华为云", f"凭据无效：{_err_message(exc)}") from exc
            raise ProviderError("华为云", f"项目列表获取失败：{_err_message(exc)}") from exc
        result: list[tuple[str, str]] = []
        for p in resp.projects or []:
            region = getattr(p, "name", "") or ""
            pid = getattr(p, "id", "") or ""
            if region and pid:
                result.append((region, pid))
        return result

    def _list_project_servers(self, project: tuple[str, str]) -> list[ServerInfo]:
        region, project_id = project
        servers: list[ServerInfo] = []
        try:
            offset = 0
            while True:
                req = ListServersDetailsRequest(limit=_PAGE_SIZE, offset=offset)
                resp = self._ecs(region, project_id).list_servers_details(req)
                for s in resp.servers or []:
                    servers.append(self._to_server(region, s))
                count = len(resp.servers or [])
                offset += _PAGE_SIZE
                if count < _PAGE_SIZE:
                    break
        except SdkException as exc:
            if _is_invalid_credentials(exc):
                raise
            # 单区域失败不阻塞整体列表
        return servers

    def _to_server(self, region: str, s: Any) -> ServerInfo:
        public_ip = getattr(s, "access_i_pv4", "") or ""
        return ServerInfo(
            instance_id=s.id,
            name=s.name or s.id,
            region=region,
            public_ip=public_ip,
            kind=ServerKind.ECS,
            extra={"security_group_ids": self._sg_ids_of(s)},
        )

    @staticmethod
    def _sg_ids_of(s: Any) -> str:
        groups = getattr(s, "security_groups", None) or []
        ids: list[str] = []
        for g in groups:
            gid = getattr(g, "id", None) or getattr(g, "security_group_id", None) or ""
            if gid:
                ids.append(str(gid))
        return ",".join(ids)

    # ---------- 防火墙规则 ----------

    def attach_firewall_rules(self, servers: list[ServerInfo]) -> None:
        """为服务器列表补充防火墙规则（安全组去重查询）。"""
        cache: dict[tuple[str, str], list[FirewallRuleInfo]] = {}
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures: dict[tuple[str, str], Any] = {}
            for s in servers:
                for sg in self._sg_ids(s):
                    key = (s.region, sg)
                    if key not in futures:
                        futures[key] = pool.submit(self._fetch_rules_safe, s.region, sg)
            for s in servers:
                for sg in self._sg_ids(s):
                    key = (s.region, sg)
                    if key not in cache:
                        cache[key] = futures[key].result()
                    s.firewall_rules.extend(cache[key])

    def _fetch_rules_safe(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        try:
            return self._sg_rules_by_id(region, sg_id)
        except SdkException:
            return []

    def _sg_rules_by_id(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        # project_id 需按区域解析：同区域项目唯一，直接借助 IAM 解析结果缓存
        project_id = self._project_of_region(region)
        req = vpc_models.ListSecurityGroupRulesRequest()
        req.security_group_id = sg_id
        req.limit = _PAGE_SIZE
        rules: list[FirewallRuleInfo] = []
        marker: str | None = None
        while True:
            resp = self._vpc(region, project_id).list_security_group_rules(req)
            items = getattr(resp, "security_group_rules", None) or []
            for r in items:
                desc = r.description or ""
                port_min, port_max = r.port_range_min, r.port_range_max
                port = "ALL" if port_min is None and port_max is None else f"{port_min}/{port_max}"
                rules.append(
                    FirewallRuleInfo(
                        rule_id=r.id,
                        protocol=(r.protocol or "ALL").upper(),
                        port=port,
                        source_cidr=r.remote_ip_prefix or "",
                        description=desc,
                        is_created_by_app=desc.startswith("CA|"),
                    )
                )
            if len(items) < _PAGE_SIZE:
                break
            marker = getattr(resp, "marker", None)  # 极少情况分页
            if not marker:
                break
            req.marker = marker
        return rules

    def _project_of_region(self, region: str) -> str:
        if not hasattr(self, "_region_project_cache"):
            self._region_project_cache: dict[str, str] = {}
            for r, pid in self._list_projects():
                self._region_project_cache[r] = pid
        return self._region_project_cache[region]

    # ---------- 授权 / 撤销 ----------

    def authorize(self, server: ServerInfo, cidr: str, marker: str) -> None:
        try:
            project_id = self._project_of_region(server.region)
            for sg in self._sg_ids(server):
                self._authorize_sg(server.region, project_id, sg, cidr, marker)
        except SdkException as exc:
            if _is_invalid_credentials(exc):
                raise CredentialsInvalidError("华为云", _err_message(exc)) from exc
            raise FirewallOpError("华为云", f"授权失败：{_err_message(exc)}") from exc

    def _authorize_sg(self, region: str, project_id: str, sg_id: str, cidr: str, marker: str) -> None:
        existing = self._sg_rules_by_id(region, sg_id)
        needed = [p for p in ("tcp", "udp", "icmp") if not self._has_rule(existing, p, cidr, marker)]
        for proto in needed:
            option = vpc_models.CreateSecurityGroupRuleOption(
                security_group_id=sg_id,
                direction="ingress",
                ethertype="IPv4",
                protocol=proto,
                remote_ip_prefix=cidr,
                description=marker,
                # port_range_min/max 留空 = 该协议全部端口
            )
            body = vpc_models.CreateSecurityGroupRuleRequestBody(security_group_rule=option)
            req = vpc_models.CreateSecurityGroupRuleRequest(body=body)
            self._vpc(region, project_id).create_security_group_rule(req)

    @staticmethod
    def _has_rule(rules: list[FirewallRuleInfo], protocol: str, cidr: str, marker: str) -> bool:
        return any(
            r.is_created_by_app and r.description == marker and r.protocol.lower() == protocol
            and r.source_cidr == cidr
            for r in rules
        )

    def revoke(self, server: ServerInfo, marker_prefix: str) -> None:
        try:
            project_id = self._project_of_region(server.region)
            for sg in self._sg_ids(server):
                rules = self._sg_rules_by_id(server.region, sg)
                targets = [r for r in rules if r.description.startswith(marker_prefix)]
                for r in targets:
                    req = vpc_models.DeleteSecurityGroupRuleRequest(security_group_rule_id=r.rule_id)
                    self._vpc(server.region, project_id).delete_security_group_rule(req)
        except SdkException as exc:
            if _is_invalid_credentials(exc):
                raise CredentialsInvalidError("华为云", _err_message(exc)) from exc
            raise FirewallOpError("华为云", f"撤销授权失败：{_err_message(exc)}") from exc
