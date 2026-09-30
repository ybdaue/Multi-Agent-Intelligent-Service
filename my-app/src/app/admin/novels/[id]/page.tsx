"use client";

import "@ant-design/v5-patch-for-react-19";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Table, Tag, Button, Space, Popconfirm, Typography, App, Modal, Input, Descriptions, Card } from "antd";
import { ArrowLeftOutlined, StopOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { getNovelDetail, banChapter, unbanChapter } from "@/lib/server/admin-actions";

type NovelDetail = Awaited<ReturnType<typeof getNovelDetail>>;
type ChapterItem = NonNullable<NovelDetail>["chapters"][number];

const statusLabel: Record<string, string> = { draft: "草稿", published: "已发布" };
const statusColor: Record<string, string> = { draft: "default", published: "green" };

export default function AdminNovelDetailPage() {
  const { message: msg } = App.useApp();
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [data, setData] = useState<NovelDetail>(null);
  const [loading, setLoading] = useState(true);
  const [banChapterTarget, setBanChapterTarget] = useState<ChapterItem | null>(null);
  const [banReason, setBanReason] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const detail = await getNovelDetail(id);
      setData(detail as NovelDetail);
    } catch { msg.error("加载失败"); }
    finally { setLoading(false); }
  }, [id, msg]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBanChapter = async () => {
    if (!banChapterTarget) return;
    try {
      await banChapter(banChapterTarget.id, banReason || undefined);
      msg.success("章节已封禁");
      setBanChapterTarget(null);
      setBanReason("");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  const handleUnbanChapter = async (chId: string) => {
    try {
      await unbanChapter(chId);
      msg.success("章节已解封");
      fetchData();
    } catch (e: unknown) { msg.error(e instanceof Error ? e.message : "操作失败"); }
  };

  if (!data && !loading) {
    return <div style={{ padding: 24, color: "#999" }}>小说不存在</div>;
  }

  const chapterColumns = [
    { title: "序号", dataIndex: "order", width: 60 },
    { title: "标题", dataIndex: "title", width: 200, ellipsis: true, render: (v: string) => v || "(无标题)" },
    { title: "状态", dataIndex: "status", width: 80, render: (v: string) => <Tag color={statusColor[v] ?? "default"}>{statusLabel[v] ?? v}</Tag> },
    { title: "字数", dataIndex: "wordCount", width: 70 },
    {
      title: "封禁", dataIndex: "banned", width: 80,
      render: (v: boolean) => <Tag color={v ? "red" : "green"}>{v ? "已封禁" : "正常"}</Tag>,
    },
    { title: "封禁原因", dataIndex: "banReason", width: 150, ellipsis: true, render: (v: string | null) => v ?? "-" },
    { title: "创建时间", dataIndex: "createdAt", width: 150, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: "操作", width: 120, fixed: "right" as const,
      render: (_: unknown, r: ChapterItem) => (
        r.banned ? (
          <Popconfirm title="确定解封该章节？" onConfirm={() => handleUnbanChapter(r.id)}>
            <Button size="small" type="link" icon={<CheckCircleOutlined />} style={{ color: "#52c41a" }}>解封</Button>
          </Popconfirm>
        ) : (
          <Button size="small" type="link" danger icon={<StopOutlined />} onClick={() => { setBanChapterTarget(r); setBanReason(""); }}>
            封禁
          </Button>
        )
      ),
    },
  ];

  return (
    <div>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => router.push("/admin/novels")} style={{ marginBottom: 12, padding: 0 }}>
        返回小说列表
      </Button>

      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        小说详情：{data?.title || "(无标题)"}
      </Typography.Title>

      {/* 小说元信息 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="ID">{data?.id}</Descriptions.Item>
          <Descriptions.Item label="用户ID">{data?.userId}</Descriptions.Item>
          <Descriptions.Item label="字数">{data?.wordCount}</Descriptions.Item>
          <Descriptions.Item label="风格">{data?.style ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="套路">{data?.tropes ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="封禁状态">
            <Tag color={data?.banned ? "red" : "green"}>{data?.banned ? "已封禁" : "正常"}</Tag>
          </Descriptions.Item>
          {data?.banned && (
            <>
              <Descriptions.Item label="封禁原因">{data?.banReason ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="封禁时间">{data?.bannedAt ? new Date(data.bannedAt).toLocaleString() : "-"}</Descriptions.Item>
            </>
          )}
          <Descriptions.Item label="创建时间">{data?.createdAt ? new Date(data.createdAt).toLocaleString() : "-"}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{data?.updatedAt ? new Date(data.updatedAt).toLocaleString() : "-"}</Descriptions.Item>
          <Descriptions.Item label="关联数">
            大纲 {data?._count?.outlines ?? 0} / 规则 {data?._count?.rules ?? 0} / 时间线 {data?._count?.timelines ?? 0} / 势力 {data?._count?.factions ?? 0}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 章节列表 */}
      <Typography.Title level={5} style={{ marginBottom: 12 }}>章节列表</Typography.Title>
      <Table
        dataSource={data?.chapters ?? []}
        columns={chapterColumns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
        scroll={{ x: 900 }}
        locale={{ emptyText: "暂无章节" }}
      />

      {/* 封禁章节弹窗 */}
      <Modal
        title="封禁章节"
        open={!!banChapterTarget}
        onCancel={() => setBanChapterTarget(null)}
        onOk={handleBanChapter}
        okText="确认封禁"
        okButtonProps={{ danger: true }}
      >
        <p>确定封禁章节「{banChapterTarget?.title || `第${banChapterTarget?.order}章`}」？</p>
        <p style={{ fontSize: 12, color: "#999" }}>封禁后用户将无法查看该章节内容</p>
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