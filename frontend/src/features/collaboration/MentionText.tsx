interface MentionTextProps {
  text: string;
  /** Lower-case handles that are highlighted when the text mentions them. */
  handles: ReadonlySet<string>;
}

/** Comment text with each @mention of a known handle highlighted. */
export function MentionText({ text, handles }: MentionTextProps) {
  return (
    <>
      {text
        .split(/((?<![\p{L}\p{N}_@])@[A-Za-z][A-Za-z0-9_]{0,31}(?![\p{L}\p{N}_]))/gu)
        .map((part, index) =>
          part.startsWith('@') && handles.has(part.slice(1).toLowerCase()) ? (
            <span key={index} className="font-semibold text-accent">
              {part}
            </span>
          ) : (
            part
          ),
        )}
    </>
  );
}
