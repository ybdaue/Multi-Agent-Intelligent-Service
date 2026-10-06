"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Input, Button, Table, Tag, Typography, DatePicker,
  Select, Space, App,
} from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { getBillingRecords } from "@/lib/server/admin-actions";

const { RangePicker } = DatePicker;

type BillingRecord = Awaited<ReturnType<typeof getBillingRecords>>["records"][number];

const serviceLabels: Record<string, string> = {
  novel: "小说",
  legal: "法律",
  finance: "金融",
  chat: "闲聊",
};
const serviceColors: Record<string, string> = {
  novel: "blue",
  legal: "purple",
  finance: "geekblue",
  chat: "cyan",
};

export default function AdminBillingPage() {
  const { message: msg } = App.useApp();

  const [records, setRecords] = useState<{ total: number; page: number; pageSize: number; records: BillingRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [email, setEmail] = useState("");
  const [serviceType, setServiceType] = useState<string>("");
  const [dateRange, setDateRange] = useState<[string, string]>(["", ""]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getBillingRecords({
        email: email || undefined,
        serviceType: serviceType || undefined,
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
  }, [page, email, serviceType, dateRange, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { title: "时间", dataIndex: "createdAt", width: 160, render: (v: string) => new Date(v).toLocaleString() },
    { title: "用户邮箱", dataIndex: "userEmail", width: 180, ellipsis: true },
    { title: "用户昵称", dataIndex: "userName", width: 120, render: (v: string | null) => v ?? "-" },
    {
      title: "服务", dataIndex: "serviceType", width: 80,
      render: (v: string) => <Tag color={serviceColors[v]}>{serviceLabels[v] ?? v}</Tag>,
    },
    {
      title: "输入 tokens", dataIndex: "inputTokens", width: 100,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: "输出 tokens", dataIndex: "outputTokens", width: 100,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: "总计 tokens", dataIndex: "totalTokens", width: 100,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: "费用", dataIndex: "totalCost", width: 80,
      render: (v: number) => <span style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>¥{(v / 100).toFixed(4)}</span>,
    },
    {
      title: "套餐抵扣", dataIndex: "planDeductedTokens", width: 90,
      render: (v: number | null) => v != null ? `${v.toLocaleString()} tokens` : "-",
    },
    {
      title: "余额扣除", dataIndex: "balanceDeductedCost", width: 80,
      render: (v: number | null) => v != null ? `¥${(v / 100).toFixed(2)}` : "-",
    },
    { title: "余额后", dataIndex: "balanceAfter", width: 70, render: (v: number) => `¥${(v / 100).toFixed(2)}` },
    { title: "请求路径", dataIndex: "requestPath", width: 160, ellipsis: true, render: (v: string | null) => v ?? "-" },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>消费账单</Typography.Title>

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
        <Select
          value={serviceType}
          onChange={(v) => { setServiceType(v); setPage(1); }}
          style={{ width: 110 }}
          options={[
            { value: "", label: "全部服务" },
            { value: "novel", label: "小说" },
            { value: "legal", label: "法律" },
            { value: "finance", label: "金融" },
            { value: "chat", label: "闲聊" },
          ]}
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
        scroll={{ x: 1600 }}
        locale={{ emptyText: "暂无消费记录" }}
      />
    </div>
  );
}