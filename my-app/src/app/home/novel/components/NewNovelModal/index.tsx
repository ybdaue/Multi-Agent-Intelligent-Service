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

const SEED_HINT = "帮我开一本书，你来问我。";

let seq = 0;
function nextId() {
  seq += 1;
  return seq;
}

/**
 * 新建小说：设定一问一答全在这个弹窗里走完。
 *
 * 开场白可以很模糊 —— 开书 agent（后端 agents/novel/setup）照 setupSkill 逐项给选项、
 * 用户说"你定"就替他拟一版过目。六项齐了请用户过目，认可了才落库，回 onCreated 让工作区
 * 切过去（这一轮不写第一章）。
 *
 * 打字机是后端真流：散文逐字从 SSE 下来，标记块在服务端就被截掉了（api/novel/stream.py
 * 的 SettingFilter），所以这里只管把 token 接在气泡后面。问题到了就整段替换 —— 两者字节一致，
 * 看不出跳变。
 *
 * 关掉 = 本次创建作废，所以**只能按按钮关**（右上角 ×、页脚「放弃 / 取消」）—— 点空白处、
 * 按 Esc 一律不响应，收设定期间按钮本身也禁用：一次误触就把这半本还没落库的书判成失败，
 * 用户会对着"没建成"的结论去找一本其实存在的书。
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
  const { run, resume, busy } = useNovelAgent("setup");
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
      setLines((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, content: question, streaming: false }];
        }
        return [...prev, { id: nextId(), role: "assistant", content: question }];
      });
      setWaiting(true);
      setStage("");
    },
    onFinal: (data) => {
      setWaiting(false);
      setStage("");
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

  const submit = () => {
    if (busy || failed) return;
    const text = input.trim();

    if (!started) {
      push("user", text || SEED_HINT);
      setInput("");
      setStarted(true);
      setStage("正在想怎么问…");
      run(novelId, text || SEED_HINT, "", handlers);
      return;
    }
    if (!waiting || !text) return;
    push("user", text);
    setInput("");
    setWaiting(false);
    setStage("正在想怎么接着问…");
    resume(novelId, text, "", handlers);
  };

  const canSend = !busy && !failed && (started ? waiting && input.trim().length > 0 : true);

  return (
    <div className={styles.backdrop}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="新建小说">
        <div className={styles.header}>
          <span className={styles.title}>新建小说</span>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            disabled={busy}
            title={busy ? "设定还没收完，先答完再关" : "关闭"}
            aria-label="关闭"
          >
            <CloseOutlined />
          </button>
        </div>

        <div ref={scrollRef} className={styles.body}>
          <div className={`${styles.row} ${styles.bot}`}>
            <div className={styles.avatar}>
              <RobotOutlined />
            </div>
            <div className={styles.bubble}>
              想开一本什么样的书？随便说，模糊也行 —— 书名、题材、主角、核心冲突这些，
              我会照着畅销书的套路一项一项问你，你拿不准就说「你定」。
            </div>
          </div>

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
                : started
                  ? "答这一项：说你的想法，或者直接说「你定」"
                  : "例如：都市修仙，主角靠金手指一路打脸（也可以留空，我来问）"
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
            onClick={submit}
            disabled={!canSend}
            title={started ? "发送" : "开始"}
            aria-label={started ? "发送" : "开始"}
          >
            {busy ? <LoadingOutlined /> : <SendOutlined />}
          </button>
        </div>

        <div className={styles.footer}>
          <span className={styles.hint}>
            {busy
              ? "正在收集设定，答完这一项才能关…"
              : failed
                ? "没有建成，关掉重来一次即可"
                : "设定收齐并确认后，这本书就建好了"}
          </span>
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={onClose}
            disabled={busy}
          >
            {started ? "放弃" : "取消"}
          </button>
        </div>
      </div>
    </div>
  );
}
