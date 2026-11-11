"""腾讯云适配器：CVM（云服务器）+ Lighthouse（轻量应用服务器）。

- CVM：安全组由 VPC 模块管理，放通规则为 Protocol=ALL / Port=ALL 的入方向策略；
- Lighthouse：实例自带防火墙，放通规则为 Protocol=ALL / Port=ALL。

腾讯云 SDK 模型不支持构造器 kwargs，统一使用属性赋值。
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.cvm.v20170312 import cvm_client, models as cvm_models
from tencentcloud.lighthouse.v20200324 import lighthouse_client, models as lh_models
from tencentcloud.vpc.v20170312 import vpc_client, models as vpc_models

from ..errors import CredentialsInvalidError, FirewallOpError, ProviderError
from ..models import CloudVendor, FirewallRuleInfo, ServerInfo, ServerKind
from .base import CloudProvider

_BOOTSTRAP_REGION = "ap-guangzhou"
_PAGE_SIZE = 100
_MAX_WORKERS = 8

_INVALID_CRED_HINTS = ("AuthFailure.SignatureFailure", "AuthFailure.SignatureExpire",
                       "AuthFailure.SecretIdNotFound", "InvalidCredential")


def _err_message(exc: TencentCloudSDKException) -> str:
    return f"{exc.code}: {exc.message}" if exc.code else str(exc.message)


def _cvm_list_request(offset: int) -> cvm_models.DescribeInstancesRequest:
    req = cvm_models.DescribeInstancesRequest()
    req.Limit = _PAGE_SIZE
    req.Offset = offset
    return req


def _lh_list_request(offset: int) -> lh_models.DescribeInstancesRequest:
    req = lh_models.DescribeInstancesRequest()
    req.Limit = _PAGE_SIZE
    req.Offset = offset
    return req


def _sg_policy(protocol: str, port: str, cidr: str, policy: str, desc: str, ipv6: str = "") -> vpc_models.SecurityGroupPolicy:
    p = vpc_models.SecurityGroupPolicy()
    p.Protocol = protocol
    p.Port = port
    p.CidrBlock = cidr
    p.Ipv6CidrBlock = ipv6
    p.Policy = policy
    p.PolicyDescription = desc
    return p


def _lh_rule(protocol: str = "", port: str = "", cidr: str = "", desc: str = "",
             rule_id: str = "") -> lh_models.FirewallRule:
    r = lh_models.FirewallRule()
    r.FirewallRuleId = rule_id
    r.Protocol = protocol
    r.Port = port
    r.CidrBlock = cidr
    r.FirewallRuleDescription = desc
    return r


class TencentProvider(CloudProvider):
    """腾讯云（CVM + 轻量应用服务器 Lighthouse）。"""

    vendor = CloudVendor.TENCENT

    # ---------- 客户端 ----------

    def _cred(self) -> credential.Credential:
        return credential.Credential(self._ak, self._sk)

    def _cvm(self, region: str) -> cvm_client.CvmClient:
        return cvm_client.CvmClient(self._cred(), region)

    def _vpc(self, region: str) -> vpc_client.VpcClient:
        return vpc_client.VpcClient(self._cred(), region)

    def _lh(self, region: str) -> lighthouse_client.LighthouseClient:
        return lighthouse_client.LighthouseClient(self._cred(), region)

    @staticmethod
    def _is_invalid_credentials(exc: TencentCloudSDKException) -> bool:
        msg = _err_message(exc)
        return any(hint in msg for hint in _INVALID_CRED_HINTS)

    # ---------- 在线验证 ----------

    def validate_credentials(self) -> str:
        try:
            resp = self._cvm(_BOOTSTRAP_REGION).DescribeRegions(cvm_models.DescribeRegionsRequest())
            count = len(resp.RegionSet or [])
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("腾讯云", f"凭据无效：{_err_message(exc)}") from exc
            raise ProviderError("腾讯云", f"区域列表获取失败：{_err_message(exc)}") from exc
        return f"腾讯云 · {count} 个可用区域"

    # ---------- 服务器列表 ----------

    def list_servers(self) -> list[ServerInfo]:
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            f_cvm = pool.submit(self._cvm_regions)
            f_lh = pool.submit(self._lh_regions)
            cvm_regions = f_cvm.result()
            lh_regions = f_lh.result()

        servers: list[ServerInfo] = []
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = [pool.submit(self._list_cvm_region, r) for r in cvm_regions]
            futures += [pool.submit(self._list_lh_region, r) for r in lh_regions]
            for fut in futures:
                servers.extend(fut.result())
        return servers

    def _cvm_regions(self) -> list[str]:
        try:
            resp = self._cvm(_BOOTSTRAP_REGION).DescribeRegions(cvm_models.DescribeRegionsRequest())
            return [r.Region for r in (resp.RegionSet or [])]
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise
            return []

    def _lh_regions(self) -> list[str]:
        try:
            resp = self._lh(_BOOTSTRAP_REGION).DescribeRegions(lh_models.DescribeRegionsRequest())
            return [r.Region for r in (resp.RegionSet or [])]
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise
            return []

    def _list_cvm_region(self, region: str) -> list[ServerInfo]:
        servers: list[ServerInfo] = []
        try:
            offset = 0
            while True:
                resp = self._cvm(region).DescribeInstances(_cvm_list_request(offset))
                for inst in resp.InstanceSet or []:
                    servers.append(self._cvm_to_server(region, inst))
                offset += _PAGE_SIZE
                if offset >= (resp.TotalCount or 0) or not resp.InstanceSet:
                    break
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise
            # 单区域失败不阻塞整体列表
        return servers

    def _cvm_to_server(self, region: str, inst: Any) -> ServerInfo:
        public_ips = [ip for ip in (inst.PublicIpAddresses or []) if ip]
        return ServerInfo(
            instance_id=inst.InstanceId,
            name=inst.InstanceName or inst.InstanceId,
            region=region,
            region_name=inst.Placement.Zone if inst.Placement else "",
            public_ip=public_ips[0] if public_ips else "",
            kind=ServerKind.ECS,
            extra={"security_group_ids": ",".join(inst.SecurityGroupIds or [])},
        )

    def _list_lh_region(self, region: str) -> list[ServerInfo]:
        servers: list[ServerInfo] = []
        try:
            offset = 0
            while True:
                resp = self._lh(region).DescribeInstances(_lh_list_request(offset))
                for inst in resp.InstanceSet or []:
                    public_ips = [ip for ip in (inst.PublicAddresses or []) if ip]
                    servers.append(
                        ServerInfo(
                            instance_id=inst.InstanceId,
                            name=inst.InstanceName or inst.InstanceId,
                            region=region,
                            region_name=inst.Zone or "",
                            public_ip=public_ips[0] if public_ips else "",
                            kind=ServerKind.LIGHTHOUSE,
                        )
                    )
                offset += _PAGE_SIZE
                if offset >= (resp.TotalCount or 0) or not resp.InstanceSet:
                    break
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise
        return servers

    # ---------- 防火墙规则 ----------

    def attach_firewall_rules(self, servers: list[ServerInfo]) -> None:
        """为服务器列表补充防火墙规则。"""
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures: dict[tuple[str, str], Any] = {}
            for s in servers:
                if s.kind is ServerKind.ECS:
                    for sg in self._sg_ids(s):
                        key = (s.region, sg)
                        if key not in futures:
                            futures[key] = pool.submit(self._fetch_cvm_rules_safe, s.region, sg)
                else:
                    key = (s.region, s.instance_id)
                    if key not in futures:
                        futures[key] = pool.submit(self._fetch_lh_rules_safe, s.region, s.instance_id)
            for s in servers:
                if s.kind is ServerKind.ECS:
                    for sg in self._sg_ids(s):
                        s.firewall_rules.extend(futures[(s.region, sg)].result())
                else:
                    s.firewall_rules.extend(futures[(s.region, s.instance_id)].result())

    def _cvm_rules(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        req = vpc_models.DescribeSecurityGroupPoliciesRequest()
        req.SecurityGroupId = sg_id
        resp = self._vpc(region).DescribeSecurityGroupPolicies(req)
        policy_set = resp.SecurityGroupPolicySet
        rules: list[FirewallRuleInfo] = []
        for p in (policy_set.Ingress if policy_set else []) or []:
            desc = p.PolicyDescription or ""
            rules.append(
                FirewallRuleInfo(
                    rule_id=sg_id,
                    protocol=p.Protocol or "",
                    port=p.Port or "",
                    source_cidr=p.CidrBlock or p.Ipv6CidrBlock or "",
                    description=desc,
                    is_created_by_app=desc.startswith("CA|"),
                )
            )
        return rules

    def _lh_rules(self, region: str, instance_id: str) -> list[FirewallRuleInfo]:
        req = lh_models.DescribeFirewallRulesRequest()
        req.InstanceId = instance_id
        resp = self._lh(region).DescribeFirewallRules(req)
        rules: list[FirewallRuleInfo] = []
        for r in resp.FirewallRuleSet or []:
            desc = r.FirewallRuleDescription or ""
            rules.append(
                FirewallRuleInfo(
                    rule_id=r.FirewallRuleId,
                    protocol=r.Protocol or "",
                    port=r.Port or "",
                    source_cidr=r.CidrBlock or "",
                    description=desc,
                    is_created_by_app=desc.startswith("CA|"),
                )
            )
        return rules

    def _fetch_cvm_rules_safe(self, region: str, sg_id: str) -> list[FirewallRuleInfo]:
        try:
            return self._cvm_rules(region, sg_id)
        except TencentCloudSDKException:
            return []

    def _fetch_lh_rules_safe(self, region: str, instance_id: str) -> list[FirewallRuleInfo]:
        try:
            return self._lh_rules(region, instance_id)
        except TencentCloudSDKException:
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
                    self._cvm_authorize(server.region, sg, cidr, marker)
            else:
                self._lh_authorize(server.region, server.instance_id, cidr, marker)
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("腾讯云", _err_message(exc)) from exc
            raise FirewallOpError("腾讯云", f"授权失败：{_err_message(exc)}") from exc

    def _cvm_authorize(self, region: str, sg_id: str, cidr: str, marker: str) -> None:
        existing = self._cvm_rules(region, sg_id)
        if any(r.is_created_by_app and r.description == marker for r in existing):
            return  # 已存在完全相同的规则
        policy_set = vpc_models.SecurityGroupPolicySet()
        policy_set.Ingress = [_sg_policy("ALL", "ALL", cidr, "ACCEPT", marker)]
        req = vpc_models.CreateSecurityGroupPoliciesRequest()
        req.SecurityGroupId = sg_id
        req.SecurityGroupPolicySet = policy_set
        self._vpc(region).CreateSecurityGroupPolicies(req)

    def _lh_authorize(self, region: str, instance_id: str, cidr: str, marker: str) -> None:
        existing = self._lh_rules(region, instance_id)
        if any(r.is_created_by_app and r.description == marker for r in existing):
            return  # 已存在完全相同的规则
        req = lh_models.CreateFirewallRulesRequest()
        req.InstanceId = instance_id
        req.FirewallRuleSet = [_lh_rule("ALL", "ALL", cidr, marker)]
        self._lh(region).CreateFirewallRules(req)

    def revoke(self, server: ServerInfo, marker_prefix: str) -> None:
        try:
            if server.kind is ServerKind.ECS:
                for sg in self._sg_ids(server):
                    self._cvm_revoke(server.region, sg, marker_prefix)
            else:
                self._lh_revoke(server.region, server.instance_id, marker_prefix)
        except TencentCloudSDKException as exc:
            if self._is_invalid_credentials(exc):
                raise CredentialsInvalidError("腾讯云", _err_message(exc)) from exc
            raise FirewallOpError("腾讯云", f"撤销授权失败：{_err_message(exc)}") from exc

    def _cvm_revoke(self, region: str, sg_id: str, marker_prefix: str) -> None:
        targets = [
            r
            for r in self._cvm_rules(region, sg_id)
            if r.description.startswith(marker_prefix) and r.source_cidr
        ]
        if not targets:
            return
        policies = [
            _sg_policy(
                r.protocol,
                r.port,
                r.source_cidr if ":" not in r.source_cidr else "",
                "ACCEPT",
                r.description,
                ipv6=r.source_cidr if ":" in r.source_cidr else "",
            )
            for r in targets
        ]
        policy_set = vpc_models.SecurityGroupPolicySet()
        policy_set.Ingress = policies
        req = vpc_models.DeleteSecurityGroupPoliciesRequest()
        req.SecurityGroupId = sg_id
        req.SecurityGroupPolicySet = policy_set
        self._vpc(region).DeleteSecurityGroupPolicies(req)

    def _lh_revoke(self, region: str, instance_id: str, marker_prefix: str) -> None:
        targets = [r for r in self._lh_rules(region, instance_id) if r.description.startswith(marker_prefix)]
        if not targets:
            return
        req = lh_models.DeleteFirewallRulesRequest()
        req.InstanceId = instance_id
        req.FirewallRuleSet = [
            _lh_rule(r.protocol, r.port, r.source_cidr, r.description, rule_id=r.rule_id)
            for r in targets
        ]
        self._lh(region).DeleteFirewallRules(req)
