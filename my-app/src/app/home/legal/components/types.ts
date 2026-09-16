export type MessageRole = "user" | "assistant";

export interface Attachment {
  id: string;
  name: string;
  size: number;
  type: string;
  file: File;
}

export interface FileInfo {
  fileId: string;
  filename: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  attachments?: Attachment[];
  fileInfo?: FileInfo;
  createdAt: number;
}

/** 一段正在进行的对话（可能尚未持久化到后端）。
 * key: 前端稳定的会话身份（用于消息写入/防串台守卫，新建后不变）。
 * threadId: 后端会话唯一 key；新建会话首条消息发出前为空串，待后端经 SSE
 * `session` 事件回传权威 id 后填入。
 */
export interface ChatSession {
  key: string;
  threadId: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

/** 侧栏会话列表项（来自后端 /sessions 的概要，不含消息历史）。 */
export interface SessionListItem {
  threadId: string;
  title: string;
}

/** 后端 user_session_history.messages 里单条消息的原始结构。 */
export interface RemoteMessage {
  role: MessageRole;
  content: string;
  messageId: string;
}

export interface SessionHistoryResponse {
  threadId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: RemoteMessage[];
}

export interface SessionListResponse {
  sessions: {
    threadId: string;
    title: string;
    createdAt: string;
    updatedAt: string;
  }[];
  total: number;
  page: number;
  page_size: number;
}
