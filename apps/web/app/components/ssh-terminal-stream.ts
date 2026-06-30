"use client";

import { apiWebSocketBase } from "@/app/lib/local-api-client";

export type TerminalStreamClientMessage =
  | { type: "input"; data: string }
  | { type: "resize"; cols: number; rows: number }
  | { type: "ping" };

export type TerminalReadyMessage = { type: "ready"; session_id: string };
export type TerminalOutputMessage = {
  type: "output";
  data: string;
  cursor: number;
  base_cursor: number;
  truncated: boolean;
};
export type TerminalStateMessage = {
  type: "state";
  connected: boolean;
  input_enabled: boolean;
  message: string;
};
export type TerminalErrorMessage = { type: "error"; message: string };
export type TerminalClosedMessage = { type: "closed"; message: string };

export type TerminalStreamServerMessage =
  | TerminalReadyMessage
  | TerminalOutputMessage
  | TerminalStateMessage
  | TerminalErrorMessage
  | TerminalClosedMessage
  | { type: "pong" };

type OpenTerminalStreamOptions = {
  sessionId: string;
  cursor: number;
  onOpen: () => void;
  onMessage: (message: TerminalStreamServerMessage) => void;
  onClose: (event: CloseEvent) => void;
  onError: () => void;
};

export type TerminalStreamController = {
  socket: WebSocket;
  send: (message: TerminalStreamClientMessage) => boolean;
  close: () => void;
};

export function openTerminalStream(options: OpenTerminalStreamOptions): TerminalStreamController {
  const url = new URL(
    `/api/v1/ssh/terminal/sessions/${options.sessionId}/stream`,
    `${apiWebSocketBase()}/`
  );
  url.searchParams.set("cursor", String(Math.max(0, Math.floor(options.cursor || 0))));

  const socket = new WebSocket(url.toString());
  socket.addEventListener("open", () => {
    options.onOpen();
  });
  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(String(event.data || "{}")) as TerminalStreamServerMessage;
      options.onMessage(payload);
    } catch {
      options.onMessage({ type: "error", message: "终端流返回了无法解析的消息" });
    }
  });
  socket.addEventListener("close", (event) => {
    options.onClose(event);
  });
  socket.addEventListener("error", () => {
    options.onError();
  });

  return {
    socket,
    send(message) {
      if (socket.readyState !== WebSocket.OPEN) {
        return false;
      }
      socket.send(JSON.stringify(message));
      return true;
    },
    close() {
      socket.close();
    },
  };
}
