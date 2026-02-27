export type Permission = "ro" | "rw";

export type ClientMessage =
  | HelloMessage
  | StartMessage
  | CancelMessage
  | SetPermissionMessage;

export type ServerMessage =
  | HelloAckMessage
  | PhaseMessage
  | LogMessage
  | ItemsMessage
  | DoneMessage
  | ErrorMessage;

export type PhaseName = "idle" | "rag" | "search" | "generate";

export interface BaseMessage {
  type: string;
  session_id: string;
}

export interface WithRequestId {
  request_id: string;
}

export interface WithInReplyTo {
  in_reply_to: string;
}

export interface HelloMessage extends BaseMessage, WithRequestId {
  type: "hello";
  protocol_version: 1;
  workspace_root: string;
  permission: Permission;
}

export interface StartMessage extends BaseMessage, WithRequestId {
  type: "start";
  query: string;
  workspace_root: string;
  permission: Permission;
}

export interface CancelMessage extends BaseMessage, WithRequestId {
  type: "cancel";
}

export interface SetPermissionMessage extends BaseMessage, WithRequestId {
  type: "set_permission";
  permission: Permission;
}

export interface HelloAckMessage extends BaseMessage, WithInReplyTo {
  type: "hello_ack";
  protocol_version: 1;
  capabilities: {
    mcp_graphrag: boolean;
    web_search: boolean;
    reddit_search: boolean;
    fixtures: boolean;
  };
}

export interface PhaseMessage extends BaseMessage {
  type: "phase";
  name: PhaseName;
  in_reply_to?: string;
}

export interface LogMessage extends BaseMessage {
  type: "log";
  level: "info" | "warn" | "error";
  message: string;
  in_reply_to?: string;
}

export type ItemGroup = "rag" | "web" | "reddit" | "clips";

export interface Item {
  id: string;
  group: ItemGroup;
  title: string;
  url: string;
  snippet: string;
  detail?: string;
  source: string;
  metadata?: Record<string, unknown>;
  clipped?: boolean;
}

export interface ItemsMessage extends BaseMessage {
  type: "items";
  group: ItemGroup;
  items: Item[];
  in_reply_to?: string;
}

export interface DoneMessage extends BaseMessage, WithInReplyTo {
  type: "done";
  ok: boolean;
  canceled: boolean;
}

export interface ErrorMessage extends BaseMessage {
  type: "error";
  message: string;
  recoverable: boolean;
  in_reply_to?: string;
}
