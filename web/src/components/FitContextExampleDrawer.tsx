"use client";

import { useEffect, useState, useRef } from "react";

interface Props {
  open: boolean;
  initialText: string;
  onClose: () => void;
  onApply: (text: string) => void;
}

export default function FitContextExampleDrawer({ open, initialText, onClose, onApply }: Props) {
  const [draft, setDraft] = useState(initialText);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset draft to initial whenever the drawer opens (edits don't carry across opens).
  useEffect(() => {
    if (open) {
      setDraft(initialText);
      const t = setTimeout(() => textareaRef.current?.focus(), 250);
      return () => clearTimeout(t);
    }
  }, [open, initialText]);

  // Esc to close.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Lock body scroll when open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  return (
    <>
      {/* Backdrop — gray-900/30 (no pure black per DESIGN.md §2) */}
      <div
        onClick={onClose}
        aria-hidden="true"
        className={`fixed inset-0 bg-gray-900/30 z-40 transition-opacity duration-200 ${
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        }`}
      />
      {/* Drawer — shadow-lg matches popover §9 elevation */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Example: what you're looking for"
        className={`fixed inset-y-0 right-0 z-50 w-full sm:w-[560px] bg-white shadow-lg flex flex-col transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-start justify-between gap-4 px-6 py-5 border-b border-gray-200/60">
          <div>
            {/* H3 scale (DESIGN.md §3) — drawer title, not page H2 */}
            <h2 className="text-lg font-semibold text-gray-900">Example: what you&apos;re looking for</h2>
            {/* Secondary role (gray-600) for subtitle */}
            <p className="mt-1 text-sm text-gray-600 leading-relaxed">
              A template to show what &ldquo;good&rdquo; looks like. Edit it to match your situation, then apply.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 -mr-2 -mt-1 p-2 text-gray-400 hover:text-gray-600 cursor-pointer rounded-md hover:bg-gray-100 transition-colors"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" />
            </svg>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* Matches the inputClass pattern from profile/page.tsx */}
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full h-full min-h-[400px] rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 leading-relaxed focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none"
            spellCheck={false}
          />
        </div>

        {/* Prominent helper strip — matches the amber "Most important step" callout on
            step 3 of the profile page, so the drawer feels continuous with that section. */}
        {draft === initialText ? (
          <div className="px-6 py-3 border-t border-amber-200 bg-amber-50">
            <p className="text-sm text-amber-900 leading-relaxed">
              <span className="font-semibold">Edit the template to make it your own.</span>{" "}
              The apply button will appear once you&apos;ve personalized it.
            </p>
          </div>
        ) : (
          <div className="px-6 py-3 border-t border-emerald-200 bg-emerald-50">
            <p className="text-sm text-emerald-900 leading-relaxed">
              <span className="font-semibold">Edited — ready to apply</span> to your profile.
            </p>
          </div>
        )}

        <footer className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200/60">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 cursor-pointer transition-colors"
          >
            Cancel
          </button>
          {draft !== initialText && (
            <button
              onClick={() => onApply(draft)}
              className="rounded-full bg-gray-900 px-6 py-2 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98] cursor-pointer"
            >
              Use this version for me
            </button>
          )}
        </footer>
      </aside>
    </>
  );
}
