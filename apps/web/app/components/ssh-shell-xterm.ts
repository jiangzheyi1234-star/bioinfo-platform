"use client";

import { useCallback, useLayoutEffect, useRef, type RefObject } from "react";

import { readTerminalClipboard, writeTerminalClipboard } from "@/app/components/ssh-terminal-clipboard";

import {
  LIGHT_TERMINAL_THEME,
  TERMINAL_FONT_SIZE,
  TERMINAL_LINE_HEIGHT,
  type TerminalHandle,
  type XTermLike,
  getTerminalGridSize,
  isTerminalHandleActive,
} from "./ssh-shell-model";

type UseSshTerminalViewportOptions = {
  surfaceRef: RefObject<HTMLDivElement | null>;
  viewportRef: RefObject<HTMLDivElement | null>;
  onInput: (data: string) => void;
  onResize: (size: { cols: number; rows: number }) => void;
  onMessage: (message: string) => void;
};

type TerminalViewportController = {
  appendOutput: (data: string) => void;
  replaceOutput: (data: string) => void;
  fit: (options?: { force?: boolean }) => void;
  focus: () => void;
  setInputEnabled: (enabled: boolean) => void;
};

function isCsiFinalByte(value: string): boolean {
  const code = value.charCodeAt(0);
  return code >= 0x40 && code <= 0x7e;
}

function findOscTerminator(value: string, start: number): { index: number; length: number } | null {
  for (let index = start; index < value.length; index += 1) {
    const char = value[index];
    if (char === "\u0007") {
      return { index, length: 1 };
    }
    if (char === "\u001b" && value[index + 1] === "\\") {
      return { index, length: 2 };
    }
  }
  return null;
}

function isTerminalAutoReplySequence(sequence: string): boolean {
  return (
    /^\u001b\](?:10|11|12|4;\d{1,3});.*(?:\u0007|\u001b\\)$/.test(sequence) ||
    /^\u001b\[(?:4|6);\d+;\d+t$/.test(sequence) ||
    /^\u001b\[[IO]$/.test(sequence) ||
    /^\u001b\[\d+;\d+R$/.test(sequence) ||
    /^\u001b\[\??[0-9;]*\$y$/.test(sequence)
  );
}

function createTerminalAutoReplyFilter() {
  let pending = "";

  return (data: string): string => {
    const input = pending + data;
    let output = "";
    pending = "";

    for (let index = 0; index < input.length;) {
      if (input[index] !== "\u001b") {
        output += input[index];
        index += 1;
        continue;
      }

      if (index + 1 >= input.length) {
        pending = input.slice(index);
        break;
      }

      const introducer = input[index + 1];
      if (introducer === "]") {
        const terminator = findOscTerminator(input, index + 2);
        if (!terminator) {
          pending = input.slice(index);
          break;
        }
        const end = terminator.index + terminator.length;
        const sequence = input.slice(index, end);
        if (!isTerminalAutoReplySequence(sequence)) {
          output += sequence;
        }
        index = end;
        continue;
      }

      if (introducer === "[") {
        let end = index + 2;
        while (end < input.length && !isCsiFinalByte(input[end])) {
          end += 1;
        }
        if (end >= input.length) {
          pending = input.slice(index);
          break;
        }
        const sequence = input.slice(index, end + 1);
        if (!isTerminalAutoReplySequence(sequence)) {
          output += sequence;
        }
        index = end + 1;
        continue;
      }

      output += input.slice(index, index + 2);
      index += 2;
    }

    return output;
  };
}

export function useSshTerminalViewport({
  surfaceRef,
  viewportRef,
  onInput,
  onResize,
  onMessage,
}: UseSshTerminalViewportOptions): TerminalViewportController {
  const terminalHandleRef = useRef<TerminalHandle | null>(null);
  const terminalBufferRef = useRef("");
  const terminalSelectionRef = useRef("");
  const lastGridRef = useRef<{ cols: number; rows: number } | null>(null);
  const terminalReadyRef = useRef(false);
  const pendingInputEnabledRef = useRef(true);
  const terminalAutoReplyFilterRef = useRef(createTerminalAutoReplyFilter());

  const fit = useCallback(
    (options?: { force?: boolean }) => {
      const handle = terminalHandleRef.current;
      if (!isTerminalHandleActive(handle) || !terminalReadyRef.current) {
        return;
      }
      try {
        handle.fitAddon.fit();
      } catch {
        return;
      }
      const next = getTerminalGridSize(handle.terminal);
      const previous = lastGridRef.current;
      if (!options?.force && previous && previous.cols === next.cols && previous.rows === next.rows) {
        return;
      }
      lastGridRef.current = next;
      onResize(next);
    },
    [onResize]
  );

  const appendOutput = useCallback((data: string) => {
    if (!data) {
      return;
    }
    terminalBufferRef.current += data;
    const handle = terminalHandleRef.current;
    if (isTerminalHandleActive(handle) && terminalReadyRef.current) {
      handle.terminal.write(data);
    }
  }, []);

  const replaceOutput = useCallback((data: string) => {
    terminalBufferRef.current = data;
    const handle = terminalHandleRef.current;
    if (!isTerminalHandleActive(handle) || !terminalReadyRef.current) {
      return;
    }
    handle.terminal.reset();
    if (data) {
      handle.terminal.write(data);
    }
  }, []);

  const focus = useCallback(() => {
    const handle = terminalHandleRef.current;
    if (!isTerminalHandleActive(handle) || !terminalReadyRef.current) {
      return;
    }
    handle.terminal.focus();
  }, []);

  const setInputEnabled = useCallback((enabled: boolean) => {
    pendingInputEnabledRef.current = enabled;
    const handle = terminalHandleRef.current;
    if (!isTerminalHandleActive(handle) || !terminalReadyRef.current) {
      return;
    }
    handle.terminal.options.disableStdin = !enabled;
  }, []);

  useLayoutEffect(() => {
    const node = viewportRef.current;
    if (!node) {
      return;
    }
    let disposed = false;
    let cleanup: (() => void) | null = null;

    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (disposed) {
        return;
      }

      const terminal = new Terminal({
        allowProposedApi: false,
        convertEol: false,
        cursorBlink: true,
        cursorStyle: "bar",
        cursorWidth: 2,
        fontFamily:
          '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: TERMINAL_FONT_SIZE,
        lineHeight: TERMINAL_LINE_HEIGHT,
        scrollback: 4000,
        theme: LIGHT_TERMINAL_THEME,
      }) as unknown as XTermLike;
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(node);

      const terminalHandle: TerminalHandle = { terminal, fitAddon, disposed: false };
      terminalHandleRef.current = terminalHandle;
      terminalReadyRef.current = false;
      lastGridRef.current = null;

      const syncSelection = () => {
        terminalSelectionRef.current = terminal.getSelection?.() || "";
      };
      const copySelection = async () => {
        const text = terminal.getSelection?.() || terminalSelectionRef.current;
        if (!text) {
          return false;
        }
        try {
          await writeTerminalClipboard(text);
          terminal.clearSelection?.();
          terminalSelectionRef.current = "";
          onMessage("");
        } catch (error) {
          onMessage(error instanceof Error ? error.message : "复制终端内容失败");
        }
        return true;
      };
      const pasteClipboard = async () => {
        try {
          const text = await readTerminalClipboard();
          if (!text) {
            return;
          }
          onInput(text);
          onMessage("");
        } catch (error) {
          onMessage(error instanceof Error ? error.message : "粘贴终端内容失败");
        }
      };

      terminalAutoReplyFilterRef.current = createTerminalAutoReplyFilter();
      const inputDisposable = terminal.onData((data) => {
        const filtered = terminalAutoReplyFilterRef.current(data);
        if (!filtered) {
          return;
        }
        onInput(filtered);
      });
      const selectionDisposable = terminal.onSelectionChange?.(syncSelection);
      terminal.attachCustomKeyEventHandler?.((event) => {
        const isModifier = event.ctrlKey || event.metaKey;
        const normalizedKey = event.key.toLowerCase();
        if (isModifier && normalizedKey === "c" && (terminal.hasSelection?.() || Boolean(terminalSelectionRef.current))) {
          event.preventDefault();
          void copySelection();
          return false;
        }
        if (isModifier && normalizedKey === "v") {
          event.preventDefault();
          void pasteClipboard();
          return false;
        }
        return true;
      });

      const focusTimer = window.setTimeout(() => terminal.focus(), 0);
      const resizeObserver = new ResizeObserver(() => {
        fit();
      });
      const handlePaste = (event: ClipboardEvent) => {
        const text = event.clipboardData?.getData("text") || "";
        if (!text) {
          return;
        }
        event.preventDefault();
        onInput(text);
      };

      resizeObserver.observe(surfaceRef.current || node);
      node.addEventListener("paste", handlePaste);
      const initializeTimer = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (disposed || !isTerminalHandleActive(terminalHandleRef.current)) {
            return;
          }
          terminalReadyRef.current = true;
          terminal.options.disableStdin = !pendingInputEnabledRef.current;
          fit({ force: true });
          if (terminalBufferRef.current) {
            terminal.write(terminalBufferRef.current);
          }
        });
      });

      cleanup = () => {
        window.clearTimeout(focusTimer);
        window.cancelAnimationFrame(initializeTimer);
        inputDisposable.dispose();
        selectionDisposable?.dispose();
        resizeObserver.disconnect();
        node.removeEventListener("paste", handlePaste);
        terminalHandle.disposed = true;
        if (terminalHandleRef.current === terminalHandle) {
          terminalHandleRef.current = null;
        }
        terminalReadyRef.current = false;
        lastGridRef.current = null;
        terminalSelectionRef.current = "";
        terminal.dispose();
      };
    })().catch((error: unknown) => {
      if (!disposed) {
        onMessage(error instanceof Error ? error.message : "终端初始化失败");
      }
    });

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [fit, onInput, onMessage, surfaceRef, viewportRef]);

  return {
    appendOutput,
    replaceOutput,
    fit,
    focus,
    setInputEnabled,
  };
}
