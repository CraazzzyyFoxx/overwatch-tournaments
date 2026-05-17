export type RealtimeConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting";

export type RealtimeEventEnvelope<TData = Record<string, unknown>> = {
  event_id: number;
  event_type: string;
  schema_version: number;
  occurred_at: string;
  actor_user_id: number | null;
  data: TData;
};

export type SubscribeOp = {
  op: "subscribe";
  topic: string;
  after_event_id?: number;
};

export type UnsubscribeOp = {
  op: "unsubscribe";
  topic: string;
};

export type PingOp = {
  op: "ping";
};

export type ClientRealtimeFrame = SubscribeOp | UnsubscribeOp | PingOp;

export type SubscribedFrame = {
  op: "subscribed";
  topic: string;
  cursor: number;
};

export type ErrorFrame = {
  op: "error";
  topic?: string | null;
  code: string;
  message: string;
};

export type EventFrame<TData = Record<string, unknown>> = {
  op: "event";
  topic: string;
  event: RealtimeEventEnvelope<TData>;
};

export type PongFrame = {
  op: "pong";
};

export type ServerRealtimeFrame<TData = Record<string, unknown>> =
  | SubscribedFrame
  | ErrorFrame
  | EventFrame<TData>
  | PongFrame;
