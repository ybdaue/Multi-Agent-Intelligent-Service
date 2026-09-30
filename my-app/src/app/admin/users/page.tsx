"use client";

import { useEffect, useState, useCallback } from "react";
import { Table, Input, Select, Tag, Typography, Button, Modal, Form, Space, Popconfirm, DatePicker, App } from "antd";
import { SearchOutlined, ReloadOutlined, EditOutlined, StopOutlined, CheckCircleOutlined, CaretDownOutlined, CaretUpOutlined } from "@ant-design/icons";
import { getUsers, banUser, unbanUser, updateUser, createUser } from "@/lib/server/admin-actions";

type UserRecord = Awaited<ReturnType<typeof getUsers>>["users"][number];
type CurrentAdmin = { id: string; role: string };

const ROLE_LABEL: Record<string, string> = { user: "普通用户", admin: "管理员", superAdmin: "超级管理员" };
const ROLE_COLOR: Record<string, string> = { user: "default", admin: "blue", superAdmin: "red" };

export default function AdminUsersPage() {
  const { message: msg } = App.useApp();

  const [data, setData] = useState<{ total: number; page: number; pageSize: number; users: UserRecord[]; currentAdmin: CurrentAdmin } | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [bannedFilter, setBannedFilter] = useState<string>("");
  const [createdAtFrom, setCreatedAtFrom] = useState<string>("");
  const [createdAtTo, setCreatedAtTo] = useState<string>("");
  const [page, setPage] = useState(1);
  const [orderField, setOrderField] = useState<string>("createdAt");
  const [orderDir, setOrderDir] = useState<"asc" | "desc">("desc");

  // 编辑弹窗
  const [editOpen, setEditOpen] = useState(false);
  const [editUser, setEditUser] = useState<UserRecord | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("user");
  const [saving, setSaving] = useState(false);

  // 创建弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [createEmail, setCreateEmail] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createConfirm, setCreateConfirm] = useState("");
  const [createName, setCreateName] = useState("");
  const [createRole, setCreateRole] = useState("user");
  const [creating, setCreating] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getUsers({
        search: search || undefined,
        page,
        pageSize: 12,
        orderField: orderField as "createdAt" | "email" | "name" | "balance",
        orderDir,
        role: roleFilter || undefined,
        banned: bannedFilter === "" ? undefined : bannedFilter === "true",
        createdAtFrom: createdAtFrom || undefined,
        createdAtTo: createdAtTo || undefined,
      });
      setData(result as typeof data);
    } finally {
      setLoading(false);
    }
  }, [search, page, roleFilter, bannedFilter, createdAtFrom, createdAtTo, orderField, orderDir]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBan = async (id: string) => {
    try {
      await banUser(id);
      msg.success("已封禁");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  const handleUnban = async (id: string) => {
    try {
      await unbanUser(id);
      msg.success("已解封");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  const openEdit = (record: UserRecord) => {
    setEditUser(record);
    setEditName(record.name ?? "");
    setEditRole(record.role);
    setEditOpen(true);
  };

  const handleSave = async () => {
    if (!editUser) return;
    setSaving(true);
    try {
      await updateUser(editUser.id, { name: editName, role: editRole });
      msg.success("保存成功");
      setEditOpen(false);
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(false); }
  };

  const handleCreate = async () => {
    if (!createEmail || !createPassword) { msg.warning("请填写邮箱和密码"); return; }
    if (createPassword !== createConfirm) { msg.warning("两次密码不一致"); return; }
    setCreating(true);
    try {
      await createUser({
        email: createEmail,
        password: createPassword,
        name: createName || undefined,
        role: createRole,
      });
      msg.success("创建成功");
      setCreateOpen(false);
      setCreateEmail("");
      setCreatePassword("");
      setCreateConfirm("");
      setCreateName("");
      setCreateRole("user");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "创建失败"); }
    finally { setCreating(false); }
  };

  const canModify = (r: UserRecord) => {
    const admin = data?.currentAdmin;
    if (!admin || admin.id === r.id) return false;
    if (admin.role === "superAdmin") return true;
    // admin 只能操作普通用户
    return admin.role === "admin" && r.role === "user";
  };

  const columns = [
    { title: "ID", dataIndex: "id", width: 200, ellipsis: true },
    { title: "邮箱", dataIndex: "email", width: 200, ellipsis: true },
    { title: "昵称", dataIndex: "name", width: 140, render: (v: string | null) => v ?? "-" },
    {
      title: "角色", dataIndex: "role", width: 100,
      render: (v: string) => (
        <Tag color={ROLE_COLOR[v] ?? "default"}>{ROLE_LABEL[v] ?? v}</Tag>
      ),
    },
    {
      title: "状态", dataIndex: "banned", width: 80,
      render: (v: boolean) => (
        <Tag color={v ? "red" : "green"}>{v ? "已封禁" : "正常"}</Tag>
      ),
    },
    {
      title: "余额", width: 100,
      render: (_: unknown, r: UserRecord) => {
        const balance = r.billingAccount?.balance ?? 0;
        return <Tag color={balance > 0 ? "green" : balance < 0 ? "red" : "default"}>¥{(balance / 100).toFixed(2)}</Tag>;
      },
    },
    { title: "注册时间", dataIndex: "createdAt", width: 170, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: "操作", width: 140, fixed: "right" as const,
      render: (_: unknown, r: UserRecord) => {
        const allowed = canModify(r);
        return (
          <Space>
            <Button size="small" type="link" icon={<EditOutlined />} disabled={!allowed} onClick={() => openEdit(r)}>
              编辑
            </Button>
            {r.banned ? (
              <Popconfirm title="确定解封该账号？" onConfirm={() => handleUnban(r.id)}>
                <Button size="small" type="link" icon={<CheckCircleOutlined />} style={{ color: "#52c41a" }} disabled={!allowed}>
                  解封
                </Button>
              </Popconfirm>
            ) : (
              <Popconfirm title="确定封禁该账号？封禁后用户将无法登录。" onConfirm={() => handleBan(r.id)}>
                <Button size="small" type="link" danger icon={<StopOutlined />} disabled={!allowed}>
                  封禁
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  const roleOptions = [
    { value: "", label: "全部角色" },
    { value: "user", label: "普通用户" },
    { value: "admin", label: "管理员" },
    { value: "superAdmin", label: "超级管理员" },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>账号管理</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          placeholder="搜索 ID / 邮箱 / 昵称"
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          style={{ width: 220 }}
          allowClear
        />
        <Select
          value={roleFilter}
          onChange={(v) => { setRoleFilter(v); setPage(1); }}
          style={{ width: 130 }}
          options={roleOptions}
        />
        <Select
          value={bannedFilter}
          onChange={(v) => { setBannedFilter(v); setPage(1); }}
          style={{ width: 110 }}
          options={[
            { value: "", label: "全部状态" },
            { value: "false", label: "正常" },
            { value: "true", label: "已封禁" },
          ]}
        />
        <DatePicker.RangePicker
          onChange={(_, dateStrings) => {
            setCreatedAtFrom(dateStrings[0] || "");
            setCreatedAtTo(dateStrings[1] || "");
            setPage(1);
          }}
          style={{ width: 240 }}
        />
        <Select
          value={orderField}
          onChange={(v) => { setOrderField(v); setPage(1); }}
          style={{ width: 130 }}
          options={[
            { value: "createdAt", label: "按注册时间" },
            { value: "email", label: "按邮箱" },
            { value: "balance", label: "按余额" },
          ]}
        />
        <Button
          type="text"
          icon={orderDir === "desc" ? <CaretDownOutlined /> : <CaretUpOutlined />}
          onClick={() => setOrderDir((p) => (p === "desc" ? "asc" : "desc"))}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
        <Button type="primary" onClick={() => setCreateOpen(true)}>创建账号</Button>
      </div>

      <Table
        dataSource={data?.users ?? []}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 12,
          total: data?.total ?? 0,
          onChange: setPage,
          showSizeChanger: false,
        }}
        size="small"
        scroll={{ x: 1000 }}
      />

      <Modal
        title="编辑账号"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        destroyOnHidden
      >
        <Form layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="邮箱">
            <Input value={editUser?.email ?? ""} disabled />
          </Form.Item>
          <Form.Item label="用户名称">
            <Input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="输入新名称" />
          </Form.Item>
          <Form.Item label="角色">
            <Select
              value={editRole}
              onChange={setEditRole}
              options={roleOptions.filter((o) => o.value)}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="创建账号"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
        destroyOnHidden
      >
        <Form layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="邮箱" required>
            <Input
              type="email" placeholder="name@example.com"
              value={createEmail} onChange={(e) => setCreateEmail(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="密码" required>
            <Input.Password
              placeholder="请输入密码"
              value={createPassword} onChange={(e) => setCreatePassword(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="确认密码" required>
            <Input.Password
              placeholder="再次输入密码"
              value={createConfirm} onChange={(e) => setCreateConfirm(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="用户名称">
            <Input
              placeholder="可选"
              value={createName} onChange={(e) => setCreateName(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="角色">
            <Select
              value={createRole}
              onChange={setCreateRole}
              options={roleOptions.filter((o) => o.value)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}