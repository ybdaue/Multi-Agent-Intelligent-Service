"use client";

import "@ant-design/v5-patch-for-react-19";

import { useEffect, useState, useCallback } from "react";
import { Table, Tag, Select, Input, Typography, App, DatePicker } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { getAdminAuditLogs } from "@/lib/server/admin-actions";

type LogRecord = Awaited<ReturnType<typeof getAdminAuditLogs>>["logs"][number];

const actionConfig: Record<string, { color: string; label: string }> = {
  create: { color: "green", label: "创建" },
  update: { color: "blue", label: "修改" },
  delete: { color: "red", label: "删除" },
  ban: { color: "orange", label: "封禁" },
  unban: { color: "default", label: "解封" },
  publish: { color: "purple", label: "发布" },
  archive: { color: "orange", label: "下线" },
  recharge: { color: "cyan", label: "充值" },
  deduct: { color: "volcano", label: "扣款" },
};

const targetTypeLabel: Record<string, string> = {
  user: "用户", novel: "小说", chapter: "章节", plan: "套餐",
  pricing: "定价", "model-route": "模型路由", order: "订单", announcement: "公告",
};

export default function AdminAuditLogsPage() {
  const { message: msg } = App.useApp();

  const [data, setData] = useState<{ total: number; page: number; pageSize: number; logs: LogRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [adminEmail, setAdminEmail] = useState("");
  const [actionFilter, setActionFilter] = useState<string>("");
  const [targetTypeFilter, setTargetTypeFilter] = useState<string>("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getAdminAuditLogs({
        page,
        pageSize: 12,
        adminEmail: adminEmail || undefined,
        action: actionFilter || undefined,
        targetType: targetTypeFilter || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      });
      setData(result as typeof data);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [page, adminEmail, actionFilter, targetTypeFilter, dateFrom, dateTo, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { title: "时间", dataIndex: "createdAt", width: 160, render: (v: string) => new Date(v).toLocaleString() },
    { title: "管理员", dataIndex: "adminEmail", width: 180, ellipsis: true },
    {
      title: "操作", dataIndex: "action", width: 80,
      render: (v: string) => {
        const cfg = actionConfig[v] ?? { color: "default", label: v };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: "目标类型", dataIndex: "targetType", width: 90,
      render: (v: string) => <Tag>{targetTypeLabel[v] ?? v}</Tag>,
    },
    { title: "目标ID", dataIndex: "targetId", width: 180, ellipsis: true, render: (v: string | null) => v ?? "-" },
    { title: "详情", dataIndex: "detail", width: 300, ellipsis: true, render: (v: string | null) => v ?? "-" },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>操作日志</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          placeholder="搜索管理员邮箱"
          prefix={<SearchOutlined />}
          value={adminEmail}
          onChange={(e) => { setAdminEmail(e.target.value); setPage(1); }}
          style={{ width: 200 }}
          allowClear
        />
        <Select
          value={actionFilter}
          onChange={(v) => { setActionFilter(v); setPage(1); }}
          style={{ width: 110 }}
          options={[
            { value: "", label: "全部操作" },
            { value: "create", label: "创建" },
            { value: "update", label: "修改" },
            { value: "delete", label: "删除" },
            { value: "ban", label: "封禁" },
            { value: "unban", label: "解封" },
            { value: "publish", label: "发布" },
            { value: "archive", label: "下线" },
            { value: "recharge", label: "充值" },
            { value: "deduct", label: "扣款" },
          ]}
        />
        <Select
          value={targetTypeFilter}
          onChange={(v) => { setTargetTypeFilter(v); setPage(1); }}
          style={{ width: 120 }}
          options={[
            { value: "", label: "全部目标" },
            { value: "user", label: "用户" },
            { value: "novel", label: "小说" },
            { value: "chapter", label: "章节" },
            { value: "plan", label: "套餐" },
            { value: "pricing", label: "定价" },
            { value: "model-route", label: "模型路由" },
            { value: "order", label: "订单" },
            { value: "announcement", label: "公告" },
          ]}
        />
        <DatePicker.RangePicker
          onChange={(_, ds) => { setDateFrom(ds[0] || ""); setDateTo(ds[1] || ""); setPage(1); }}
          style={{ width: 240 }}
        />
      </div>

      <Table
        dataSource={data?.logs ?? []}
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
        scroll={{ x: 1000 }}
        locale={{ emptyText: "暂无操作日志" }}
      />
    </div>
  );
}