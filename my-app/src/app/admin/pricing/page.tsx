"use client";

import "@ant-design/v5-patch-for-react-19";

import { useEffect, useState, useCallback } from "react";
import {
  Tabs, Card, Tag, Button, Modal, Form, Input, InputNumber,
  Select, Space, Typography, App,
} from "antd";
import {
  EditOutlined,
} from "@ant-design/icons";
import {
  getModelRoutes, saveModelGroup, type ModelGroupItem,
} from "@/lib/server/admin-actions";

type ModelItem = Awaited<ReturnType<typeof getModelRoutes>>[number];

const serviceOptions = [
  { value: "novel", label: "小说" },
  { value: "legal", label: "法律" },
  { value: "finance", label: "金融" },
];

const roleOptions = [
  { value: "main", label: "主模型" },
  { value: "intent", label: "意图识别" },
  { value: "compress", label: "压缩" },
  { value: "rerank", label: "重排序" },
];

const roleColors: Record<string, string> = {
  main: "green", intent: "purple", compress: "orange", rerank: "cyan",
};

const providerOptions = [
  { value: "openai", label: "openai" },
  { value: "deepseek", label: "deepseek" },
  { value: "zhipu", label: "zhipu" },
  { value: "qwen", label: "qwen" },
  { value: "guiji", label: "guiji (硅基流动)" },
];

const serviceLabels: Record<string, string> = Object.fromEntries(
  serviceOptions.map((o) => [o.value, o.label]),
);
const roleLabels: Record<string, string> = Object.fromEntries(
  roleOptions.map((o) => [o.value, o.label]),
);

/** 按 serviceType → role → model[] 分组 */
function groupByServiceRole(data: ModelItem[]) {
  const map = new Map<string, Map<string, ModelItem[]>>();
  for (const item of data) {
    if (item.role === "pricing") continue;
    if (!map.has(item.serviceType)) map.set(item.serviceType, new Map());
    const roleMap = map.get(item.serviceType)!;
    if (!roleMap.has(item.role)) roleMap.set(item.role, []);
    roleMap.get(item.role)!.push(item);
  }
  return map;
}

// ── 模型条目行 ──

function ModelRow({ label, color, item }: { label: string; color: string; item: ModelItem }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "6px 0", borderBottom: "1px solid var(--color-border, #f0f0f0)",
    }}>
      <Tag color={color} style={{ margin: 0, flexShrink: 0, minWidth: 40, textAlign: "center" }}>
        {label}
      </Tag>
      <span style={{ flexShrink: 0, minWidth: 100, fontWeight: 500 }}>{item.provider}</span>
      <code style={{ flex: 1, color: "var(--color-text-secondary, #666)" }}>{item.modelName}</code>
      <span style={{ flexShrink: 0, fontSize: 13, color: "var(--color-text-tertiary, #999)", whiteSpace: "nowrap" }}>
        ￥{(item.inputPrice).toFixed(3)} / ￥{(item.outputPrice).toFixed(3)}
      </span>
    </div>
  );
}

// ── 角色卡片 ──

function RoleCard({
  serviceType, role, models, onEdit,
}: {
  serviceType: string;
  role: string;
  models: ModelItem[];
  onEdit: (serviceType: string, role: string) => void;
}) {
  const primary = models.find((m) => !m.isBackup);
  const backup = models.find((m) => m.isBackup);

  if (!primary && !backup) {
    return (
      <Card
        size="small"
        title={<span><Tag color={roleColors[role]}>{role}</Tag> {roleLabels[role] || role}</span>}
        extra={
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => onEdit(serviceType, role)}>
            配置
          </Button>
        }
        style={{ opacity: 0.5 }}
      >
        <div style={{ textAlign: "center", padding: "12px 0", color: "var(--color-text-tertiary, #999)" }}>
          暂未配置
        </div>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={<span>
        <Tag color={roleColors[role]}>{role}</Tag>
        {roleLabels[role] || role}
      </span>}
      extra={
        <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(serviceType, role)}>
          编辑
        </Button>
      }
    >
      {primary && <ModelRow label="主选" color="blue" item={primary} />}
      {backup && <ModelRow label="备用" color="orange" item={backup} />}
    </Card>
  );
}

// ── 编辑弹窗 ──

interface GroupFormValues {
  primary: { provider: string; modelName: string; inputPrice: number; outputPrice: number };
  backup: { provider: string; modelName: string; inputPrice: number; outputPrice: number };
}

function EditGroupModal({
  open, serviceType, role, models, saving,
  onSave, onCancel,
}: {
  open: boolean;
  serviceType: string;
  role: string;
  models: ModelItem[];
  saving: boolean;
  onSave: (serviceType: string, role: string, items: ModelGroupItem[]) => Promise<void>;
  onCancel: () => void;
}) {
  const [form] = Form.useForm<GroupFormValues>();
  const { message: msg } = App.useApp();

  useEffect(() => {
    if (!open) return;
    const primary = models.find((m) => !m.isBackup);
    const backup = models.find((m) => m.isBackup);
    form.setFieldsValue({
      primary: {
        provider: primary?.provider ?? "",
        modelName: primary?.modelName ?? "",
        inputPrice: primary ? primary.inputPrice : 0,
        outputPrice: primary ? primary.outputPrice : 0,
      },
      backup: {
        provider: backup?.provider ?? "",
        modelName: backup?.modelName ?? "",
        inputPrice: backup ? backup.inputPrice : 0,
        outputPrice: backup ? backup.outputPrice : 0,
      },
    });
  }, [open, models, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      const items: ModelGroupItem[] = [];

      items.push({
          provider: values.primary.provider,
          modelName: values.primary.modelName,
          inputPrice: values.primary.inputPrice,
          outputPrice: values.primary.outputPrice,
          isBackup: false,
          priority: 0,
        });

        items.push({
          provider: values.backup.provider,
          modelName: values.backup.modelName,
          inputPrice: values.backup.inputPrice,
          outputPrice: values.backup.outputPrice,
          isBackup: true,
          priority: 0,
        });

      await onSave(serviceType, role, items);
    } catch (e: unknown) {
      if (e && typeof e === "object" && "errorFields" in e) return;
      msg.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const label = roleLabels[role] || role;
  const serviceLabel = serviceLabels[serviceType] || serviceType;

  return (
    <Modal
      title={`编辑模型配置 — ${serviceLabel} / ${label}`}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={saving}
      okText="保存"
      width={800}
      forceRender
      destroyOnHidden
      styles={{ body: { paddingTop: 20, maxHeight: 480, overflowY: "auto" } }}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        {/* 主模型 */}
        <Typography.Text strong style={{ display: "block", marginBottom: 12 }}>
          主模型
        </Typography.Text>
        <div style={{ display: "flex", gap: 12, flexWrap: "nowrap", marginBottom: 8 }}>
          <Form.Item name={["primary", "provider"]} label="供应商" rules={[{ required: true, message: "必填" }]} style={{ flex: 1, minWidth: 0 }}>
            <Select options={providerOptions} />
          </Form.Item>
          <Form.Item name={["primary", "modelName"]} label="模型名" rules={[{ required: true, message: "必填" }]} style={{ flex: 1, minWidth: 0 }}>
            <Input placeholder="如 deepseek-v4-flash" />
          </Form.Item>
          <Form.Item name={["primary", "inputPrice"]} label="输入价（元/百万tokens）" rules={[{ required: true }]} style={{ flex: 1, minWidth: 0 }}>
            <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name={["primary", "outputPrice"]} label="输出价（元/百万tokens）" rules={[{ required: true }]} style={{ flex: 1, minWidth: 0 }}>
            <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
          </Form.Item>
        </div>

        {/* 备用模型 */}
        <Typography.Text strong style={{ display: "block", margin: "20px 0 12px" }}>
          备用模型
        </Typography.Text>
        <div style={{ display: "flex", gap: 12, flexWrap: "nowrap", marginBottom: 8 }}>
          <Form.Item name={["backup", "provider"]} label="供应商" rules={[{ required: true, message: "必填" }]} style={{ flex: 1, minWidth: 0 }}>
            <Select options={providerOptions} />
          </Form.Item>
          <Form.Item name={["backup", "modelName"]} label="模型名" rules={[{ required: true, message: "必填" }]} style={{ flex: 1, minWidth: 0 }}>
            <Input placeholder="如 deepseek-v4-flash" />
          </Form.Item>
          <Form.Item name={["backup", "inputPrice"]} label="输入价（元/百万tokens）" rules={[{ required: true }]} style={{ flex: 1, minWidth: 0 }}>
            <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name={["backup", "outputPrice"]} label="输出价（元/百万tokens）" style={{ flex: 1, minWidth: 0 }}>
            <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}

// ── 主页面 ──

export default function AdminModelRoutePage() {
  const { message: msg } = App.useApp();

  const [data, setData] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [serviceTab, setServiceTab] = useState<string>("novel");

  // 编辑弹窗状态
  const [modalOpen, setModalOpen] = useState(false);
  const [editServiceType, setEditServiceType] = useState<string>("");
  const [editRole, setEditRole] = useState<string>("");
  const [editModels, setEditModels] = useState<ModelItem[]>([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getModelRoutes();
      setData(list as ModelItem[]);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const grouped = groupByServiceRole(data);

  // 打开编辑弹窗
  const openEdit = (serviceType: string, role: string) => {
    const roleMap = grouped.get(serviceType);
    const models = roleMap?.get(role) ?? [];
    setEditServiceType(serviceType);
    setEditRole(role);
    setEditModels(models);
    setModalOpen(true);
  };

  // 保存模型组
  const handleSaveGroup = async (serviceType: string, role: string, items: ModelGroupItem[]) => {
    setSaving(true);
    try {
      await saveModelGroup(serviceType, role, items);
      msg.success("保存成功");
      setModalOpen(false);
      fetchData();
    } catch (e) {
      msg.error(`保存失败：${e instanceof Error ? e.message : "未知错误"}`);
    } finally { setSaving(false); }
  };

  const currentRoles = grouped.get(serviceTab) ?? new Map();

  return (
    <div>
      <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>模型路由管理</Typography.Title>
      </div>

      <Typography.Paragraph type="secondary" style={{ marginBottom: 16, fontSize: 13 }}>
        按服务与角色分组配置模型。每个角色可设一个主模型和一个可选备用模型。
        修改保存后需要重启后端服务使新配置生效。
      </Typography.Paragraph>

      <Tabs
        activeKey={serviceTab}
        onChange={setServiceTab}
        items={serviceOptions.map((svc) => ({
          key: svc.value,
          label: svc.label,
          children: (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(480px, 1fr))", gap: 16 }}>
              {roleOptions.map((ro) => (
                <RoleCard
                  key={ro.value}
                  serviceType={svc.value}
                  role={ro.value}
                  models={currentRoles.get(ro.value) ?? []}
                  onEdit={openEdit}
                />
              ))}
            </div>
          ),
        }))}
      />

      <EditGroupModal
        open={modalOpen}
        serviceType={editServiceType}
        role={editRole}
        models={editModels}
        saving={saving}
        onSave={handleSaveGroup}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
}