"use client";

import { useState, KeyboardEvent, ClipboardEvent } from "react";

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  className?: string;
}

export default function TagInput({
  tags,
  onChange,
  placeholder = "Type and press Enter",
  className = "",
}: TagInputProps) {
  const [input, setInput] = useState("");

  const addTags = (raw: string) => {
    // Split on comma or newline, deduplicate
    const newTags = raw
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter((s) => s && !tags.includes(s));
    if (newTags.length > 0) {
      onChange([...tags, ...newTags]);
    }
    setInput("");
  };

  const handleKey = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === "Tab") {
      if (input.trim()) {
        e.preventDefault();
        addTags(input);
      }
    } else if (e.key === "Backspace" && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  const handlePaste = (e: ClipboardEvent) => {
    const pasted = e.clipboardData.getData("text");
    if (pasted.includes(",") || pasted.includes("\n")) {
      e.preventDefault();
      addTags(pasted);
    }
  };

  const remove = (idx: number) => {
    onChange(tags.filter((_, i) => i !== idx));
  };

  return (
    <div
      className={`flex flex-wrap items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-sm focus-within:border-emerald-500 focus-within:ring-1 focus-within:ring-emerald-500 ${className}`}
    >
      {tags.map((tag, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"
        >
          {tag}
          <button
            type="button"
            onClick={() => remove(i)}
            className="ml-0.5 rounded p-0.5 text-emerald-400 hover:bg-emerald-100 hover:text-emerald-600"
            aria-label={`Remove ${tag}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={() => input.trim() && addTags(input)}
        onPaste={handlePaste}
        placeholder={tags.length === 0 ? placeholder : ""}
        className="min-w-[140px] flex-1 border-none bg-transparent py-0.5 outline-none placeholder:text-gray-400"
      />
    </div>
  );
}
