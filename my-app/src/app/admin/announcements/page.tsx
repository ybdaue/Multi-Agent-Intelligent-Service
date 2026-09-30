"use client";

import "@ant-design/v5-patch-for-react-19";

import dayjs from "dayjs";
import { useEffect, useState, useCallback } from "react";
import { Table, Tag, Button, Modal, Form, Input, Select, Space, Popconfirm, Typography, App, DatePicker } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, CheckCircleOutlined, InboxOutlined } from "@ant-design/icons";
import { getAnnouncements, createAnnouncement, updateAnnouncement, deleteAnnouncement, publishAnnouncement, archiveAnnouncement } from "@/lib/server/admin-actions";

type AnnounceItem = Awaited<ReturnType<typeof getAnnouncements>>["announcements"][number];

const statusConfig: Record<string, { color: string; label: string }> = {
  draft: { color: "default", label: "草稿" },
  published: { color: "green", label: "已发布" },
  archived: { color: "orange", label: "已下线" },
};

const priorityConfig: Record<string, { color: string; label: string }> = {
  low: { color: "default", label: "低" },
  normal: { color: "blue", label: "普通" },
  high: { color: "orange", label: "高" },
  urgent: { color: "red", label: "紧急" },
};

// 子组件：Form.useForm 与 Form 同生命周期，Modal 关闭时卸载干净
function AnnouncementForm({
  open,
  editing,
  saving,
  onSave,
  onCancel,
}: {
  open: boolean;
  editing: AnnounceItem | null;
  saving: boolean;
  onSave: (values: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [form] = Form.useForm();
  const { message: msg } = App.useApp();

  useEffect(() => {
    if (!open) return;
    if (editing) {
      form.setFieldsValue({
        title: editing.title,
        content: editing.content,
        priority: editing.priority,
        targetRole: editing.targetRole,
        publishAt: editing.publishAt ? dayjs(editing.publishAt) : null,
        expiresAt: editing.expiresAt ? dayjs(editing.expiresAt) : null,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ priority: "normal" });
    }
  }, [open, editing, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await onSave(values);
    } catch (e: unknown) {
      if (e && typeof e === "object" && "errorFields" in e) return;
      msg.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  return (
    <Modal
      title={editing ? "编辑公告" : "新建公告"}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={saving}
      okText="保存"
      width={640}
      forceRender
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入公告标题" }]}>
          <Input placeholder="公告标题" />
        </Form.Item>
        <Form.Item name="content" label="内容" rules={[{ required: true, message: "请输入公告内容" }]}>
          <Input.TextArea rows={6} placeholder="公告内容" />
        </Form.Item>
        <Space style={{ width: "100%" }} align="start">
          <Form.Item name="priority" label="优先级">
            <Select style={{ width: 150 }} options={[
              { value: "low", label: "低" },
              { value: "normal", label: "普通" },
              { value: "high", label: "高" },
              { value: "urgent", label: "紧急" },
            ]} />
          </Form.Item>
          <Form.Item name="targetRole" label="目标角色">
            <Select style={{ width: 150 }} allowClear
              options={[
                { value: "", label: "全部用户" },
                { value: "user", label: "普通用户" },
                { value: "admin", label: "管理员" },
              ]}
            />
          </Form.Item>
        </Space>
        <Space style={{ width: "100%" }} align="start">
          <Form.Item name="publishAt" label="计划发布时间">
            <DatePicker showTime style={{ width: 220 }} />
          </Form.Item>
          <Form.Item name="expiresAt" label="过期时间">
            <DatePicker showTime style={{ width: 220 }} />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

export default function AdminAnnouncementsPage() {
  const { message: msg } = App.useApp();

  const [data, setData] = useState<{ total: number; page: number; pageSize: number; announcements: AnnounceItem[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AnnounceItem | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getAnnouncements({ status: statusFilter || undefined, page, pageSize: 12 });
      setData(result as typeof data);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [statusFilter, page, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (record: AnnounceItem) => {
    setEditing(record);
    setModalOpen(true);
  };

  const handleSave = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      const payload: Parameters<typeof createAnnouncement>[0] = {
        title: values.title as string,
        content: values.content as string,
        priority: values.priority as string,
        targetRole: (values.targetRole as string) || undefined,
        publishAt: (values.publishAt as Date | undefined)?.toISOString(),
        expiresAt: (values.expiresAt as Date | undefined)?.toISOString(),
      };
      if (editing) {
        await updateAnnouncement(editing.id, payload);
        msg.success("更新成功");
      } else {
        await createAnnouncement(payload);
        msg.success("创建成功");
      }
      setModalOpen(false);
      fetchData();
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "保存失败");
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteAnnouncement(id);
      msg.success("已删除");
      fetchData();
    } catch { msg.error("删除失败"); }
  };

  const handlePublish = async (id: string) => {
    try {
      await publishAnnouncement(id);
      msg.success("已发布");
      fetchData();
    } catch { msg.error("操作失败"); }
  };

  const handleArchive = async (id: string) => {
    try {
      await archiveAnnouncement(id);
      msg.success("已下线");
      fetchData();
    } catch { msg.error("操作失败"); }
  };

  const columns = [
    { title: "标题", dataIndex: "title", width: 200, ellipsis: true },
    {
      title: "优先级", dataIndex: "priority", width: 80,
      render: (v: string) => {
        const cfg = priorityConfig[v] ?? { color: "default", label: v };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: "状态", dataIndex: "status", width: 80,
      render: (v: string) => {
        const cfg = statusConfig[v] ?? { color: "default", label: v };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    { title: "目标角色", dataIndex: "targetRole", width: 90, render: (v: string | null) => v ? <Tag>{v}</Tag> : <Tag>全部</Tag> },
    { title: "发布时间", dataIndex: "publishAt", width: 150, render: (v: string | null) => v ? new Date(v).toLocaleString() : "-" },
    { title: "过期时间", dataIndex: "expiresAt", width: 150, render: (v: string | null) => v ? new Date(v).toLocaleString() : "-" },
    { title: "创建者", width: 160, ellipsis: true, render: (_: unknown, r: AnnounceItem) => r.creator?.email ?? "-" },
    {
      title: "操作", width: 220, fixed: "right" as const,
      render: (_: unknown, r: AnnounceItem) => (
        <Space>
          {r.status === "archived" && (
            <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          )}
          {r.status === "archived" && (
            <Popconfirm title="确定重新上线该公告？" onConfirm={() => handlePublish(r.id)}>
              <Button size="small" type="link" icon={<CheckCircleOutlined />} style={{ color: "#52c41a" }}>上线</Button>
            </Popconfirm>
          )}
          {r.status === "draft" && (
            <Popconfirm title="确定发布该公告？" onConfirm={() => handlePublish(r.id)}>
              <Button size="small" type="link" icon={<CheckCircleOutlined />} style={{ color: "#52c41a" }}>发布</Button>
            </Popconfirm>
          )}
          {r.status === "published" && (
            <Popconfirm title="确定下线该公告？" onConfirm={() => handleArchive(r.id)}>
              <Button size="small" type="link" icon={<InboxOutlined />} style={{ color: "#faad14" }}>下线</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确定删除该公告？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>系统公告</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Select
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1); }}
          style={{ width: 120 }}
          options={[
            { value: "", label: "全部状态" },
            { value: "draft", label: "草稿" },
            { value: "published", label: "已发布" },
            { value: "archived", label: "已下线" },
          ]}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建公告</Button>
      </div>

      <Table
        dataSource={data?.announcements ?? []}
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
        scroll={{ x: 1200 }}
        locale={{ emptyText: "暂无公告" }}
      />

      {/* Form 始终挂载，Modal 通过 open 控制显隐 */}
      <AnnouncementForm
        open={modalOpen}
        editing={editing}
        saving={saving}
        onSave={handleSave}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
}