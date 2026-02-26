import process from "node:process";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";

import type { BackendClient } from "../ipc/backendClient";
import type { Permission, PhaseName, ServerMessage } from "../ipc/protocol";

type Props = {
  backend: BackendClient;
  workspaceRoot: string;
  initialPermission: Permission;
};

type UiLine = {
  key: string;
  text: string;
  color?: string;
};

function formatMessage(msg: ServerMessage): UiLine[] {
  if (msg.type === "phase") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `phase → ${msg.name}`,
        color: "cyan",
      },
    ];
  }
  if (msg.type === "log") {
    const color =
      msg.level === "error" ? "red" : msg.level === "warn" ? "yellow" : "white";
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: msg.message,
        color,
      },
    ];
  }
  if (msg.type === "done") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: msg.canceled ? "done (canceled)" : msg.ok ? "done (ok)" : "done (failed)",
        color: msg.ok && !msg.canceled ? "green" : "yellow",
      },
    ];
  }
  if (msg.type === "error") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `error: ${msg.message}`,
        color: "red",
      },
    ];
  }
  if (msg.type === "hello_ack") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `backend ready (protocol v${msg.protocol_version})`,
        color: "green",
      },
    ];
  }
  return [
    {
      key: `${Date.now()}-${Math.random()}`,
      text: JSON.stringify(msg),
      color: "gray",
    },
  ];
}

export function App({ backend, workspaceRoot, initialPermission }: Props) {
  const { exit } = useApp();
  const [phase, setPhase] = useState<PhaseName>("idle");
  const [permission] = useState<Permission>(initialPermission);
  const [input, setInput] = useState("");
  const [lines, setLines] = useState<UiLine[]>(() => [
    {
      key: "welcome",
      text: "Magpie CLI (M0) — type a query and press Enter",
      color: "white",
    },
  ]);

  const ctrlCArmedRef = useRef(false);
  const lastStartRequestId = useRef<string | null>(null);

  useEffect(() => {
    const buffered = backend.consumeBufferedMessages();
    if (buffered.length > 0) {
      const formatted = buffered.flatMap(formatMessage);
      setLines((prev) => [...prev, ...formatted].slice(-200));
    }

    const onMessage = (msg: ServerMessage) => {
      if (msg.type === "phase") setPhase(msg.name);
      const formatted = formatMessage(msg);
      setLines((prev) => [...prev, ...formatted].slice(-200));
      if (msg.type === "done" && msg.in_reply_to === lastStartRequestId.current) {
        setPhase("idle");
        ctrlCArmedRef.current = false;
      }
    };
    backend.on("message", onMessage);
    return () => {
      backend.off("message", onMessage);
    };
  }, [backend]);

  const prompt = useMemo(() => {
    return phase === "idle" ? "> " : `${phase}> `;
  }, [phase]);

  useInput((chunk, key) => {
    if (key.ctrl && (chunk === "c" || chunk === "\u0003")) {
      if (phase !== "idle" && !ctrlCArmedRef.current) {
        ctrlCArmedRef.current = true;
        backend.cancel();
        setLines((prev) => [
          ...prev,
          { key: `${Date.now()}-ctrlc`, text: "cancel requested (Ctrl+C again to exit)", color: "yellow" },
        ]);
        return;
      }
      backend.stop();
      exit();
      return;
    }

    if (key.return) {
      const trimmed = input.trim();
      if (!trimmed) return;
      setLines((prev) => [
        ...prev,
        { key: `${Date.now()}-user`, text: `${prompt}${trimmed}`, color: "magenta" },
      ]);
      setInput("");
      ctrlCArmedRef.current = false;
      setPhase("rag");
      lastStartRequestId.current = backend.startQuery(trimmed);
      return;
    }

    if (key.backspace || key.delete) {
      setInput((prev) => prev.slice(0, -1));
      return;
    }

    if (key.escape) {
      setInput("");
      return;
    }

    if (!key.ctrl && !key.meta && chunk) {
      setInput((prev) => prev + chunk);
    }
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box flexDirection="column" marginBottom={1}>
        {lines.map((l) => (
          <Text key={l.key} color={l.color}>
            {l.text}
          </Text>
        ))}
      </Box>

      <Box>
        <Text color="gray">{prompt}</Text>
        <Text>{input}</Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">
          phase={phase} perm={permission.toUpperCase()} root={workspaceRoot} pid=
          {process.pid}
        </Text>
      </Box>
    </Box>
  );
}
