"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  SettingsFieldStatus,
  SettingsResponse,
} from "./types";
import { FIELD_LABELS } from "./types";
import styles from "./index.module.scss";

interface SetupSettingsPanelProps {
  novelId: string;
  /** 递增计数器：每次 SSE question/final 后父组件 +1，触发面板刷新 */
  revision: number;
  /** 是否允许编辑（waiting && !busy && !failed） */
  canEdit: boolean;
  /** 用户编辑了一项设定 */
  onEdit: (field: string, content: string) => void;
}

interface EditingField {
  field: string;
  /** 平铺字段（书名等）：整段文本 */
  content: string;
  /** 结构化字段：按子分类逐项编辑，key→值。存在时不看 content */
  subs?: { key: string; label: string; required: boolean; value: string }[];
}

interface ConfirmDeps {
  field: string;
  content: string;
  affected: string[];
}

export default function SetupSettingsPanel({
  novelId,
  revision,
  canEdit,
  onEdit,
}: SetupSettingsPanelProps) {
  const [fields, setFields] = useState<SettingsFieldStatus[]>([]);
  const [dependencies, setDependencies] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<EditingField | null>(null);
  const [confirmDeps, setConfirmDeps] = useState<ConfirmDeps | null>(null);

  /** 从后端拉取 settings */
  const fetchSettings = useCallback(async () => {
    if (!novelId) return;
    setLoading(true);
    try {
      const res = await fetch(
        `/api/novel/setup/settings?novelId=${encodeURIComponent(novelId)}`,
      );
      if (!res.ok) return;
      const data: SettingsResponse = await res.json();
      setFields(data.fields);
      setDependencies(data.dependencies);
    } catch {
      // 静默失败 —— 面板只是缓存视图，不阻塞用户
    } finally {
      setLoading(false);
    }
  }, [novelId]);

  // revision 变化时（SSE question/final 后）自动拉取
  useEffect(() => {
    fetchSettings();
  }, [fetchSettings, revision]);

  // 初始加载
  useEffect(() => {
    fetchSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId]);

  const handleStartEdit = (f: SettingsFieldStatus) => {
    if (!canEdit) return;
    if (f.sub_fields && f.sub_fields.length > 0) {
      setEditing({
        field: f.field,
        content: "",
        subs: f.sub_fields.map((sf) => ({
          key: sf.key,
          label: sf.label,
          required: sf.required,
          value: sf.value,
        })),
      });
    } else {
      setEditing({ field: f.field, content: f.content });
    }
  };

  /** 结构化字段：把子分类的值拼成 JSON 内容交给 agent */
  const buildSubContent = (subs: NonNullable<EditingField["subs"]>) => {
    const obj: Record<string, string> = {};
    subs.forEach((s) => {
      if (s.value.trim()) obj[s.key] = s.value.trim();
    });
    return JSON.stringify(obj);
  };

  const handleSaveEdit = () => {
    if (!editing) return;
    const content = editing.subs
      ? buildSubContent(editing.subs)
      : editing.content;
    if (!content.trim() || content === "{}") return;
    const deps = dependencies[editing.field] || [];
    if (deps.length > 0) {
      setConfirmDeps({ field: editing.field, content, affected: deps });
      setEditing(null);
    } else {
      onEdit(editing.field, content);
      setEditing(null);
    }
  };

  const handleConfirmEdit = () => {
    if (!confirmDeps) return;
    onEdit(confirmDeps.field, confirmDeps.content);
    setConfirmDeps(null);
  };

  // 依赖关系可视化：按 affected 分组
  const depEntries = Object.entries(dependencies).filter(
    ([, deps]) => deps.length > 0,
  );

  return (
    <aside className={styles.settingsPanel}>
      <h3 className={styles.panelTitle}>设定</h3>

      <div className={styles.fieldList}>
        {fields.length === 0 && !loading && (
          <p className={styles.emptyHint}>暂无设定</p>
        )}
        {fields.map((f) => (
          <div
            key={f.field}
            className={`${styles.fieldCard} ${f.collected ? styles.collected : styles.pending}`}
          >
            <div className={styles.fieldHeader}>
              <span
                className={`${styles.statusDot} ${
                  f.collected ? styles.dotDone : styles.dotEmpty
                }`}
              />
              <span className={styles.fieldLabel}>{f.label}</span>
              <button
                type="button"
                className={styles.editBtn}
                disabled={!canEdit}
                onClick={() => handleStartEdit(f)}
                title={canEdit ? "编辑此项设定" : "请等待当前操作完成"}
              >
                编辑
              </button>
            </div>
            {f.sub_fields && f.sub_fields.length > 0 ? (
              <div className={styles.subFieldList}>
                {f.sub_fields.map((sf) => (
                  <div
                    key={sf.key}
                    className={`${styles.subFieldItem} ${
                      sf.collected ? styles.subFieldDone : styles.subFieldEmpty
                    }`}
                  >
                    <span
                      className={`${styles.subFieldDot} ${
                        sf.collected ? styles.dotDone : styles.dotEmpty
                      }`}
                    />
                    <span className={styles.subFieldName}>
                      {sf.label}
                      {sf.required && (
                        <span className={styles.subFieldReq}>*</span>
                      )}
                    </span>
                    <span
                      className={styles.subFieldValue}
                      title={sf.collected ? sf.value : "尚未收集"}
                    >
                      {sf.collected ? sf.value : "尚未收集"}
                    </span>
                  </div>
                ))}
              </div>
            ) : f.collected ? (
              <p className={styles.fieldContent} title={f.content}>{f.content}</p>
            ) : (
              <p className={styles.fieldEmpty}>尚未收集</p>
            )}
          </div>
        ))}
      </div>

      {/* 依赖关系可视化 */}
      {depEntries.length > 0 && (
        <div className={styles.depSection}>
          <h4 className={styles.depTitle}>依赖关系</h4>
          {depEntries.map(([field, deps]) => (
            <p key={field} className={styles.depRow}>
              <span className={styles.depFrom}>{FIELD_LABELS[field] || field}</span>
              <span className={styles.depArrow}>→</span>
              <span className={styles.depTo}>
                {deps.map((d) => FIELD_LABELS[d] || d).join("、")}
              </span>
            </p>
          ))}
        </div>
      )}

      {/* 载入中指示 */}
      {loading && <p className={styles.loadingHint}>刷新中…</p>}

      {/* ── 编辑弹框 ── */}
      {editing && (
        <div className={styles.editOverlay}>
          <div className={styles.editDialog}>
            <h4 className={styles.editTitle}>
              编辑 {FIELD_LABELS[editing.field] || editing.field}
            </h4>
            {editing.subs ? (
              <div className={styles.editSubList}>
                {editing.subs.map((s, idx) => (
                  <label key={s.key} className={styles.editSubRow}>
                    <span className={styles.editSubLabel}>
                      {s.label}
                      {s.required && (
                        <span className={styles.subFieldReq}>*</span>
                      )}
                    </span>
                    <input
                      className={styles.editSubInput}
                      value={s.value}
                      placeholder="留空表示不定此项"
                      onChange={(e) => {
                        const next = editing.subs!.map((it, i) =>
                          i === idx ? { ...it, value: e.target.value } : it,
                        );
                        setEditing({ ...editing, subs: next });
                      }}
                    />
                  </label>
                ))}
              </div>
            ) : (
              <textarea
                className={styles.editTextarea}
                value={editing.content}
                rows={6}
                onChange={(e) =>
                  setEditing({ ...editing, content: e.target.value })
                }
                placeholder="输入新的设定内容…"
              />
            )}
            <div className={styles.editActions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                type="button"
                className={styles.saveBtn}
                disabled={
                  editing.subs
                    ? !editing.subs.some((s) => s.value.trim())
                    : !editing.content.trim()
                }
                onClick={handleSaveEdit}
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 依赖确认弹框 ── */}
      {confirmDeps && (
        <div className={styles.confirmOverlay}>
          <div className={styles.confirmDialog}>
            <p className={styles.confirmHeading}>
              修改 <strong>{FIELD_LABELS[confirmDeps.field]}</strong>
            </p>
            <p className={styles.confirmWarning}>
              将清空以下依赖项，需重新讨论：
            </p>
            <ul>
              {confirmDeps.affected.map((dep) => (
                <li key={dep}>{FIELD_LABELS[dep] || dep}</li>
              ))}
            </ul>
            <div className={styles.confirmActions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={() => setConfirmDeps(null)}
              >
                取消
              </button>
              <button
                type="button"
                className={styles.confirmBtn}
                onClick={handleConfirmEdit}
              >
                确认修改
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}