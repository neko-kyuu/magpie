import process from "node:process";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, useApp, useInput, Static } from "ink";

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
  dotColor: string;
  textColor?: string;
  userInput?: boolean;
};

const CLI_BACKGROUND = "#FAF7F6";
const DOT_DEFAULT = "#2F2F2F";
const DOT_SUCCESS = "#7B9A77";
const DOT_ERROR = "#BC7877";
const TEXT_COLOR = "#000000";
const TEXT_COLOR_DIM = "#9e9b9b";

function formatMessage(msg: ServerMessage): UiLine[] {
  if (msg.type === "phase") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `phase → ${msg.name}`,
        dotColor: DOT_DEFAULT,
        textColor: "cyan",
      },
    ];
  }
  if (msg.type === "log") {
    const isError = msg.level === "error" || msg.level === "warn";
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: msg.message,
        dotColor: isError ? DOT_ERROR : DOT_DEFAULT,
        textColor: msg.level === "error" ? "red" : msg.level === "warn" ? "yellow" : TEXT_COLOR_DIM,
      },
    ];
  }
  if (msg.type === "items") {
    if (msg.items.length === 0) {
      return [
        {
          key: `${Date.now()}-${Math.random()}`,
          text: `${msg.group} items: 0`,
          dotColor: DOT_DEFAULT,
          textColor: "gray",
        },
      ];
    }
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `${msg.group} items: ${msg.items.length}`,
        dotColor: DOT_SUCCESS,
        textColor: "green",
      },
      ...msg.items.map((item, idx) => ({
        key: `${Date.now()}-${Math.random()}-${idx}`,
        text: `${item.clipped ? "★ " : ""}[${item.id}] ${item.title} — ${item.detail}`,
        dotColor: CLI_BACKGROUND,
        textColor: TEXT_COLOR_DIM,
      })),
    ];
  }
  if (msg.type === "done") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: msg.canceled ? "done (canceled)" : msg.ok ? "done (ok)" : "done (failed)",
        dotColor: msg.ok && !msg.canceled ? DOT_SUCCESS : DOT_ERROR,
        textColor: msg.ok && !msg.canceled ? "green" : "yellow",
      },
    ];
  }
  if (msg.type === "error") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `error: ${msg.message}`,
        dotColor: DOT_ERROR,
        textColor: "red",
      },
    ];
  }
  if (msg.type === "hello_ack") {
    return [
      {
        key: `${Date.now()}-${Math.random()}`,
        text: `backend ready (protocol v${msg.protocol_version})`,
        dotColor: DOT_SUCCESS,
        textColor: "green",
      },
    ];
  }
  return [
    {
      key: `${Date.now()}-${Math.random()}`,
      text: JSON.stringify(msg),
      dotColor: DOT_DEFAULT,
      textColor: "gray",
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
      text: "Magpie CLI (M1) - type a query and press Enter",
      dotColor: DOT_DEFAULT,
      textColor: TEXT_COLOR,
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
  const inputLines = input.split(/\r?\n/);

  useInput((chunk, key) => {
    if (key.ctrl && (chunk === "c" || chunk === "\u0003")) {
      if (phase !== "idle" && !ctrlCArmedRef.current) {
        ctrlCArmedRef.current = true;
        backend.cancel();
        setLines((prev) => [
          ...prev,
          {
            key: `${Date.now()}-ctrlc`,
            text: "cancel requested (Ctrl+C again to exit)",
            dotColor: DOT_DEFAULT,
            textColor: "yellow",
          },
        ]);
        return;
      }
      backend.stop();
      exit();
      return;
    }

    const normalized =
      typeof chunk === "string"
        ? chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
        : "";

    const isPasteLike =
      !key.ctrl &&
      !key.meta &&
      normalized.length > 1;

    if (isPasteLike) {
      setInput((prev) => prev + normalized);
      return;
    }

    if (key.return) {
      const trimmed = input.trim();
      if (!trimmed) return;

      setLines((prev) => [
        ...prev,
        {
          key: `${Date.now()}-user`,
          text: `${prompt}${trimmed}`,
          dotColor: DOT_DEFAULT,
          textColor: TEXT_COLOR,
          userInput: true,
        },
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

    if (!key.ctrl && !key.meta && normalized) {
      setInput((prev) => prev + normalized);
    }
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Static items={lines}>
        {(l) => (
          <Box
            key={l.key}
            flexDirection="row"
            alignItems="flex-start"
            marginBottom={1}
          >
            <Box width={2} flexShrink={0}>
              <Text color={l.dotColor}>●</Text>
            </Box>

            <Text
              color={l.textColor}
              backgroundColor={l.userInput ? "#eeeeee" : undefined}
            >
              {l.text}
            </Text>
          </Box>
        )}
      </Static>

      <Box flexDirection="column">
        <Box>
          <Text color="gray">{prompt}</Text>
          <Text>{inputLines[0] ?? ""}</Text>
        </Box>

        {inputLines.slice(1).map((line, i) => (
          <Box key={i}>
            <Text color="gray">{" ".repeat(prompt.length)}</Text>
            <Text>{line}</Text>
          </Box>
        ))}
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
