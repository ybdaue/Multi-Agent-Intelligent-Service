"use client";

import "@ant-design/v5-patch-for-react-19";

import { useEffect, useState, useCallback } from "react";
import { Table, Tag, Button, Select, Input, Space, Popconfirm, Typography, App, Modal } from "antd";
import { SearchOutlined, EyeOutlined, StopOutlined, CheckCircleOutlined, DeleteOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { getNovels, banNovel, unbanNovel, deleteNovel } from "@/lib/server/admin-actions";

type NovelRecord = Awaited<ReturnType<typeof getNovels>>["novels"][number];

export default function AdminNovelsPage() {
  const { message: msg } = App.useApp();
  const router = useRouter();

  const [data, setData] = useState<{ total: number; page: number; pageSize: number; novels: NovelRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [bannedFilter, setBannedFilter] = useState<string>("");
  const [banReason, setBanReason] = useState("");
  const [banTarget, setBanTarget] = useState<NovelRecord | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getNovels({
        search: search || undefined,
        page,
        pageSize: 12,
        banned: bannedFilter === "" ? undefined : bannedFilter === "true",
      });
      setData(result as typeof data);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [search, page, bannedFilter, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBan = async () => {
    if (!banTarget) return;
    try {
      await banNovel(banTarget.id, banReason || undefined);
      msg.success("已封禁");
      setBanTarget(null);
      setBanReason("");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  const handleUnban = async (id: string) => {
    try {
      await unbanNovel(id);
      msg.success("已解封");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteNovel(id);
      msg.success("已删除");
      fetchData();
    } catch { msg.error("删除失败"); }
  };

  const columns = [
    { title: "标题", dataIndex: "title", width: 200, ellipsis: true, render: (v: string) => v || "(无标题)" },
    { title: "用户ID", dataIndex: "userId", width: 180, ellipsis: true },
    { title: "字数", dataIndex: "wordCount", width: 80 },
    { title: "风格", dataIndex: "style", width: 100, render: (v: string | null) => v ?? "-" },
    { title: "章节数", width: 80, render: (_: unknown, r: NovelRecord) => r._count.chapters },
    { title: "角色数", width: 80, render: (_: unknown, r: NovelRecord) => r._count.characters },
    {
      title: "封禁状态", dataIndex: "banned", width: 90,
      render: (v: boolean) => <Tag color={v ? "red" : "green"}>{v ? "已封禁" : "正常"}</Tag>,
    },
    { title: "创建时间", dataIndex: "createdAt", width: 160, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: "操作", width: 200, fixed: "right" as const,
      render: (_: unknown, r: NovelRecord) => (
        <Space>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => router.push(`/admin/novels/${r.id}`)}>
            详情
          </Button>
          {r.banned ? (
            <Popconfirm title="确定解封该小说？" onConfirm={() => handleUnban(r.id)}>
              <Button size="small" type="link" icon={<CheckCircleOutlined />} style={{ color: "#52c41a" }}>解封</Button>
            </Popconfirm>
          ) : (
            <Button size="small" type="link" danger icon={<StopOutlined />} onClick={() => { setBanTarget(r); setBanReason(""); }}>
              封禁
            </Button>
          )}
          <Popconfirm title="确定删除该小说？此操作不可恢复。" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>小说管理</Typography.Title>

      <div style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          placeholder="搜索标题 / ID"
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          style={{ width: 220 }}
          allowClear
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
      </div>

      <Table
        dataSource={data?.novels ?? []}
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
        locale={{ emptyText: "暂无小说" }}
      />

      <Modal
        title="封禁小说"
        open={!!banTarget}
        onCancel={() => setBanTarget(null)}
        onOk={handleBan}
        okText="确认封禁"
        okButtonProps={{ danger: true }}
      >
        <p>确定封禁小说「{banTarget?.title}」？</p>
        <p style={{ fontSize: 12, color: "#999" }}>封禁后用户将无法访问该小说及其章节内容</p>
        <Input.TextArea
          placeholder="封禁原因（可选）"
          value={banReason}
          onChange={(e) => setBanReason(e.target.value)}
          rows={3}
          style={{ marginTop: 8 }}
        />
      </Modal>
    </div>
  );
}