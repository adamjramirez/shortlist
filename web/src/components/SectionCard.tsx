"use client";

import { useState, type ReactNode } from "react";

interface SectionCardProps {
  title: string;
  subtitle?: string;
  step?: number;
  defaultOpen?: boolean;
  collapsible?: boolean;
  children: ReactNode;
}

export default function SectionCard({
  title,
  subtitle,
  step,
  defaultOpen = true,
  collapsible = false,
  children,
}: SectionCardProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="pt-8 first:pt-0">
      <div
        className={`flex items-start gap-3 ${collapsible ? "cursor-pointer select-none" : ""} ${open ? "mb-4" : ""}`}
        onClick={collapsible ? () => setOpen(!open) : undefined}
      >
        {step !== undefined && (
          <span className="font-mono text-sm font-semibold text-gray-300 w-5 text-right shrink-0 pt-0.5">
            {step}
          </span>
        )}
        <div className="flex-1">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          {subtitle && (
            <p className="mt-0.5 text-sm text-gray-500">{subtitle}</p>
          )}
        </div>
        {collapsible && (
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform duration-200 mt-1 ${open ? "rotate-180" : ""}`}
            fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </div>
      {open && <div className={step !== undefined ? "pl-8" : ""}>{children}</div>}
    </section>
  );
}
