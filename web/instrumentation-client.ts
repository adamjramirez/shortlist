import posthog from "posthog-js";

posthog.init("phc_NPhbB68CFkI7dXVAacRN60tnc4ADmH5dWnOVZBEkwS1", {
  api_host: "/ingest",
  ui_host: "https://eu.posthog.com",
  capture_pageleave: true,
  defaults: "2026-01-30",
});
