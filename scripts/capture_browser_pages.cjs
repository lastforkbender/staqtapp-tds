#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const pages = [
  ["dashboard", "Dashboard", "#overview"],
  ["engine-health", "Engine Health", "#architecture"],
  ["real-time-metrics", "Real-time Metrics", "#performance"],
  ["transition-timeline", "Transition Timeline", "#timeline"],
  ["event-ring-monitor", "Event Ring Monitor", "#diagnostics"],
  ["pressure-diagnostics", "Pressure Diagnostics", "#pressure"],
  ["csv-interpole", "CSV Interpole", "#csv-interpole"],
  ["snapshot-explorer", "Snapshot Explorer", "#snapshots"],
  ["lock-contention", "Lock Contention", "#locks"],
  ["workload-analytics", "Workload Analytics", "#behavior"],
  ["spiral-rank", "Spiral Rank", "#spiral-rank"],
  ["index-analytics", "Index Analytics", "#indexes"],
  ["storage-analytics", "Storage Analytics", "#storage"],
  ["comparative-views", "Comparative Views", "#comparison"],
  ["recovery-planner", "Recovery Planner", "#recovery"],
  ["policy-proposals", "Policy Proposals", "#recommendations"],
  ["alerts-events", "Alerts & Events", "#alerts"],
  ["security", "Security", "#security"],
  ["settings", "Settings", "#configuration"],
];

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
  const outputDir = path.resolve(
    process.argv[3] || path.join("docs", "screenshots", "browser_pages"),
  );
  fs.mkdirSync(outputDir, { recursive: true });

  const launchOptions = { headless: true };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      colorScheme: "dark",
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.addStyleTag({
      content: "html{scroll-behavior:auto!important}*,*::before,*::after{animation:none!important;transition:none!important}",
    });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(
      () => document.getElementById("csv-interpole-status")?.textContent.trim() === "Monitor Ready",
      null,
      { timeout: 30000 },
    );

    const navCount = await page.locator("a.nav-pill").count();
    if (navCount !== pages.length) {
      throw new Error(`expected ${pages.length} Browser pages, found ${navCount}`);
    }

    for (const [index, [slug, label, hash]] of pages.entries()) {
      const nav = page.locator(`a.nav-pill[href="${hash}"]`);
      if ((await nav.count()) !== 1) {
        throw new Error(`missing unique navigation control for ${label} (${hash})`);
      }
      await nav.click();
      await page.evaluate((selector) => {
        document.querySelector(selector).scrollIntoView({ block: "start", behavior: "instant" });
      }, hash);
      await page.waitForTimeout(100);

      const state = await page.evaluate((selector) => {
        const navLink = document.querySelector(`a.nav-pill[href="${selector}"]`);
        const target = document.querySelector(selector);
        const rect = target?.getBoundingClientRect();
        return {
          active: Boolean(navLink?.classList.contains("active")),
          visible: Boolean(rect && rect.bottom > 0 && rect.top < window.innerHeight),
          hash: window.location.hash,
        };
      }, hash);
      if (!state.active || !state.visible || state.hash !== hash) {
        throw new Error(`${label} did not become the active visible Browser page: ${JSON.stringify(state)}`);
      }

      const filename = `${String(index + 1).padStart(2, "0")}-${slug}-1280x800.png`;
      await page.screenshot({ path: path.join(outputDir, filename), fullPage: false });
      process.stdout.write(`${filename}\n`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
