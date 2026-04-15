import { Fragment, type ReactNode } from "react";

interface TranscriptMessageContentProps {
  text: string;
  onOpenPath: (path: string) => void | Promise<void>;
}

interface MessageTokenText {
  kind: "text";
  text: string;
}

interface MessageTokenLink {
  kind: "link";
  label: string;
  target: string;
  local: boolean;
}

type MessageToken = MessageTokenText | MessageTokenLink;

const APP_ROUTE_PREFIXES = [
  "/auth",
  "/codex",
  "/debug",
  "/desktop",
  "/fs",
  "/legacy",
  "/pair",
  "/power",
  "/settings",
  "/shares",
  "/shot",
  "/telegram",
  "/threads",
  "/tmux",
  "/wsl",
];

function normalizeLinkTarget(target: string): string {
  const trimmed = target.trim();
  if (trimmed.startsWith("<") && trimmed.endsWith(">") && trimmed.length > 2) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function isExternalUrl(target: string): boolean {
  return /^https?:\/\//i.test(target);
}

function isLikelyLocalPathTarget(target: string): boolean {
  const normalized = normalizeLinkTarget(target);
  if (!normalized) {
    return false;
  }
  if (isExternalUrl(normalized) || /^[a-z][a-z0-9+.-]*:/i.test(normalized) && !/^[a-z]:[\\/]/i.test(normalized)) {
    return false;
  }
  if (/^[a-z]:[\\/]/i.test(normalized) || normalized.startsWith("\\\\")) {
    return true;
  }
  if (!normalized.startsWith("/")) {
    return false;
  }
  return !APP_ROUTE_PREFIXES.some((prefix) => normalized === prefix || normalized.startsWith(`${prefix}/`));
}

function tokenizeMessage(text: string): MessageToken[] {
  const tokens: MessageToken[] = [];
  const matcher = /\[([^\]]+)\]\(([^)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = matcher.exec(text)) !== null) {
    const [raw, label, target] = match;
    const start = match.index;
    if (start > lastIndex) {
      tokens.push({ kind: "text", text: text.slice(lastIndex, start) });
    }
    const normalizedTarget = normalizeLinkTarget(target);
    if (!label.trim() || !normalizedTarget) {
      tokens.push({ kind: "text", text: raw });
    } else {
      tokens.push({
        kind: "link",
        label,
        target: normalizedTarget,
        local: isLikelyLocalPathTarget(normalizedTarget),
      });
    }
    lastIndex = start + raw.length;
  }

  if (lastIndex < text.length) {
    tokens.push({ kind: "text", text: text.slice(lastIndex) });
  }

  if (tokens.length === 0) {
    tokens.push({ kind: "text", text });
  }

  return tokens;
}

function renderTextWithBreaks(text: string, keyPrefix: string): ReactNode[] {
  const lines = text.split("\n");
  const nodes: ReactNode[] = [];
  lines.forEach((line, index) => {
    if (index > 0) {
      nodes.push(<br key={`${keyPrefix}-br-${index}`} />);
    }
    if (line.length > 0) {
      nodes.push(<Fragment key={`${keyPrefix}-text-${index}`}>{line}</Fragment>);
    }
  });
  return nodes;
}

export function TranscriptMessageContent({ text, onOpenPath }: TranscriptMessageContentProps) {
  const tokens = tokenizeMessage(text);
  const children: ReactNode[] = [];

  tokens.forEach((token, index) => {
    if (token.kind === "text") {
      children.push(...renderTextWithBreaks(token.text, `msg-${index}`));
      return;
    }
    if (token.local) {
      children.push(
        <a
          key={`msg-link-${index}`}
          className="event-link"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            void onOpenPath(token.target);
          }}
        >
          {token.label}
        </a>,
      );
      return;
    }
    children.push(
      <a
        key={`msg-link-${index}`}
        className="event-link"
        href={token.target}
        target="_blank"
        rel="noreferrer"
      >
        {token.label}
      </a>,
    );
  });

  return <p className="event-message">{children}</p>;
}
