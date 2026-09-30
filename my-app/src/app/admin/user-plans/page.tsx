"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Input, Button, Table, Tag, Typography, DatePicker,
  Space, App,
} from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { getUserPlans } from "@/lib/server/admin-actions";

const { RangePicker } = DatePicker;

type UserPlanRecord = Awaited<ReturnType<typeof getUserPlans>>["records"][number];

const typeLabels: Record<string, string> = {
  recharge: "充值套餐",
  token: "Token套餐",
  subscription: "订阅套餐",
};
const typeColors: Record<string, string> = {
  recharge: "green",
  token: "blue",
  subscription: "purple",
};

/** 根据套餐类型+状态返回展示标签与颜色 */
function getStatusDisplay(record: UserPlanRecord): { label: string; color: string } {
  const { plan, status } = record;
  // 充值套餐购买即用，统一灰色
  if (plan.type === "recharge") return { label: "已使用", color: "default" };

  if (plan.type === "token") {
    if (status === "exhausted") return { label: "已使用", color: "default" };
    if (status === "expired") return { label: "已过期", color: "red" };
    if (status === "active") return { label: "使用中", color: "green" };
    if (status === "cancelled") return { label: "已取消", color: "red" };
  }

  if (plan.type === "subscription") {
    if (status === "active") return { label: "使用中", color: "green" };
    if (status === "expired") return { label: "已过期", color: "red" };
    if (status === "cancelled") return { label: "已取消", color: "red" };
    if (status === "exhausted") return { label: "已使用", color: "default" };
  }

  return { label: status, color: "default" };
}

/** 根据套餐类型返回有效期文本 */
function getExpirationDisplay(record: UserPlanRecord): string {
  const { plan, expiresAt, currentPeriodEnd } = record;
  if (plan.type === "recharge") return "-";
  if (plan.type === "token") return expiresAt ? new Date(expiresAt).toLocaleString() : "永久";
  if (plan.type === "subscription") return currentPeriodEnd ? new Date(currentPeriodEnd).toLocaleString() : "-";
  return "-";
}

export default function AdminUserPlansPage() {
  const { message: msg } = App.useApp();

  const [records, setRecords] = useState<{ total: number; page: number; pageSize: number; records: UserPlanRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [email, setEmail] = useState("");
  const [dateRange, setDateRange] = useState<[string, string]>(["", ""]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getUserPlans({
        email: email || undefined,
        dateFrom: dateRange[0] || undefined,
        dateTo: dateRange[1] || undefined,
        page,
        pageSize: 12,
      });
      setRecords(r as typeof records);
    } catch {
      msg.error("加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, email, dateRange, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { title: "购买时间", dataIndex: "purchasedAt", width: 160, render: (v: string) => new Date(v).toLocaleString() },
    { title: "用户邮箱", width: 180, ellipsis: true, render: (_: unknown, r: UserPlanRecord) => r.user.email },
    { title: "用户昵称", width: 120, render: (_: unknown, r: UserPlanRecord) => r.user.name ?? "-" },
    { title: "套餐名称", width: 140, render: (_: unknown, r: UserPlanRecord) => r.plan.name },
    {
      title: "套餐类型", width: 100,
      render: (_: unknown, r: UserPlanRecord) => (
        <Tag color={typeColors[r.plan.type]}>{typeLabels[r.plan.type] ?? r.plan.type}</Tag>
      ),
    },
    { title: "套餐价格", width: 90, render: (_: unknown, r: UserPlanRecord) => `¥${(r.plan.price / 100).toFixed(2)}` },
    {
      title: "状态", width: 80,
      render: (_: unknown, r: UserPlanRecord) => {
        const { label, color } = getStatusDisplay(r);
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: "Token 额度", width: 120,
      render: (_: unknown, r: UserPlanRecord) => {
        if (r.plan.type === "recharge" || !r.totalTokens) return "-";
        const used = r.usedTokens ?? 0;
        const total = r.totalTokens;
        const pct = total > 0 ? Math.round((used / total) * 100) : 0;
        return (
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            {used.toLocaleString()} / {total.toLocaleString()} ({pct}%)
          </span>
        );
      },
    },
    {
      title: "有效期至", width: 160,
      render: (_: unknown, r: UserPlanRecord) => getExpirationDisplay(r),
    },
    {
      title: "自动续费", width: 80,
      render: (_: unknown, r: UserPlanRecord) => {
        if (r.plan.type === "recharge") return "-";
        return r.autoRenew ? <Tag color="blue">开启</Tag> : <Tag>关闭</Tag>;
      },
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>套餐账单</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <RangePicker
          onChange={(_, ds) => { setDateRange([ds[0] || "", ds[1] || ""]); setPage(1); }}
          style={{ width: 240 }}
        />
        <Input
          placeholder="搜索邮箱"
          prefix={<SearchOutlined />}
          allowClear
          value={email}
          onChange={(e) => { setEmail(e.target.value); setPage(1); }}
          style={{ width: 200 }}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </div>

      <Table
        dataSource={records?.records ?? []}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 12,
          total: records?.total ?? 0,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          size: "small",
        }}
        size="small"
        scroll={{ x: 1200 }}
        locale={{ emptyText: "暂无套餐记录" }}
      />
    </div>
  );
}