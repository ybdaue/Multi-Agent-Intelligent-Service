"use client";

import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";
import {
  AlignLeftOutlined,
  CloseOutlined,
  FileTextOutlined,
  LinkOutlined,
  LoadingOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import {
  INSPIRATION_CATEGORY_OPTIONS,
  INSPIRATION_USAGE_OPTIONS,
  type InspirationCategory,
  type InspirationItem,
  type InspirationKind,
  type InspirationUsage,
} from "../types";
import styles from "./index.module.scss";

interface InspirationModalProps {
  onClose: () => void;
  onConfirm: (
    items: InspirationItem[],
    categories?: InspirationCategory[],
    usage?: InspirationUsage,
    /** 提交中关窗（X / 取消 / Esc / 点背景）会 abort 它，让这趟翻译请求连后端一起断掉 */
    signal?: AbortSignal,
  ) => void | Promise<void>;
  /** 默认 true（聊天框的素材弹窗仍能传图）；灵感库那边传 false 去掉图片 */
  allowImage?: boolean;
  /** 是否给"文本"输入（灵感库那边开着，可直接敲一段文字当灵感） */
  allowText?: boolean;
  /** 是否显示内容类型 / 使用策略选择（灵感库那边开着）；生命周期固定，不进弹窗 */
  showCategory?: boolean;
  /** 弹窗标题，默认"添加灵感素材" */
  title?: string;
  /**
   * 单素材模式（灵感库用）：一次只收**一条**灵感，文件 / 链接 / 文本三选一，且不设存放列表 ——
   * 选中的文件就地显示，链接 / 文本则等到确定时按当前输入拼一条。聊天框用默认的多素材模式，
   * 图片 / 文件 / 链接可以一下凑一批。
   */
  single?: boolean;
}

let seq = 0;
function createId() {
  seq += 1;
  return `insp-${Date.now().toString(36)}-${seq}`;
}

/** 分类 → 默认使用策略：风格必用，其余选用。与后端 default_usage 对齐。 */
function defaultUsage(cats: InspirationCategory[]): InspirationUsage {
  return cats.includes("style") ? "must" : "selectable";
}

/** 图片读成 data URL，省去 object URL 的创建/回收生命周期 */
function toDataUrl(file: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => resolve("");
    reader.readAsDataURL(file);
  });
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 一段文本的头一行当名字，太长就截断（列表里显示 / 落库名用） */
function textName(raw: string) {
  const head = raw.split("\n")[0].replace(/\s+/g, " ").trim();
  if (!head) return "文本灵感";
  return head.length > 24 ? `${head.slice(0, 24)}…` : head;
}

/** 只粘贴域名时补上协议，避免生成不可点开的链接 */
function toUrl(raw: string) {
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
}

export default function InspirationModal({
  onClose,
  onConfirm,
  allowImage = true,
  allowText = false,
  showCategory = false,
  title = "添加灵感素材",
  single = false,
}: InspirationModalProps) {
  const [items, setItems] = useState<InspirationItem[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [textInput, setTextInput] = useState("");
  const [categories, setCategories] = useState<InspirationCategory[]>(["other"]);
  const [usage, setUsage] = useState<InspirationUsage>("selectable");
  // 用户手动点过 usage 后就不再跟着分类自动改（换标签不覆盖用户的选择）
  const [usagePinned, setUsagePinned] = useState(false);
  const [mode, setMode] = useState<Exclude<InspirationKind, "image">>("file");
  // 确认后进入提交态：等父级把素材翻译、落库完（onConfirm 的 Promise 兑现）才关弹窗
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  // 提交中那次翻译请求的控制器：关窗时 abort，连后端一起取消
  const abortRef = useRef<AbortController | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** 关窗：若正在提交就把请求 abort 掉（"取消了却还落库"很反直觉），再交回父级关闭 */
  const close = useCallback(() => {
    abortRef.current?.abort();
    onClose();
  }, [onClose]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close]);

  const addImages = async (files: FileList) => {
    // 单素材模式只收第一张（文件 input 已关掉 multiple，这里再兜一道）。
    const list = Array.from(files);
    const picked = await Promise.all(
      (single ? list.slice(0, 1) : list).map(async (file) => ({
        id: createId(),
        kind: "image" as const,
        name: file.name,
        size: file.size,
        file,
        preview: await toDataUrl(file),
      })),
    );
    setItems((prev) => (single ? picked : [...prev, ...picked]));
  };

  const addFiles = (files: FileList) => {
    const list = Array.from(files);
    const picked = (single ? list.slice(0, 1) : list).map((file) => ({
      id: createId(),
      kind: "file" as const,
      name: file.name,
      size: file.size,
      file,
    }));
    setItems((prev) => (single ? picked : [...prev, ...picked]));
  };

  const addUrl = () => {
    const raw = urlInput.trim();
    if (!raw) return;
    const url = toUrl(raw);
    const item = { id: createId(), kind: "url" as const, name: url, url };
    setItems((prev) => (single ? [item] : [...prev, item]));
    setUrlInput("");
  };

  const addText = () => {
    const raw = textInput.trim();
    if (!raw) return;
    const item = { id: createId(), kind: "text" as const, name: textName(raw), text: raw };
    setItems((prev) => (single ? [item] : [...prev, item]));
    setTextInput("");
  };

  const remove = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  /** 切形态：把上一种形态留下的内容全清掉，避免确定时拼进脏数据 */
  const switchMode = (next: Exclude<InspirationKind, "image">) => {
    if (next === mode) return;
    setMode(next);
    setItems([]);
    setUrlInput("");
    setTextInput("");
  };

  const toggleCategory = (value: InspirationCategory) => {
    const next = categories.includes(value)
      ? categories.filter((c) => c !== value)
      : [...categories, value];
    setCategories(next);
    // 没被手动锁定过就跟着分类走：选了风格→必用
    if (!usagePinned) setUsage(defaultUsage(next));
  };

  // 单素材模式下可选的形态（顺带复用成"形态切换"按钮）；聊天框不走这条。
  const modes: {
    value: Exclude<InspirationKind, "image">;
    label: string;
    Icon: ComponentType<{ className?: string }>;
  }[] = [
    { value: "file", label: "上传文件", Icon: FileTextOutlined },
    { value: "url", label: "添加链接", Icon: LinkOutlined },
    ...(allowText
      ? [{ value: "text" as const, label: "写文本", Icon: AlignLeftOutlined }]
      : []),
  ];

  /** 单素材模式下当前形态攒出来的一条；没有内容就返回空数组（确定键也据此禁用）。 */
  const buildSingle = (): InspirationItem[] => {
    if (mode === "file") return items;
    if (mode === "url") {
      const raw = urlInput.trim();
      if (!raw) return [];
      const url = toUrl(raw);
      return [{ id: createId(), kind: "url", name: url, url }];
    }
    const raw = textInput.trim();
    if (!raw) return [];
    return [{ id: createId(), kind: "text", name: textName(raw), text: raw }];
  };

  const singleReady =
    mode === "file"
      ? items.length === 1
      : mode === "url"
        ? Boolean(urlInput.trim())
        : Boolean(textInput.trim());

  const confirmDisabled =
    submitting ||
    (single
      ? !singleReady || (showCategory && categories.length === 0)
      : items.length === 0 || (showCategory && categories.length === 0));

  const confirm = async () => {
    const out = single ? buildSingle() : items;
    if (out.length === 0) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setSubmitting(true);
    setSubmitError("");
    try {
      await onConfirm(out, showCategory ? categories : undefined, usage, controller.signal);
      onClose();
    } catch (err) {
      // 被关窗 abort 掉了：不用报错（弹窗马上就没）
      if (controller.signal.aborted) return;
      // 真失败就留在弹窗里报错（父级不再自己关窗），让用户改完再试
      setSubmitError(err instanceof Error ? err.message : "没能添加");
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.backdrop} onClick={close}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <span className={styles.title}>{title}</span>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={close}
            title={submitting ? "取消翻译并关闭" : "关闭"}
            aria-label="关闭"
          >
            <CloseOutlined />
          </button>
        </div>

        <div className={styles.body}>
          {single ? (
            <div className={styles.modes}>
              {modes.map(({ value, label, Icon }) => (
                <button
                  key={value}
                  type="button"
                  className={`${styles.modeBtn} ${mode === value ? styles.modeBtnOn : ""}`}
                  onClick={() => switchMode(value)}
                >
                  <Icon />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className={styles.pickers}>
              {allowImage && (
                <button
                  type="button"
                  className={styles.pickBtn}
                  onClick={() => imageInputRef.current?.click()}
                >
                  <PictureOutlined />
                  <span>上传图片</span>
                </button>
              )}
              <button
                type="button"
                className={styles.pickBtn}
                onClick={() => fileInputRef.current?.click()}
              >
                <FileTextOutlined />
                <span>上传文件</span>
              </button>
            </div>
          )}

          {allowImage && (
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple={!single}
              hidden
              onChange={(e) => {
                if (e.target.files?.length) void addImages(e.target.files);
                e.target.value = "";
              }}
            />
          )}
          <input
            ref={fileInputRef}
            type="file"
            multiple={!single}
            hidden
            onChange={(e) => {
              if (e.target.files?.length) addFiles(e.target.files);
              e.target.value = "";
            }}
          />

          {single ? (
            mode === "file" ? (
              items.length > 0 ? (
                // 选好文件后就地显示这一条，替换掉选择按钮
                <div className={styles.filePicked}>
                  <FileTextOutlined className={styles.itemIcon} />
                  <span className={styles.itemName} title={items[0].name}>
                    {items[0].name}
                  </span>
                  {items[0].size != null && (
                    <span className={styles.itemMeta}>{formatSize(items[0].size)}</span>
                  )}
                  <button
                    type="button"
                    className={styles.removeBtn}
                    onClick={() => setItems([])}
                    title="移除"
                    aria-label="移除"
                  >
                    <CloseOutlined />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className={styles.pickBtn}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <FileTextOutlined />
                  <span>选择文件</span>
                </button>
              )
            ) : mode === "url" ? (
              <div className={styles.urlRow}>
                <input
                  className={styles.urlInput}
                  value={urlInput}
                  placeholder="粘贴链接，如 example.com/article"
                  onChange={(e) => setUrlInput(e.target.value)}
                />
                <button
                  type="button"
                  className={styles.clearBtn}
                  onClick={() => setUrlInput("")}
                  disabled={!urlInput}
                >
                  清空
                </button>
              </div>
            ) : (
              <div className={styles.textRow}>
                <textarea
                  className={styles.textArea}
                  value={textInput}
                  rows={6}
                  placeholder="直接写一段文字当灵感，如一个热梗、一句对白"
                  onChange={(e) => setTextInput(e.target.value)}
                />
                <button
                  type="button"
                  className={styles.clearBtn}
                  onClick={() => setTextInput("")}
                  disabled={!textInput}
                >
                  清空
                </button>
              </div>
            )
          ) : (
            <>
              {allowText && (
                <div className={styles.textRow}>
                  <textarea
                    className={styles.textArea}
                    value={textInput}
                    rows={2}
                    placeholder="直接写一段文字当灵感，如一个热梗、一句对白"
                    onChange={(e) => setTextInput(e.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.addUrlBtn}
                    onClick={addText}
                    disabled={!textInput.trim()}
                  >
                    添加
                  </button>
                </div>
              )}

              <div className={styles.urlRow}>
                <input
                  className={styles.urlInput}
                  value={urlInput}
                  placeholder="粘贴链接，如 example.com/article"
                  onChange={(e) => setUrlInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addUrl();
                    }
                  }}
                />
                <button
                  type="button"
                  className={styles.addUrlBtn}
                  onClick={addUrl}
                  disabled={!urlInput.trim()}
                >
                  添加
                </button>
              </div>
            </>
          )}

          {showCategory && (
            <>
              <div className={styles.categoryRow}>
                <span className={styles.categoryLabel}>类型（可多选）</span>
                <div className={styles.categoryChips}>
                  {INSPIRATION_CATEGORY_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`${styles.categoryChip} ${
                        categories.includes(option.value) ? styles.categoryChipOn : ""
                      }`}
                      onClick={() => toggleCategory(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <span className={styles.categoryHint}>
                  每个标签各生成一条灵感，尽量少选、越精准越好
                </span>
              </div>

              <div className={styles.categoryRow}>
                <span className={styles.categoryLabel}>使用策略</span>
                <div className={styles.categoryChips}>
                  {INSPIRATION_USAGE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`${styles.categoryChip} ${
                        usage === option.value ? styles.categoryChipOn : ""
                      }`}
                      onClick={() => {
                        setUsage(option.value);
                        setUsagePinned(true);
                      }}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <span className={styles.categoryHint}>
                  {usage === "must"
                    ? "每章强制用上"
                    : usage === "never"
                      ? "写章时不会出现"
                      : "写章时可被挑选（也可在对话框指定）"}
                </span>
              </div>
            </>
          )}

          {!single && (
            <div className={styles.listWrap}>
              {items.length === 0 ? (
                <div className={styles.emptyHint}>
                  {allowImage
                    ? "还没有素材，可上传图片、文件或添加链接"
                    : allowText
                      ? "还没有内容，先在一种形态下填入内容"
                      : "还没有素材，可上传文件或添加链接"}
                </div>
              ) : (
                <ul className={styles.list}>
                  {items.map((item) => (
                    <li key={item.id} className={styles.item}>
                      {item.kind === "image" ? (
                        item.preview ? (
                          // eslint-disable-next-line @next/next/no-img-element -- data URL 本地预览，无远程加载可优化
                          <img className={styles.thumb} src={item.preview} alt="" />
                        ) : (
                          <PictureOutlined className={styles.itemIcon} />
                        )
                      ) : item.kind === "text" ? (
                        <AlignLeftOutlined className={styles.itemIcon} />
                      ) : item.kind === "file" ? (
                        <FileTextOutlined className={styles.itemIcon} />
                      ) : (
                        <LinkOutlined className={styles.itemIcon} />
                      )}
                      <span className={styles.itemName} title={item.name}>
                        {item.name}
                      </span>
                      {item.kind === "file" && item.size != null && (
                        <span className={styles.itemMeta}>{formatSize(item.size)}</span>
                      )}
                      <button
                        type="button"
                        className={styles.removeBtn}
                        onClick={() => remove(item.id)}
                        title="移除"
                        aria-label="移除"
                      >
                        <CloseOutlined />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className={styles.footer}>
          {submitError ? <span className={styles.footerError}>{submitError}</span> : null}
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={close}
          >
            {submitting ? "取消翻译" : "取消"}
          </button>
          <button
            type="button"
            className={styles.confirmBtn}
            onClick={confirm}
            disabled={confirmDisabled}
          >
            {submitting ? (
              <>
                <LoadingOutlined className={styles.spinner} />
                <span>翻译中…</span>
              </>
            ) : (
              "确定"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}