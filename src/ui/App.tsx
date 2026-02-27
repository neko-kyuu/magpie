import process from "node:process";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, useApp, useInput, Static, useStdout } from "ink";

import type { BackendClient } from "../ipc/backendClient";
import type { Item, Permission, PhaseName, ServerMessage } from "../ipc/protocol";
import {
  RESULTS_GROUPS,
  cycleGroup,
  exitHistoryBrowse,
  firstNonEmptyGroup,
  historyDown,
  historyUp,
  initialHistoryState,
  normalizeSelection,
  pushHistory,
  wrapSelection,
  type ResultsGroup,
} from "./focus";
import { buildViewport, clamp } from "./detail";

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
const DOT_SELECTED = "#00afd7";
const TEXT_COLOR = "#000000";
const TEXT_COLOR_DIM = "#9e9b9b";

function normalizeLogMessage(message: string) {
  if (message.startsWith("stderr: ")) return message.slice("stderr: ".length);
  if (message.startsWith("stderr:")) return message.slice("stderr:".length).trimStart();
  return message;
}

function padCenter(text: string, width: number) {
  if (width <= 0) return "";
  if (text.length >= width) return text;
  const remaining = width - text.length;
  const left = Math.floor(remaining / 2);
  const right = remaining - left;
  return `${" ".repeat(left)}${text}${" ".repeat(right)}`;
}

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
        text: normalizeLogMessage(msg.message),
        dotColor: isError ? DOT_ERROR : DOT_DEFAULT,
        textColor: msg.level === "error" ? "red" : msg.level === "warn" ? "yellow" : TEXT_COLOR_DIM,
      },
    ];
  }
  if (msg.type === "items") {
    if (msg.group !== "rag") {
      return [
        {
          key: `${Date.now()}-${Math.random()}`,
          text: `${msg.group} items: ${msg.items.length}`,
          dotColor: msg.items.length > 0 ? DOT_SUCCESS : DOT_DEFAULT,
          textColor: msg.items.length > 0 ? "green" : "gray",
        },
      ];
    }

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
      ...msg.items.map((item, idx) => {
        const display = item.group === 'rag' ? item.detail : `${item.snippet ? ` — ${item.snippet}` : ""}${item.url ? ` (${item.url})` : ""}`;
        return {
          key: `${Date.now()}-${Math.random()}-${idx}`,
          text: `[${item.id}] ${item.title}${display}`,
          dotColor: CLI_BACKGROUND,
          textColor: TEXT_COLOR_DIM,
        }
      }),
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
  const { stdout } = useStdout();
  const [phase, setPhase] = useState<PhaseName>("idle");
  const [permission] = useState<Permission>(initialPermission);
  const [input, setInput] = useState("");
  const [focus, setFocus] = useState<"input" | "list">("input");
  const [activeGroup, setActiveGroup] = useState<ResultsGroup>("web");
  const [selectedByGroup, setSelectedByGroup] = useState<Record<ResultsGroup, number>>({
    web: 0,
    reddit: 0,
    clips: 0,
  });
  const [history, setHistory] = useState(() => initialHistoryState());

  const [ragItems, setRagItems] = useState<Item[]>([]);
  const [webItems, setWebItems] = useState<Item[]>([]);
  const [redditItems, setRedditItems] = useState<Item[]>([]);
  const [clipsItems, setClipsItems] = useState<Item[]>([]);
  const [detailMode, setDetailMode] = useState(false);
  const [detailOffset, setDetailOffset] = useState(0);
  const [lines, setLines] = useState<UiLine[]>(() => [
    {
      key: "welcome",
      text: "Magpie CLI (M2) - type a query and press Enter",
      dotColor: DOT_DEFAULT,
      textColor: TEXT_COLOR,
    },
  ]);

  const ctrlCArmedRef = useRef(false);
  const lastStartRequestId = useRef<string | null>(null);
  const focusRef = useRef(focus);
  const webLenRef = useRef(0);
  const redditLenRef = useRef(0);

  useEffect(() => {
    focusRef.current = focus;
  }, [focus]);

  useEffect(() => {
    const buffered = backend.consumeBufferedMessages();
    const onMessage = (msg: ServerMessage) => {
      if (msg.type === "phase") setPhase(msg.name);

      if (msg.type === "items") {
        if (msg.group === "rag") {
          setRagItems(msg.items);
        } else if (msg.group === "web") {
          const prevLen = webLenRef.current;
          const nextLen = msg.items.length;
          webLenRef.current = nextLen;
          setWebItems(msg.items);
          setSelectedByGroup((prev) => ({ ...prev, web: normalizeSelection(prev.web, nextLen) }));

          if (focusRef.current === "input" && prevLen === 0 && nextLen > 0) {
            setFocus("list");
            setActiveGroup("web");
            setSelectedByGroup((prev) => ({ ...prev, web: 0 }));
          }
        } else if (msg.group === "reddit") {
          const prevLen = redditLenRef.current;
          const nextLen = msg.items.length;
          redditLenRef.current = nextLen;
          setRedditItems(msg.items);
          setSelectedByGroup((prev) => ({ ...prev, reddit: normalizeSelection(prev.reddit, nextLen) }));

          if (focusRef.current === "input" && prevLen === 0 && nextLen > 0) {
            setFocus("list");
            setActiveGroup("reddit");
            setSelectedByGroup((prev) => ({ ...prev, reddit: 0 }));
          }
        } else if (msg.group === "clips") {
          const nextLen = msg.items.length;
          setClipsItems(msg.items);
          setSelectedByGroup((prev) => ({ ...prev, clips: normalizeSelection(prev.clips, nextLen) }));
        }
      }

      const formatted = formatMessage(msg);
      setLines((prev) => [...prev, ...formatted].slice(-200));
      if (msg.type === "done" && msg.in_reply_to === lastStartRequestId.current) {
        setPhase("idle");
        ctrlCArmedRef.current = false;
      }
    };

    if (buffered.length > 0) {
      for (const msg of buffered) onMessage(msg);
    }
    backend.on("message", onMessage);
    return () => {
      backend.off("message", onMessage);
    };
  }, [backend]);

  const prompt = useMemo(() => {
    return phase === "idle" ? "> " : `${phase}> `;
  }, [phase]);
  const inputLines = input.split(/\r?\n/);

  const resultsByGroup: Record<ResultsGroup, Item[]> = useMemo(
    () => ({ web: webItems, reddit: redditItems, clips: clipsItems }),
    [webItems, redditItems, clipsItems]
  );
  const groupLengths: Record<ResultsGroup, number> = useMemo(
    () => ({
      web: resultsByGroup.web.length,
      reddit: resultsByGroup.reddit.length,
      clips: resultsByGroup.clips.length,
    }),
    [resultsByGroup]
  );
  const activeItems = resultsByGroup[activeGroup];
  const selectedIndex = normalizeSelection(selectedByGroup[activeGroup], activeItems.length);
  const groupTabs = useMemo(() => {
    return RESULTS_GROUPS.map((g) => ({ group: g, label: `${g.toUpperCase()} ${groupLengths[g]}` }));
  }, [groupLengths]);
  const tabWidth = useMemo(() => {
    const max = groupTabs.reduce((acc, t) => Math.max(acc, t.label.length), 0);
    return Math.max(8, max) + 2;
  }, [groupTabs]);

  const selectedItem = activeItems[selectedIndex] ?? null;
  const selectedDetailUrl = selectedItem?.url ? String(selectedItem.url) : "";
  const selectedDetailBody = selectedItem?.detail ?? selectedItem?.snippet ?? "no detail";
  const detailText = `${selectedDetailUrl || "(no url)"}\n${String(selectedDetailBody || "no detail")}`;

  const termColumns = typeof (stdout as any)?.columns === "number" ? Number((stdout as any).columns) : 80;
  const termRows = typeof (stdout as any)?.rows === "number" ? Number((stdout as any).rows) : 24;
  const detailWidth = Math.max(20, termColumns - 6);
  const detailMaxHeight = clamp(Math.floor(termRows / 3), 4, 12);
  const detailViewport = useMemo(() => {
    return buildViewport(detailText, detailWidth, detailMaxHeight, detailOffset);
  }, [detailText, detailWidth, detailMaxHeight, detailOffset]);

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

    if (key.tab) {
      if (focus === "input") {
        const nextGroup = groupLengths[activeGroup] > 0 ? activeGroup : firstNonEmptyGroup(groupLengths) ?? activeGroup;
        setActiveGroup(nextGroup);
        setFocus("list");
      } else {
        setFocus("input");
      }
      return;
    }

    if (key.escape) {
      setFocus("input");
      setHistory((prev) => exitHistoryBrowse(prev));
      return;
    }

    if (focus === "list") {
      if (chunk === "o") {
        setDetailMode((prev) => !prev);
        setDetailOffset(0);
        return;
      }

      if (detailMode) {
        const page = Math.max(1, detailViewport.height - 1);
        if (key.ctrl && (chunk === "u" || chunk === "\u0015")) {
          setDetailOffset((prev) => Math.max(0, prev - page));
          return;
        }
        if (key.ctrl && (chunk === "d" || chunk === "\u0004")) {
          setDetailOffset((prev) => Math.min(detailViewport.maxOffset, prev + page));
          return;
        }
        if (key.ctrl && key.upArrow) {
          setDetailOffset((prev) => Math.max(0, prev - 1));
          return;
        }
        if (key.ctrl && key.downArrow) {
          setDetailOffset((prev) => Math.min(detailViewport.maxOffset, prev + 1));
          return;
        }
      }

      if (key.leftArrow) {
        setActiveGroup((prev) => cycleGroup(prev, -1));
        return;
      }
      if (key.rightArrow) {
        setActiveGroup((prev) => cycleGroup(prev, +1));
        return;
      }
      if (key.upArrow) {
        const len = resultsByGroup[activeGroup].length;
        setSelectedByGroup((prev) => ({
          ...prev,
          [activeGroup]: wrapSelection(prev[activeGroup] ?? 0, -1, len),
        }));
        setDetailOffset(0);
        return;
      }
      if (key.downArrow) {
        const len = resultsByGroup[activeGroup].length;
        setSelectedByGroup((prev) => ({
          ...prev,
          [activeGroup]: wrapSelection(prev[activeGroup] ?? 0, +1, len),
        }));
        setDetailOffset(0);
        return;
      }
      return;
    }

    if (focus === "input") {
      if (key.upArrow) {
        setHistory((prev) => {
          const res = historyUp(prev, input);
          setInput(res.value);
          return res.state;
        });
        return;
      }
      if (key.downArrow) {
        setHistory((prev) => {
          const res = historyDown(prev, input);
          setInput(res.value);
          return res.state;
        });
        return;
      }
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
      setHistory((prev) => exitHistoryBrowse(prev));
      setInput((prev) => prev + normalized);
      return;
    }

    if (key.return) {
      if (focus !== "input") return;
      const trimmed = input.trim();
      if (!trimmed) return;

      setHistory((prev) => pushHistory(exitHistoryBrowse(prev), trimmed));
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
      setHistory((prev) => exitHistoryBrowse(prev));
      setInput((prev) => prev.slice(0, -1));
      return;
    }

    if (!key.ctrl && !key.meta && normalized) {
      setHistory((prev) => exitHistoryBrowse(prev));
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

      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Text color="gray">results </Text>
          <Text color={focus === "list" ? "cyan" : "gray"}>focus={focus}</Text>
        </Box>
        <Box flexDirection="row">
          {groupTabs.map((t, idx) => {
            const isActive = t.group === activeGroup;
            const bg = isActive ? DOT_SELECTED : "#e9e9e9";
            const fg = isActive ? "#000000" : "#333333";
            return (
              <Box key={t.group} marginRight={idx < groupTabs.length - 1 ? 1 : 0}>
                <Text backgroundColor={bg} color={fg}>
                  {padCenter(t.label, tabWidth)}
                </Text>
              </Box>
            );
          })}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {activeItems.length === 0 ? (
            <Text color="gray">({activeGroup} has no items)</Text>
          ) : (
            activeItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              const dotColor = focus === "list" && isSelected ? DOT_SELECTED : DOT_DEFAULT;
              const line = `${item.clipped ? "★ " : ""}[${item.id}] ${item.title}${item.snippet ? ` — ${item.snippet}` : ""}`;
              return (
                <Box key={item.id} flexDirection="column">
                  <Box flexDirection="row" alignItems="flex-start">
                    <Box width={2} flexShrink={0}>
                      <Text color={dotColor}>●</Text>
                    </Box>
                    <Text color={isSelected ? TEXT_COLOR : TEXT_COLOR_DIM}>{line}</Text>
                  </Box>

                  {detailMode && isSelected ? (
                    <Box flexDirection="column" marginLeft={2} marginTop={1}>
                      <Box>
                        <Text color="gray">url: </Text>
                        <Text color={TEXT_COLOR_DIM}>{selectedDetailUrl || "(no url)"}</Text>
                      </Box>
                      <Box flexDirection="column" marginTop={1}>
                        {detailViewport.lines.map((l, i) => (
                          <Text key={i} color={TEXT_COLOR_DIM}>
                            {l || " "}
                          </Text>
                        ))}
                      </Box>
                      {detailViewport.maxOffset > 0 ? (
                        <Box marginTop={1}>
                          <Text color="gray">
                            scroll {detailViewport.offset + 1}/{detailViewport.maxOffset + 1} (Ctrl+u/d page, Ctrl+↑/↓ line)
                          </Text>
                        </Box>
                      ) : null}
                    </Box>
                  ) : null}
                </Box>
              );
            })
          )}
        </Box>
      </Box>

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
