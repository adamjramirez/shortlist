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
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <div
        className={`flex items-start gap-3 px-5 pt-5 ${collapsible ? "cursor-pointer select-none" : ""} ${open ? "pb-1" : "pb-5"}`}
        onClick={collapsible ? () => setOpen(!open) : undefined}
      >
        {step !== undefined && (
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
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
          <span className="mt-0.5 text-gray-400">{open ? "▾" : "▸"}</span>
        )}
      </div>
      {open && <div className="px-5 pb-5 pt-3">{children}</div>}
    </section>
  );
}
