"use client";

import "@ant-design/v5-patch-for-react-19";

import { useEffect, useState, useCallback } from "react";
import { Table, Tag, Button, Select, Input, Space, Popconfirm, Modal, Typography, App, DatePicker } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { getPaymentOrders, updatePaymentOrderStatus } from "@/lib/server/admin-actions";

type OrderRecord = Awaited<ReturnType<typeof getPaymentOrders>>["orders"][number];

const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: "orange", label: "待处理" },
  success: { color: "green", label: "已完成" },
  failed: { color: "red", label: "失败" },
  expired: { color: "default", label: "已过期" },
};

const methodConfig: Record<string, string> = {
  balance: "余额",
  alipay: "支付宝",
  wxpay: "微信支付",
};

export default function AdminOrdersPage() {
  const { message: msg, modal: antModal } = App.useApp();

  const [data, setData] = useState<{ total: number; page: number; pageSize: number; orders: OrderRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [methodFilter, setMethodFilter] = useState<string>("");
  const [emailSearch, setEmailSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getPaymentOrders({
        page,
        pageSize: 12,
        status: statusFilter || undefined,
        paymentMethod: methodFilter || undefined,
        email: emailSearch || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      });
      setData(result as typeof data);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [page, statusFilter, methodFilter, emailSearch, dateFrom, dateTo, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleMarkSuccess = (record: OrderRecord) => {
    let note = "";
    antModal.confirm({
      title: "确认完成订单",
      content: (
        <div>
          <p>用户：{record.userEmail}</p>
          <p>金额：¥{(record.amount / 100).toFixed(2)}</p>
          <Input.TextArea placeholder="备注（可选）" rows={3} onChange={(e) => { note = e.target.value; }} />
        </div>
      ),
      onOk: async () => {
        try {
          await updatePaymentOrderStatus(record.id, "success", note || undefined);
          msg.success("订单已标记为完成");
          fetchData();
        } catch { msg.error("操作失败"); }
      },
    });
  };

  const columns = [
    { title: "创建时间", dataIndex: "createdAt", width: 160, render: (v: string) => new Date(v).toLocaleString() },
    { title: "用户邮箱", dataIndex: "userEmail", width: 180, ellipsis: true },
    { title: "用户昵称", dataIndex: "userName", width: 120, render: (v: string | null) => v ?? "-" },
    { title: "套餐", dataIndex: "planName", width: 140, render: (v: string | null) => v ?? "直接充值" },
    {
      title: "金额", dataIndex: "amount", width: 100,
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    {
      title: "支付方式", dataIndex: "paymentMethod", width: 100,
      render: (v: string) => methodConfig[v] ?? v,
    },
    {
      title: "状态", dataIndex: "status", width: 90,
      render: (v: string) => {
        const cfg = statusConfig[v] ?? { color: "default", label: v };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    { title: "交易号", dataIndex: "tradeNo", width: 180, ellipsis: true, render: (v: string | null) => v ?? "-" },
    { title: "支付时间", dataIndex: "paidAt", width: 160, render: (v: string | null) => v ? new Date(v).toLocaleString() : "-" },
    { title: "备注", dataIndex: "note", width: 150, ellipsis: true, render: (v: string | null) => v ?? "-" },
    {
      title: "操作", width: 100, fixed: "right" as const,
      render: (_: unknown, r: OrderRecord) => (
        r.status === "pending" ? (
          <Button size="small" type="link" style={{ color: "#52c41a" }} onClick={() => handleMarkSuccess(r)}>
            标记完成
          </Button>
        ) : <span style={{ color: "#999" }}>-</span>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>订单管理</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          placeholder="搜索用户邮箱"
          prefix={<SearchOutlined />}
          value={emailSearch}
          onChange={(e) => { setEmailSearch(e.target.value); setPage(1); }}
          style={{ width: 200 }}
          allowClear
        />
        <Select
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1); }}
          style={{ width: 120 }}
          options={[
            { value: "", label: "全部状态" },
            { value: "pending", label: "待处理" },
            { value: "success", label: "已完成" },
            { value: "failed", label: "失败" },
            { value: "expired", label: "已过期" },
          ]}
        />
        <Select
          value={methodFilter}
          onChange={(v) => { setMethodFilter(v); setPage(1); }}
          style={{ width: 130 }}
          options={[
            { value: "", label: "全部支付方式" },
            { value: "balance", label: "余额" },
            { value: "alipay", label: "支付宝" },
            { value: "wxpay", label: "微信支付" },
          ]}
        />
        <DatePicker.RangePicker
          onChange={(_, ds) => { setDateFrom(ds[0] || ""); setDateTo(ds[1] || ""); setPage(1); }}
          style={{ width: 240 }}
        />
      </div>

      <Table
        dataSource={data?.orders ?? []}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 12,
          total: data?.total ?? 0,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (t: number) => `共 ${t} 条`,
        }}
        size="small"
        scroll={{ x: 1400 }}
        locale={{ emptyText: "暂无订单" }}
      />
    </div>
  );
}