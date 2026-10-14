"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CloseOutlined,
  LoadingOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { NovelAgentHandlers } from "../useNovelAgent";
import { useNovelAgent } from "../useNovelAgent";
import SetupSettingsPanel from "./SetupSettingsPanel";
import { FIELD_LABELS } from "./types";
import styles from "./index.module.scss";

interface NewNovelModalProps {
  onClose: () => void;
  /** 书已经在库里了：父组件拿这个 id 重拉书架并选中它 */
  onCreated: (novelId: string) => void;
}

interface Line {
  id: number;
  role: "user" | "assistant";
  content: string;
  /** 这一条还在逐字长：后续的 token 接在它后面，问题到了就收尾 */
  streaming?: boolean;
}

/** 开书轮的 thread id 就是小说 id，由这里发：uuid 撞车概率为零，也就没人能拿一个猜到的 id 去覆盖别人的书 */
function newNovelId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `novel-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const OPENING = "我要开一本书";

let seq = 0;
function nextId() {
  seq += 1;
  return seq;
}

/**
 * 新建小说：设定一问一答全在这个弹窗里走完。
 *
 * 弹窗一打开就直接调 run 接口，不再显示静态开场白 —— 开书 agent（后端 agents/novel/setup）
 * 会先给一个友好的提问开场。逐项给选项、用户说"你定"就替他拟一版过目。
 * 六项齐了请用户过目，认可了才落库，回 onCreated 让工作区切过去。
 *
 * 打字机是后端真流：散文逐字从 SSE 下来，标记块在服务端就被截掉了（api/novel/stream.py
 * 的 SettingFilter），所以这里只管把 token 接在气泡后面。问题到了就整段替换 —— 两者字节一致，
 * 看不出跳变。
 *
 * 关掉 = 本次创建作废，所以**只能按按钮关**（右上角 ×、页脚「放弃 / 取消」）—— 点空白处、
 * 按 Esc 一律不响应，免得误触把半本还没落库的书判成失败。收设定期间也能关：按下去先把在飞的
 * 那轮请求 abort 掉，再关窗；半途而废就跟没建过一样，重开一次即可。
 */
export default function NewNovelModal({ onClose, onCreated }: NewNovelModalProps) {
  const [novelId] = useState(newNovelId);
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const [stage, setStage] = useState("");
  /** 开书那一轮已经发出去了：此后输入框是在答 agent 的提问，不再是开场白 */
  const [started, setStarted] = useState(false);
  const [waiting, setWaiting] = useState(false);
  /** 这一轮炸了：只能关掉重来，别再往同一个 thread 上叠 */
  const [failed, setFailed] = useState(false);
  /** 设定面板刷新计数器：每次 SSE question/final +1，传给面板组件触发重拉 */
  const [settingsRevision, setSettingsRevision] = useState(0);
  const { run, resume, stop, busy } = useNovelAgent("setup");
  const scrollRef = useRef<HTMLDivElement>(null);

  const push = useCallback((role: Line["role"], content: string) => {
    setLines((prev) => [...prev, { id: nextId(), role, content }]);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, stage]);

  const handlers: NovelAgentHandlers = {
    onToken: (chunk) => {
      setStage("");
      setLines((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, content: last.content + chunk }];
        }
        return [...prev, { id: nextId(), role: "assistant", content: chunk, streaming: true }];
      });
    },
    onQuestion: (question) => {
      // 流下来的 token 拼起来就是这句话，整段替换：接着往下打的观感，不跳变。
      // 开书这条路只发 text（没有按钮、没有待确认的稿），所以这里只取它。
      setLines((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, content: question.text, streaming: false }];
        }
        return [...prev, { id: nextId(), role: "assistant", content: question.text }];
      });
      setWaiting(true);
      setStage("");
      setSettingsRevision((n) => n + 1);
    },
    onFinal: (data) => {
      setWaiting(false);
      setStage("");
      setSettingsRevision((n) => n + 1);
      if (data.saved) {
        onCreated(data.novelId || novelId);
        return;
      }
      // 没落库（重复提交同一个 id 之外不该发生）：给一句兜底，别让用户对着空白猜
      push("assistant", data.message || "这本书没建成，关掉重来一次。");
      setFailed(true);
    },
    onError: (message) => {
      push("assistant", `[出错] ${message}`);
      setWaiting(false);
      setStage("");
      setFailed(true);
    },
  };

  const autoStarted = useRef(false);

  // 弹窗打开即默认调 run 接口，不显示用户气泡
  useEffect(() => {
    if (autoStarted.current) return;
    autoStarted.current = true;
    setStarted(true);
    setStage("正在想怎么问…");
    run(novelId, OPENING, "", handlers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useCallback(() => {
    if (busy || failed || !waiting) return;
    const text = input.trim();
    if (!text) return;
    push("user", text);
    setInput("");
    setWaiting(false);
    setStage("正在想怎么接着问…");
    resume(novelId, text, "", handlers);
  }, [busy, failed, waiting, input, push, resume, novelId, handlers]);

  /** 用户通过右侧面板编辑了一项设定：构造系统消息发给 agent */
  const handleEdit = useCallback(
    (field: string, content: string) => {
      if (busy || failed || !waiting) return;
      // 格式与后端 settings.py 的 SETTING_MARK / SETTING_END 一致，maintain 节点能解析
      const editText = `用户修改了设定项「${field}」为：\n【设定项】${field}\n【内容】${content}\n【设定结束】`;
      const label = FIELD_LABELS[field] || field;
      // 结构化项的内容是 JSON，气泡里别摆原文，能解就摊成"值、值"
      let preview = content;
      try {
        const obj = JSON.parse(content);
        if (obj && typeof obj === "object") {
          preview = Object.values(obj).filter(Boolean).join("、");
        }
      } catch {
        // 非 JSON（书名/核心冲突等散文项），原样显示
      }
      push("user", `✏️ 修改了「${label}」：\n${preview}`);
      setWaiting(false);
      setStage("正在处理修改…");
      resume(novelId, editText, "", handlers);
    },
    [busy, failed, waiting, push, resume, novelId, handlers],
  );

  const canSend = !busy && !failed && waiting && input.trim().length > 0;

  /** 中途退出：先把在飞的这轮请求 aborted 掉，再关窗（关掉 = 本次创建作废，书没落库）。 */
  const abandon = useCallback(() => {
    stop();
    onClose();
  }, [stop, onClose]);

  return (
    <div className={styles.backdrop}>
      <div className={`${styles.dialog} ${styles.withPanel}`} role="dialog" aria-modal="true" aria-label="新建小说">
        <div className={styles.header}>
          <span className={styles.title}>新建小说</span>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={abandon}
            title={busy ? "中断本次设定，关掉弹窗" : "关闭"}
            aria-label="关闭"
          >
            <CloseOutlined />
          </button>
        </div>

        <div className={styles.mainArea}>
          {/* 左侧：聊天区 + 输入框 */}
          <div className={styles.chatColumn}>
            <div ref={scrollRef} className={styles.body}>
              {lines.map((line) => (
                <div
                  key={line.id}
                  className={`${styles.row} ${line.role === "user" ? styles.mine : styles.bot}`}
                >
                  <div className={styles.avatar}>
                    {line.role === "user" ? <UserOutlined /> : <RobotOutlined />}
                  </div>
                  <div className={styles.bubble}>{line.content}</div>
                </div>
              ))}

              {stage && (
                <div className={`${styles.row} ${styles.bot}`}>
                  <div className={styles.avatar}>
                    <RobotOutlined />
                  </div>
                  <div className={`${styles.bubble} ${styles.stageBubble}`}>
                    <LoadingOutlined className={styles.stageIcon} />
                    {stage}
                  </div>
                </div>
              )}
            </div>

            <div className={styles.composer}>
              <textarea
                className={styles.textarea}
                value={input}
                rows={2}
                disabled={busy || failed}
                placeholder={
                  failed
                    ? "本次创建已中止，关掉重来"
                    : "答这一项：说你的想法，或者直接说「你定」"
                }
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              <button
                type="button"
                className={styles.sendBtn}
                onClick={() => submit()}
                disabled={!canSend}
                title="发送"
                aria-label="发送"
              >
                {busy ? <LoadingOutlined /> : <SendOutlined />}
              </button>
            </div>
          </div>

          {/* 右侧：设定面板 */}
          <SetupSettingsPanel
            novelId={novelId}
            revision={settingsRevision}
            canEdit={waiting && !busy && !failed}
            onEdit={handleEdit}
          />
        </div>

        <div className={styles.footer}>
          <span className={styles.hint}>
            {busy
              ? "正在收集设定，中途放弃可就白搭了"
              : failed
                ? "没有建成，关掉重来一次即可"
                : "设定收齐并确认后，这本书就建好了"}
          </span>
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={abandon}
          >
            {started ? "放弃" : "取消"}
          </button>
        </div>
      </div>
    </div>
  );
}