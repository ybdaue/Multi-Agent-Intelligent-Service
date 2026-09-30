"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Select, InputNumber, Input, Button, Table, Tag, Space,
  App, Popconfirm, Modal, Flex, DatePicker, Typography,
} from "antd";
import {
  ReloadOutlined, PlusOutlined, MinusOutlined, DeleteOutlined, SearchOutlined,
} from "@ant-design/icons";
import { getUsers, getRechargeRecords } from "@/lib/server/admin-actions";

const { RangePicker } = DatePicker;

type UserOption = { id: string; email: string; name: string | null; balance: number };
type RechargeRecord = Awaited<ReturnType<typeof getRechargeRecords>>["records"][number];

export default function AdminRechargePage() {
  const { message: msg } = App.useApp();

  // ── 数据 ──
  const [userOptions, setUserOptions] = useState<UserOption[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);

  // ── 充值记录筛选 ──
  const [records, setRecords] = useState<{ total: number; page: number; pageSize: number; records: RechargeRecord[] } | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordPage, setRecordPage] = useState(1);
  const [recordEmail, setRecordEmail] = useState("");
  const [dateRange, setDateRange] = useState<[string, string]>(["", ""]);

  // ── 弹窗状态 ──
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [actionType, setActionType] = useState<"recharge" | "deduct">("recharge");
  const [amount, setAmount] = useState<number>(0);
  const [note, setNote] = useState("");
  const [executing, setExecuting] = useState(false);

  // 加载用户
  const fetchUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const r = await getUsers({ pageSize: 200, orderField: "createdAt", orderDir: "desc" });
      setUserOptions(
        r.users.map((u) => ({
          id: u.id, email: u.email, name: u.name,
          balance: u.billingAccount?.balance ?? 0,
        }))
      );
    } catch { /* */ } finally { setLoadingUsers(false); }
  }, []);

  // 加载充值记录
  const fetchRecords = useCallback(async () => {
    setRecordLoading(true);
    try {
      const r = await getRechargeRecords({
        email: recordEmail || undefined,
        dateFrom: dateRange[0] || undefined,
        dateTo: dateRange[1] || undefined,
        page: recordPage,
        pageSize: 12,
      });
      setRecords(r as typeof records);
    } catch { /* */ } finally { setRecordLoading(false); }
  }, [recordPage, recordEmail, dateRange]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);
  useEffect(() => { fetchRecords(); }, [fetchRecords]);

  const selectedUsers = userOptions.filter((u) => selectedUserIds.includes(u.id));

  // ── API ──
  const callAdminAPI = async (path: string, body: Record<string, string>) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(body)) fd.append(k, v);
    const res = await fetch(path, { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "请求失败" }));
      throw new Error(err.detail || err.error || "请求失败");
    }
    return res.json();
  };

  const handleExecute = async () => {
    const finalAmount = actionType === "deduct" ? -Math.abs(amount) : Math.abs(amount);
    setExecuting(true);
    try {
      if (selectedUserIds.length === 1) {
        await callAdminAPI("/api/admin/adjust-balance", { userId: selectedUserIds[0], amount: String(finalAmount), note });
      } else {
        await callAdminAPI("/api/admin/batch-adjust-balance", { userIds: JSON.stringify(selectedUserIds), amount: String(finalAmount), note });
      }
      msg.success(`操作成功，${selectedUserIds.length} 个用户已处理`);
      setModalOpen(false);
      setSelectedUserIds([]);
      setAmount(0);
      setNote("");
      setActionType("recharge");
      fetchUsers();
      fetchRecords();
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "操作失败");
    } finally { setExecuting(false); }
  };

  // ── 充值记录列 ──
  const recordColumns = [
    { title: "时间", dataIndex: "createdAt", width: 170, render: (v: string) => new Date(v).toLocaleString() },
    { title: "用户邮箱", dataIndex: "userEmail", width: 200, ellipsis: true },
    { title: "用户昵称", dataIndex: "userName", width: 120, render: (v: string | null) => v ?? "-" },
    {
      title: "金额", dataIndex: "amount", width: 100,
      render: (v: number) => {
        const p = v > 0;
        return <span style={{ color: p ? "#52c41a" : "#ff4d4f", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{(v / 100).toFixed(2)} 元</span>;
      },
    },
    {
      title: "变动前", dataIndex: "balanceBefore", width: 90,
      render: (v: number) => <span style={{ fontVariantNumeric: "tabular-nums" }}>{(v / 100).toFixed(2)}</span>,
    },
    {
      title: "变动后", dataIndex: "balanceAfter", width: 90,
      render: (v: number) => <span style={{ fontVariantNumeric: "tabular-nums" }}>{(v / 100).toFixed(2)}</span>,
    },
    { title: "备注", dataIndex: "note", ellipsis: true, render: (v: string | null) => v ?? "-" },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Space>
          <Typography.Title level={4} style={{ margin: 0 }}>余额管理</Typography.Title>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>余额调整</Button>
        </Space>
      </div>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <RangePicker
          onChange={(_, ds) => { setDateRange([ds[0] || "", ds[1] || ""]); setRecordPage(1); }}
          style={{ width: 240 }}
        />
        <Input
          placeholder="搜索邮箱"
          prefix={<SearchOutlined />}
          allowClear
          value={recordEmail}
          onChange={(e) => { setRecordEmail(e.target.value); setRecordPage(1); }}
          style={{ width: 200 }}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchRecords}>刷新</Button>
      </div>

      <Table
        dataSource={records?.records ?? []}
        columns={recordColumns}
        rowKey="id"
        loading={recordLoading}
        pagination={{
          current: recordPage, pageSize: 12, total: records?.total ?? 0,
          onChange: setRecordPage, showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`, size: "small",
        }}
        size="small"
        locale={{ emptyText: "暂无余额记录" }}
      />

      {/* ── 充值/扣款弹窗 ── */}
      {modalOpen && (
      <Modal
        title="余额调整"
        open
        onCancel={() => { setModalOpen(false); setSelectedUserIds([]); setAmount(0); setNote(""); setActionType("recharge"); }}
        footer={null}
        width={760}
        destroyOnHidden
        afterClose={() => { setSelectedUserIds([]); setAmount(0); setNote(""); setActionType("recharge"); }}
      >
        <div style={{ display: "flex", gap: 16, minHeight: 320, marginTop: 8 }}>

          {/* 左侧 */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
            {/* 选择用户 */}
            <div>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>选择用户</div>
              <Select
                showSearch
                style={{ width: "100%" }}
                placeholder="搜索用户，点击添加到右侧"
                value={null}
                filterOption={(input, option) =>
                  (option?.label as string ?? "").toLowerCase().includes(input.toLowerCase())
                }
                onChange={(id: string) => {
                  if (id && !selectedUserIds.includes(id)) {
                    setSelectedUserIds((prev) => [...prev, id]);
                  }
                }}
                options={userOptions
                  .filter((u) => !selectedUserIds.includes(u.id))
                  .map((u) => ({ value: u.id, label: `${u.email}（${u.name ?? "-"}）` }))
                }
                notFoundContent="无匹配用户"
              />
            </div>

            {/* 切换 + 金额 */}
            <Flex gap={8} align="center">
              <Button
                type={actionType === "recharge" ? "primary" : "default"}
                danger={actionType === "deduct"}
                onClick={() => setActionType((p) => (p === "recharge" ? "deduct" : "recharge"))}
                style={{ minWidth: 64 }}
              >
                {actionType === "recharge" ? "充值" : "扣款"}
              </Button>
              <InputNumber
                style={{ flex: 1 }}
                placeholder="金额（元）"
                min={0.01}
                step={0.01}
                precision={2}
                prefix="¥"
                controls={false}
                value={amount ? amount / 100 : undefined}
                onChange={(v) => setAmount(v ? Math.round(v * 100) : 0)}
              />
            </Flex>

            {/* 备注 */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>原因备注</div>
              <Input.TextArea
                style={{ flex: 1, minHeight: 60 }}
                placeholder="选填"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={200}
              />
            </div>

            {/* 确认 */}
            <Popconfirm
              title="确认执行？"
              description={
                <div style={{ fontSize: 13 }}>
                  <Tag color={actionType === "recharge" ? "green" : "red"}>{actionType === "recharge" ? "充值" : "扣款"}</Tag>
                  <span style={{ fontWeight: 600 }}>{(Math.abs(amount) / 100).toFixed(2)} 元</span>
                  <span style={{ color: "var(--color-text-secondary)", marginLeft: 4 }}>× {selectedUsers.length} 人</span>
                  {note && <div style={{ marginTop: 4, color: "var(--color-text-secondary)" }}>{note}</div>}
                </div>
              }
              onConfirm={handleExecute}
              okText="确认"
              cancelText="取消"
              okButtonProps={{ danger: actionType === "deduct" }}
            >
              <Button
                type="primary"
                size="large"
                block
                loading={executing}
                disabled={selectedUserIds.length === 0 || amount === 0}
                danger={actionType === "deduct"}
                icon={actionType === "recharge" ? <PlusOutlined /> : <MinusOutlined />}
              >
                {actionType === "recharge" ? "确认充值" : "确认扣款"}
              </Button>
            </Popconfirm>
          </div>

          {/* 右侧：已选用户 */}
          <div style={{ width: 260, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              已选用户
              {selectedUsers.length > 0 && <span style={{ color: "var(--color-text-secondary)", fontWeight: 400 }}>（{selectedUsers.length}）</span>}
            </div>
            <div style={{
              flex: 1, overflow: "auto", border: "1px solid var(--color-border)",
              borderRadius: 6, padding: 2, background: "var(--color-surface)",
            }}>
              {selectedUsers.length === 0 ? (
                <div style={{ color: "var(--color-text-tertiary)", textAlign: "center", padding: "60px 0", fontSize: 13 }}>
                  暂无选择
                </div>
              ) : (
                selectedUsers.map((u) => (
                  <div key={u.id} style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "6px 8px", borderBottom: "1px solid var(--color-border)",
                    fontSize: 13, background: "var(--color-surface)",
                  }}>
                    <div style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {u.email}
                    </div>
                    <span style={{ fontVariantNumeric: "tabular-nums", flexShrink: 0 }}>
                      {(u.balance / 100).toFixed(2)}
                    </span>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />}
                      onClick={() => setSelectedUserIds((prev) => prev.filter((i) => i !== u.id))}
                    />
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      </Modal>
      )}
    </div>
  );
}