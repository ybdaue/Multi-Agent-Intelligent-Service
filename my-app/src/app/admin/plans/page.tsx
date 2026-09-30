"use client";

import "@ant-design/v5-patch-for-react-19";

import { useCallback, useEffect, useState } from "react";
import {
  Button, Table, Tag, Space, App, Modal, Form, Input, InputNumber,
  Select, Switch, Popconfirm, Typography,
} from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import { getPlans, createPlan, updatePlan, deletePlan } from "@/lib/server/admin-actions";

type Plan = Awaited<ReturnType<typeof getPlans>>[number];

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

const serviceOptions = [
  { value: "novel", label: "小说" },
  { value: "legal", label: "法律" },
  { value: "finance", label: "金融" },
  { value: "chat", label: "闲聊" },
];

export default function AdminPlansPage() {
  const { message: msg } = App.useApp();

  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Plan | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const planType = Form.useWatch("type", form);

  const fetchPlans = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPlans();
      setPlans(data);
    } catch { /* */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchPlans(); }, [fetchPlans]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ type: "recharge", autoRenew: true, isActive: true, sortOrder: 0 });
    setModalOpen(true);
  };

  const openEdit = (plan: Plan) => {
    setEditing(plan);
    // DB 存分，表单显示元 → 除以 100
    form.setFieldsValue({
      ...plan,
      price: plan.price / 100,
      bonusAmount: plan.bonusAmount ? plan.bonusAmount / 100 : undefined,
      tokenAmount: plan.tokenAmount,
      validityDays: plan.validityDays,
      periodDays: plan.periodDays,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      // 表单输入是元，DB 存分 → 乘以 100（price/bonusAmount 是金额字段）
      const dbValues = {
        ...values,
        price: Math.round(values.price * 100),
        bonusAmount: values.bonusAmount != null ? Math.round(values.bonusAmount * 100) : undefined,
      };
      if (editing) {
        await updatePlan(editing.id, dbValues);
        msg.success("套餐已更新");
      } else {
        await createPlan(dbValues);
        msg.success("套餐已创建");
      }
      setModalOpen(false);
      fetchPlans();
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "操作失败");
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: string, name: string) => {
    try {
      await deletePlan(id);
      msg.success(`已删除套餐：${name}`);
      fetchPlans();
    } catch (e: unknown) {
      msg.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const formatPrice = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

  const columns = [
    { title: "排序", dataIndex: "sortOrder", width: 60 },
    { title: "名称", dataIndex: "name", width: 160 },
    {
      title: "类型", dataIndex: "type", width: 100,
      render: (t: string) => <Tag color={typeColors[t]}>{typeLabels[t] ?? t}</Tag>,
    },
    {
      title: "价格", dataIndex: "price", width: 90,
      render: (v: number) => formatPrice(v),
    },
    {
      title: "赠送/额度", width: 130,
      render: (_: unknown, r: Plan) => {
        if (r.type === "recharge") return `送 ${formatPrice(r.bonusAmount ?? 0)}`;
        if (r.tokenAmount) return `${(r.tokenAmount / 10000).toFixed(0)}万 token`;
        return "-";
      },
    },
    {
      title: "限制服务", width: 100,
      render: (_: unknown, r: Plan) => r.serviceType
        ? <Tag>{serviceOptions.find(s => s.value === r.serviceType)?.label ?? r.serviceType}</Tag>
        : <span style={{ color: "var(--color-text-tertiary)" }}>不限</span>,
    },
    {
      title: "有效期", width: 100,
      render: (_: unknown, r: Plan) => {
        if (r.type === "token") return r.validityDays ? `${r.validityDays}天` : "永久";
        if (r.type === "subscription") return `${r.periodDays ?? 30}天/周期`;
        return "-";
      },
    },
    {
      title: "状态", dataIndex: "isActive", width: 70,
      render: (v: boolean) => <Tag color={v ? "green" : "red"}>{v ? "上架" : "下架"}</Tag>,
    },
    {
      title: "操作", width: 140, fixed: "right" as const,
      render: (_: unknown, r: Plan) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除此套餐？" onConfirm={() => handleDelete(r.id, r.name)} okText="确认" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Space>
          <Typography.Title level={4} style={{ margin: 0 }}>套餐管理</Typography.Title>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建套餐</Button>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={fetchPlans}>刷新</Button>
      </div>

      <Table
        dataSource={plans}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        scroll={{ x: 900 }}
        pagination={false}
        locale={{ emptyText: "暂无套餐" }}
      />

      {modalOpen && (
        <Modal
          title={editing ? "编辑套餐" : "新建套餐"}
          open
          onCancel={() => { setModalOpen(false); }}
          onOk={handleSave}
          confirmLoading={saving}
          width={640}
          destroyOnHidden
        >
          <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item name="name" label="套餐名称" rules={[{ required: true, message: "请输入名称" }]}>
              <Input placeholder="如：新手充值包" />
            </Form.Item>

            <Space style={{ width: "100%" }} size={16}>
              <Form.Item name="type" label="套餐类型" rules={[{ required: true }]}>
                <Select style={{ width: 140 }} options={[
                  { value: "recharge", label: "充值套餐" },
                  { value: "token", label: "Token套餐" },
                  { value: "subscription", label: "订阅套餐" },
                ]} />
              </Form.Item>
              <Form.Item name="price" label="价格（元）" rules={[{ required: true, type: "number", min: 0.01 }]}>
                <InputNumber style={{ width: 140 }} min={0.01} step={0.01} precision={2} placeholder="单位：元" />
              </Form.Item>
              <Form.Item name="sortOrder" label="排序权重">
                <InputNumber style={{ width: 100 }} min={0} />
              </Form.Item>
            </Space>

            {planType === "recharge" && (
              <Form.Item name="bonusAmount" label="赠送金额（元）" rules={[{ type: "number", min: 0 }]}>
                <InputNumber style={{ width: 200 }} min={0} step={0.01} precision={2} placeholder="额外赠送的余额（元）" />
              </Form.Item>
            )}

            {(planType === "token" || planType === "subscription") && (
              <>
                <Form.Item name="tokenAmount" label="Token 额度" rules={[{ required: true, type: "number", min: 1 }]}>
                  <InputNumber style={{ width: 200 }} min={1} placeholder="如：1000000（100万）" />
                </Form.Item>
                <Space style={{ width: "100%" }} size={16}>
                  <Form.Item name="serviceType" label="限制服务类型">
                    <Select style={{ width: 140 }} allowClear placeholder="不限">
                      {serviceOptions.map(o => <Select.Option key={o.value} value={o.value}>{o.label}</Select.Option>)}
                    </Select>
                  </Form.Item>
                  <Form.Item name="modelName" label="限制模型">
                    <Input style={{ width: 200 }} placeholder="如：deepseek-v4-flash" allowClear />
                  </Form.Item>
                </Space>
              </>
            )}

            {planType === "token" && (
              <Form.Item name="validityDays" label="有效天数（购买后）" rules={[{ type: "number", min: 1 }]}>
                <InputNumber style={{ width: 200 }} min={1} placeholder="留空=永久有效" />
              </Form.Item>
            )}

            {planType === "subscription" && (
              <Space style={{ width: "100%" }} size={16}>
                <Form.Item name="periodDays" label="周期天数" rules={[{ type: "number", min: 1 }]}>
                  <InputNumber style={{ width: 120 }} min={1} />
                </Form.Item>
                <Form.Item name="autoRenew" label="自动续费" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Space>
            )}

            <Form.Item name="description" label="描述说明">
              <Input.TextArea rows={3} placeholder="选填" />
            </Form.Item>

            {editing && (
              <Form.Item name="isActive" label="上架状态" valuePropName="checked">
                <Switch />
              </Form.Item>
            )}
          </Form>
        </Modal>
      )}
    </div>
  );
}