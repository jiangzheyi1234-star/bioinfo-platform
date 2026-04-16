"use client";

export async function writeTerminalClipboard(text: string): Promise<void> {
  if (!text) {
    return;
  }
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  if (typeof document === "undefined") {
    throw new Error("系统剪贴板不可用");
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    const copied = document.execCommand("copy");
    if (!copied) {
      throw new Error("系统剪贴板不可用");
    }
  } finally {
    document.body.removeChild(textarea);
  }
}

export async function readTerminalClipboard(): Promise<string> {
  if (typeof navigator === "undefined" || !navigator.clipboard?.readText) {
    throw new Error("当前环境不支持读取系统剪贴板");
  }
  return navigator.clipboard.readText();
}
