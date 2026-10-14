"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlignLeftOutlined,
  BorderOutlined,
  BulbOutlined,
  ClearOutlined,
  CloseOutlined,
  FileTextOutlined,
  LinkOutlined,
  LoadingOutlined,
  PictureOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Switch } from "antd";
import InspirationPicker from "../InspirationPicker";
import type { InspirationItem, Message } from "../types";
import styles from "./index.module.scss";

/** 这些按钮只把预设提示词填进输入框，不直接发起请求；灵感提示另开弹窗 */
const TOOL_PROMPTS = [
  { label: "润色", prompt: "请润色本章正文，保持情节与人物不变，优化文笔和节奏。" },
  { label: "扩写", prompt: "请扩写本章正文，补充细节描写与环境氛围，不改变原有情节走向。" },
  { label: "缩写", prompt: "请缩写本章正文，保留关键情节，让语言更凝练。" },
  { label: "重写", prompt: "请重写本章正文，换一个叙事切入点，主要情节保持不变。" },
];

interface AiPanelProps {
  messages: Message[];
  onSend: (text: string, attachments: InspirationItem[]) => void;
  /** 这本书的 id（= threadId）：从灵感库挑灵感时要它去拉这本书的灵感列表 */
  threadId: string | null;
  /** 当前进度文案（"正在写这一章…"），空串表示没有在跑的活 */
  stage: string;
  /** 整个面板封掉：本轮还没跑完（别在同一 thread 上叠第二轮），或本轮在别的章上跑 */
  disabled: boolean;
  /** 这一轮的流还开着（能掐断）。跟 disabled 不是一回事：等答复时流已经关了 */
  running: boolean;
  /** 掐断这一轮生成 */
  onStop: () => void;
  /** 图在等用户答复，输入框的提示语跟着换 */
  pendingQuestion: boolean;
  /** 停在确认上时后端给的出口（收下 / 按库里改）。为空就是普通提问，照旧打字答 */
  answerOptions: { id: string; label: string }[];
  /** 点了出口按钮：按它答，不用打字 */
  onAnswer: (option: { id: string; label: string }) => void;
  /** 清空这本书的对话记录（后端那份一起清，刷新后不会回来） */
  onClear: () => void;
  /** 这本书的 AI 审稿开关；切换即写入 novel.reviewEnabled */
  reviewEnabled: boolean;
  onToggleReview: (on: boolean) => void;
}

function AttachmentIcon({ kind }: { kind: InspirationItem["kind"] }) {
  if (kind === "image") return <PictureOutlined />;
  if (kind === "file") return <FileTextOutlined />;
  if (kind === "text") return <AlignLeftOutlined />;
  return <LinkOutlined />;
}

export default function AiPanel({
  messages,
  onSend,
  threadId,
  stage,
  disabled,
  running,
  onStop,
  pendingQuestion,
  answerOptions,
  onAnswer,
  onClear,
  reviewEnabled,
  onToggleReview,
}: AiPanelProps) {
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<InspirationItem[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, stage]);

  const canSend = (input.trim().length > 0 || attachments.length > 0) && !disabled;

  const send = () => {
    if (!canSend) return;
    onSend(input.trim(), attachments);
    setInput("");
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <section className={styles.panel}>
      <div className={styles.toolBar}>
        {TOOL_PROMPTS.map((t) => (
          <button
            key={t.label}
            type="button"
            className={styles.toolBtn}
            title={t.prompt}
            disabled={disabled}
            onClick={() => setInput(t.prompt)}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          className={styles.toolBtn}
          title="从灵感库挑选用在本章的灵感（挑中的这一章必须用）"
          disabled={disabled}
          onClick={() => setModalOpen(true)}
        >
          <BulbOutlined />
          <span>灵感提示</span>
        </button>
      </div>

      <div ref={scrollRef} className={styles.chatArea}>
        {messages.length === 0 && !stage && !running ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyAvatar}>
              <RobotOutlined />
            </div>
            <p className={styles.emptyText}>
              想怎么写这一章？
              <br />
              点上方工具按钮，或直接说出你的要求。
            </p>
          </div>
        ) : (
          <div className={styles.messageList}>
            {messages.map((m) => (
              <div
                key={m.id}
                className={`${styles.messageRow} ${m.role === "user" ? styles.user : ""}`}
              >
                <div className={styles.avatarWrap}>
                  {m.role === "assistant" ? <RobotOutlined /> : <UserOutlined />}
                </div>
                <div className={styles.bubbleWrap}>
                  {m.attachments && m.attachments.length > 0 && (
                    <div className={styles.chips}>
                      {m.attachments.map((a) =>
                        a.kind === "image" && a.preview ? (
                          // eslint-disable-next-line @next/next/no-img-element -- data URL 本地预览，无远程加载可优化
                          <img
                            key={a.id}
                            className={styles.chipThumb}
                            src={a.preview}
                            alt={a.name}
                            title={a.name}
                          />
                        ) : (
                          <span key={a.id} className={styles.chip} title={a.name}>
                            <AttachmentIcon kind={a.kind} />
                            <span className={styles.chipName}>{a.name}</span>
                          </span>
                        ),
                      )}
                    </div>
                  )}
                  {m.content && <div className={styles.bubble}>{m.content}</div>}
                </div>
              </div>
            ))}

            {/* 出口按钮：挂在等答复那一问下面，跟打字答走同一条路（见 NovelWorkspace 的
                onAnswer），只是不必让用户把"收下"两个字打出来 */}
            {answerOptions.length > 0 && (
              <div className={styles.messageRow}>
                <div className={styles.avatarWrap}>
                  <RobotOutlined />
                </div>
                <div className={styles.bubbleWrap}>
                  <div className={styles.answerRow}>
                    {answerOptions.map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        className={styles.answerBtn}
                        disabled={disabled}
                        onClick={() => onAnswer(option)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 进度行：这一轮走到哪个节点了，后端按节点名报，不掺模型输出 */}
            {stage && (
              <div className={styles.messageRow}>
                <div className={styles.avatarWrap}>
                  <RobotOutlined />
                </div>
                <div className={styles.bubbleWrap}>
                  <div className={`${styles.bubble} ${styles.stageBubble}`}>
                    <LoadingOutlined className={styles.stageIcon} />
                    {stage}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* AI 审稿开关：输入框上方单独一行，靠左 */}
      <div className={styles.reviewBar}>
        <span className={styles.reviewLabel} title="关掉后 AI 写完不再审稿，直接进入确认">
          AI 审稿
        </span>
        <Switch size="small" checked={reviewEnabled} onChange={onToggleReview} />
      </div>

      <div className={styles.composer}>
        {attachments.length > 0 && (
          <div className={styles.staged}>
            {attachments.map((a) => (
              <span key={a.id} className={styles.chip} title={a.name}>
                <AttachmentIcon kind={a.kind} />
                <span className={styles.chipName}>{a.name}</span>
                <button
                  type="button"
                  className={styles.chipRemove}
                  onClick={() =>
                    setAttachments((prev) => prev.filter((i) => i.id !== a.id))
                  }
                  title="移除素材"
                  aria-label="移除素材"
                >
                  <CloseOutlined />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className={styles.inputRow}>
          {/* 清空这本的整段对话。正等答复时不给清：那一稿还没确认落库，后端也不收（它会回一句
              让人先把这一稿定下来）—— 清历史会把那一问从快照上抹掉，那一稿就没人看得见了 */}
          <button
            type="button"
            className={styles.clearBtn}
            onClick={onClear}
            disabled={disabled || pendingQuestion || messages.length === 0}
            title="清空对话记录"
            aria-label="清空对话记录"
          >
            <ClearOutlined />
          </button>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            value={input}
            rows={1}
            disabled={disabled}
            placeholder={
              disabled
                ? "AI 正在处理，稍候…"
                : pendingQuestion
                  ? "回复上面的问题：收下，或说一句往哪儿改"
                  : "Enter发送、Shift+Enter换行即可"
            }
            onChange={(e) => {
              const el = e.target;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
              setInput(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          {/* 在跑就把发送换成停止：这一轮跑着的时候本来也发不出第二条，掐断它才是当下能做的事。
              不给 disabled 门禁（面板正封着才最需要它）。 */}
          {running ? (
            <button
              type="button"
              className={styles.stopBtn}
              onClick={onStop}
              title="停止生成"
              aria-label="停止生成"
            >
              <BorderOutlined />
            </button>
          ) : (
            <button
              type="button"
              className={styles.sendBtn}
              onClick={send}
              disabled={!canSend}
              title="发送"
              aria-label="发送"
            >
              <SendOutlined />
            </button>
          )}
        </div>
      </div>

      {modalOpen && (
        <InspirationPicker
          threadId={threadId}
          onClose={() => setModalOpen(false)}
          onConfirm={(items) => {
            // 只暂存到输入框附件区，由用户补完文字后自行发送
            setAttachments((prev) => [...prev, ...items]);
          }}
        />
      )}
    </section>
  );
}
