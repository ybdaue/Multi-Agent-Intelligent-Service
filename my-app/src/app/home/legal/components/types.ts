export type MessageRole = "user" | "assistant";

export interface Attachment {
  id: string;
  name: string;
  size: number;
  type: string;
  file: File;
}

export interface FileInfo {
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

export interface ChatSession {
  id: string;
  threadId: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}
