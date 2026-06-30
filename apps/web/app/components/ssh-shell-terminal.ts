"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import {
  openTerminalStream,
  type TerminalStreamClientMessage,
  type TerminalStreamController,
  type TerminalStreamServerMessage,
} from "@/app/components/ssh-terminal-stream";

import {
  DEFAULT_TERMINAL_HEIGHT,
  TERMINAL_HEIGHT_KEY,
  type SSHStatus,
  type TerminalSnapshot,
  clampTerminalHeight,
  isSshChannelReady,
  normalizeFetchError,
  readStoredTerminalHeight,
} from "./ssh-shell-model";
import { useSshTerminalViewport } from "./ssh-shell-xterm";

export type UseSshTerminalResult = {
  terminalOpen: boolean;
  terminalHeight: number;
  terminalMessage: string;
  terminalGridLabel: string;
  openTerminal: (options?: { replaceExisting?: boolean }) => Promise<void>;
  closeTerminal: () => Promise<void>;
  beginTerminalResize: (startY: number) => void;
};

type UseSshTerminalOptions = {
  status: SSHStatus | null;
  refreshStatus: (options?: { silent?: boolean }) => Promise<SSHStatus | null>;
  surfaceRef: RefObject<HTMLDivElement | null>;
  viewportRef: RefObject<HTMLDivElement | null>;
};

const DEFAULT_TERMINAL_GRID = { cols: 120, rows: 28 };
const TERMINAL_RECONNECT_DELAY_MS = 1000;

export function useSshTerminal({
  status,
  refreshStatus,
  surfaceRef,
  viewportRef,
}: UseSshTerminalOptions): UseSshTerminalResult {
  const terminalStreamRef = useRef<TerminalStreamController | null>(null);
  const terminalReconnectTimerRef = useRef<number | null>(null);
  const creatingTerminalSessionRef = useRef(false);
  const terminalCursorRef = useRef(0);
  const terminalSessionIdRef = useRef<string | null>(null);
  const terminalOpenRef = useRef(false);
  const terminalSessionClosedRef = useRef(false);
  const terminalClosingRef = useRef(false);
  const terminalInputEnabledRef = useRef(false);
  const pendingTerminalResizeRef = useRef<{ cols: number; rows: number } | null>(null);
  const pendingTerminalInputRef = useRef("");
  const dragStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const terminalGridRef = useRef(DEFAULT_TERMINAL_GRID);

  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(DEFAULT_TERMINAL_HEIGHT);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [terminalMessage, setTerminalMessage] = useState("");
  const [terminalInputEnabled, setTerminalInputEnabled] = useState(false);
  const [terminalGridLabel, setTerminalGridLabel] = useState("120x28");

  const sendTerminalStreamMessage = useCallback(
    (message: TerminalStreamClientMessage, options?: { queueInput?: boolean; queueResize?: boolean }): boolean => {
      const controller = terminalStreamRef.current;
      if (!controller || controller.socket.readyState !== WebSocket.OPEN) {
        if (message.type === "input" && options?.queueInput) {
          pendingTerminalInputRef.current += message.data;
        }
        if (message.type === "resize" && options?.queueResize) {
          pendingTerminalResizeRef.current = { cols: message.cols, rows: message.rows };
        }
        return false;
      }
      const sent = controller.send(message);
      if (message.type === "input" && !sent && options?.queueInput) {
        pendingTerminalInputRef.current += message.data;
      }
      if (message.type === "resize" && options?.queueResize) {
        pendingTerminalResizeRef.current = sent ? null : { cols: message.cols, rows: message.rows };
      }
      return sent;
    },
    []
  );

  const queueTerminalInput = useCallback(
    (data: string) => {
      if (!data) {
        return;
      }
      if (!terminalSessionIdRef.current) {
        setTerminalMessage("终端会话尚未建立");
        return;
      }
      if (!terminalInputEnabledRef.current) {
        setTerminalMessage("SSH 已断开，终端会话已结束");
        return;
      }
      sendTerminalStreamMessage({ type: "input", data }, { queueInput: true });
    },
    [sendTerminalStreamMessage]
  );

  const flushPendingTerminalInput = useCallback(() => {
    const data = pendingTerminalInputRef.current;
    if (!data) {
      return;
    }
    pendingTerminalInputRef.current = "";
    sendTerminalStreamMessage({ type: "input", data }, { queueInput: true });
  }, [sendTerminalStreamMessage]);

  const flushPendingTerminalResize = useCallback(() => {
    const pending = pendingTerminalResizeRef.current;
    if (!pending) {
      return;
    }
    sendTerminalStreamMessage(
      { type: "resize", cols: pending.cols, rows: pending.rows },
      { queueResize: true }
    );
  }, [sendTerminalStreamMessage]);

  const terminalViewport = useSshTerminalViewport({
    surfaceRef,
    viewportRef,
    onInput: queueTerminalInput,
    onResize: ({ cols, rows }) => {
      terminalGridRef.current = { cols, rows };
      setTerminalGridLabel(`${cols}x${rows}`);
      if (terminalSessionIdRef.current && !terminalSessionClosedRef.current) {
        sendTerminalStreamMessage({ type: "resize", cols, rows }, { queueResize: true });
      }
    },
    onMessage: setTerminalMessage,
  });

  const clearTerminalReconnectTimer = useCallback(() => {
    if (terminalReconnectTimerRef.current !== null) {
      window.clearTimeout(terminalReconnectTimerRef.current);
      terminalReconnectTimerRef.current = null;
    }
  }, []);

  const closeTerminalStream = useCallback(() => {
    clearTerminalReconnectTimer();
    const controller = terminalStreamRef.current;
    terminalStreamRef.current = null;
    if (controller) {
      controller.close();
    }
  }, [clearTerminalReconnectTimer]);

  const resetTerminalState = useCallback(() => {
    closeTerminalStream();
    terminalCursorRef.current = 0;
    terminalSessionIdRef.current = null;
    terminalSessionClosedRef.current = false;
    pendingTerminalResizeRef.current = null;
    pendingTerminalInputRef.current = "";
    setTerminalSessionId(null);
    setTerminalMessage("");
    setTerminalInputEnabled(false);
    terminalViewport.replaceOutput("");
  }, [closeTerminalStream, terminalViewport]);

  const replaceTerminalSnapshot = useCallback(
    (item: TerminalSnapshot) => {
      terminalCursorRef.current = item.cursor || 0;
      terminalSessionIdRef.current = item.session_id;
      terminalSessionClosedRef.current = Boolean(item.closed);
      setTerminalSessionId(item.session_id);
      setTerminalMessage(item.message || "");
      setTerminalInputEnabled(Boolean(item.input_enabled));
      terminalViewport.replaceOutput(typeof item.output === "string" ? item.output : "");
    },
    [terminalViewport]
  );

  const connectTerminalStream = useCallback(
    (sessionId: string, cursor: number) => {
      if (!sessionId) {
        return;
      }
      clearTerminalReconnectTimer();
      terminalStreamRef.current?.close();
      terminalStreamRef.current = null;

      const controller = openTerminalStream({
        sessionId,
        cursor,
        onOpen: () => {
          setTerminalMessage("");
          terminalViewport.fit({ force: true });
          flushPendingTerminalResize();
          flushPendingTerminalInput();
        },
        onMessage: (message: TerminalStreamServerMessage) => {
          if (terminalStreamRef.current?.socket !== controller.socket) {
            return;
          }
          switch (message.type) {
            case "ready":
              setTerminalMessage("");
              return;
            case "output":
              if (!message.data) {
                return;
              }
              terminalCursorRef.current += message.data.length;
              terminalViewport.appendOutput(message.data);
              return;
            case "state":
              setTerminalInputEnabled(Boolean(message.input_enabled));
              setTerminalMessage(message.message || "");
              return;
            case "error":
              if (/unknown session|unknown terminal session/i.test(message.message || "")) {
                terminalSessionClosedRef.current = true;
                terminalSessionIdRef.current = null;
                setTerminalSessionId(null);
                setTerminalInputEnabled(false);
                setTerminalMessage("终端会话已失效，请重新打开终端");
                return;
              }
              setTerminalMessage(message.message || "终端流错误");
              return;
            case "closed":
              terminalSessionClosedRef.current = true;
              setTerminalInputEnabled(false);
              setTerminalMessage(message.message || "终端会话已结束");
              return;
            case "pong":
              return;
          }
        },
        onClose: async (event) => {
          if (terminalStreamRef.current?.socket !== controller.socket) {
            return;
          }
          terminalStreamRef.current = null;
          setTerminalInputEnabled(false);
          const nextStatus = await refreshStatus({ silent: true });
          if (
            event.code === 1000 ||
            terminalClosingRef.current ||
            terminalSessionClosedRef.current ||
            !isSshChannelReady(nextStatus) ||
            !terminalOpenRef.current ||
            terminalSessionIdRef.current !== sessionId
          ) {
            return;
          }
          setTerminalMessage("终端连接中断，正在重新连接...");
          clearTerminalReconnectTimer();
          terminalReconnectTimerRef.current = window.setTimeout(() => {
            terminalReconnectTimerRef.current = null;
            if (
              terminalClosingRef.current ||
              terminalSessionClosedRef.current ||
              !terminalOpenRef.current ||
              terminalSessionIdRef.current !== sessionId
            ) {
              return;
            }
            connectTerminalStream(sessionId, terminalCursorRef.current);
          }, TERMINAL_RECONNECT_DELAY_MS);
        },
        onError: () => {},
      });
      terminalStreamRef.current = controller;
    },
    [clearTerminalReconnectTimer, flushPendingTerminalInput, flushPendingTerminalResize, refreshStatus, terminalViewport]
  );

  useEffect(() => {
    terminalSessionIdRef.current = terminalSessionId;
  }, [terminalSessionId]);

  useEffect(() => {
    terminalOpenRef.current = terminalOpen;
  }, [terminalOpen]);

  useEffect(() => {
    terminalInputEnabledRef.current = terminalInputEnabled;
    terminalViewport.setInputEnabled(terminalInputEnabled);
  }, [terminalInputEnabled, terminalViewport]);

  useEffect(() => {
    setTerminalHeight(readStoredTerminalHeight());
  }, []);

  useEffect(() => {
    return () => {
      terminalClosingRef.current = true;
      closeTerminalStream();
    };
  }, [closeTerminalStream]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TERMINAL_HEIGHT_KEY, String(terminalHeight));
    }
  }, [terminalHeight]);

  useEffect(() => {
    if (isSshChannelReady(status) || !terminalOpen) {
      return;
    }
    clearTerminalReconnectTimer();
    setTerminalInputEnabled(false);
    setTerminalMessage("SSH 已断开，终端会话已结束");
  }, [clearTerminalReconnectTimer, status, terminalOpen]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const state = dragStateRef.current;
      if (!state) {
        return;
      }
      setTerminalHeight(clampTerminalHeight(state.startHeight - (event.clientY - state.startY)));
    };

    const stopDragging = () => {
      dragStateRef.current = null;
      document.body.classList.remove("ssh-terminal-resizing");
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("blur", stopDragging);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("blur", stopDragging);
      document.body.classList.remove("ssh-terminal-resizing");
    };
  }, []);

  useEffect(() => {
    if (!terminalOpen || !terminalInputEnabled) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      terminalViewport.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [terminalInputEnabled, terminalOpen, terminalSessionId, terminalViewport]);

  const closeTerminal = useCallback(async () => {
    const activeSessionId = terminalSessionId;
    terminalClosingRef.current = true;
    creatingTerminalSessionRef.current = false;
    setTerminalOpen(false);
    resetTerminalState();
    try {
      if (activeSessionId) {
        await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${activeSessionId}`);
      }
    } catch {
      // local UI state has already been cleared
    } finally {
      terminalClosingRef.current = false;
    }
  }, [resetTerminalState, terminalSessionId]);

  const openTerminal = useCallback(
    async (options?: { replaceExisting?: boolean }) => {
      setTerminalOpen(true);
      setTerminalMessage("");
      if (!isSshChannelReady(status)) {
        setTerminalMessage("请先连接远端服务器");
        setTerminalInputEnabled(false);
        return;
      }
      if (terminalSessionId && terminalInputEnabled && !options?.replaceExisting) {
        return;
      }
      if (creatingTerminalSessionRef.current) {
        return;
      }
      terminalClosingRef.current = false;
      creatingTerminalSessionRef.current = true;
      try {
        if (terminalSessionId) {
          await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${terminalSessionId}`).catch(() => undefined);
          resetTerminalState();
        }
        const { cols, rows } = terminalGridRef.current;
        const data = await requestLocalApiJson("POST", "/api/v1/ssh/terminal/sessions", { body: { cols, rows } });
        const snapshot = (data?.item || null) as TerminalSnapshot;
        replaceTerminalSnapshot(snapshot);
        terminalSessionClosedRef.current = false;
        connectTerminalStream(snapshot.session_id, snapshot.cursor || 0);
      } catch (error) {
        setTerminalInputEnabled(false);
        setTerminalMessage(normalizeFetchError(error) || "远程终端创建失败");
      } finally {
        creatingTerminalSessionRef.current = false;
      }
    },
    [connectTerminalStream, replaceTerminalSnapshot, resetTerminalState, status, terminalInputEnabled, terminalSessionId]
  );

  const beginTerminalResize = useCallback(
    (startY: number) => {
      dragStateRef.current = {
        startY,
        startHeight: terminalHeight,
      };
      document.body.classList.add("ssh-terminal-resizing");
    },
    [terminalHeight]
  );

  return {
    terminalOpen,
    terminalHeight,
    terminalMessage,
    terminalGridLabel,
    openTerminal,
    closeTerminal,
    beginTerminalResize,
  };
}
