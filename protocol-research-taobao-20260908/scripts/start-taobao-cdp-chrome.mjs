/**
 * Launch (or reuse) a Chrome instance with a remote debugging port for read-only
 * research of the Taobao / Qianniu item publish flow.
 *
 * Mirrors mcp-server/scripts/start-fxg-cdp-chrome.mjs but uses a separate port
 * and a separate user-data-dir, because Taobao is a different account platform
 * than the Douyin (fxg) shop and the two logins must not share a profile.
 */
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..", "..");

const cdpPort = Number(process.env.TAOBAO_CDP_PORT || 9334);
const cdpListUrl = process.env.TAOBAO_CDP_LIST_URL || `http://127.0.0.1:${cdpPort}/json/list`;
const publishUrl = process.env.TAOBAO_PUBLISH_URL || "https://item.upload.taobao.com/sell/ai/category.htm";
const profileDir = path.resolve(
  process.env.TAOBAO_CDP_PROFILE_DIR || path.join(projectRoot, ".runtime", "chrome-taobao-cdp")
);
const targetHint = process.env.TARGET_HINT || "item.upload.taobao.com";
const waitMs = Number(process.env.WAIT_MS || 15000);

function getChromeCandidates() {
  const candidates = [];
  if (process.env.CHROME_PATH) candidates.push(process.env.CHROME_PATH);

  if (process.platform === "win32") {
    const env = process.env;
    const bases = [env.ProgramFiles, env["ProgramFiles(x86)"], env.LOCALAPPDATA].filter(Boolean);
    for (const base of bases) {
      candidates.push(path.join(base, "Google", "Chrome", "Application", "chrome.exe"));
    }
  } else if (process.platform === "darwin") {
    candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium");
  }
  return candidates;
}

function resolveChromePath() {
  for (const candidate of getChromeCandidates()) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("Chrome executable not found. Set CHROME_PATH to an installed Chrome executable.");
}

async function readTargets() {
  const response = await fetch(cdpListUrl);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : [];
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 500)}`);
  return Array.isArray(payload) ? payload : [];
}

async function waitForCdp() {
  const deadline = Date.now() + waitMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      return await readTargets();
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw lastError || new Error(`CDP endpoint did not become ready: ${cdpListUrl}`);
}

async function openPublishPageIfMissing(targets) {
  const pages = targets.filter((item) => item.type === "page");
  if (pages.some((item) => String(item.url || "").includes(targetHint))) return targets;
  const newUrl = `${cdpListUrl.replace(/\/json\/list$/, "/json/new")}?${encodeURIComponent(publishUrl)}`;
  await fetch(newUrl, { method: "PUT" });
  await new Promise((resolve) => setTimeout(resolve, 2000));
  return readTargets();
}

let launched = false;
let chromePath = null;

try {
  fs.mkdirSync(profileDir, { recursive: true });
  let targets = [];
  try {
    targets = await readTargets();
  } catch {
    chromePath = resolveChromePath();
    const args = [
      `--remote-debugging-port=${cdpPort}`,
      `--user-data-dir=${profileDir}`,
      "--new-window",
      publishUrl,
    ];
    spawn(chromePath, args, { detached: true, stdio: "ignore" }).unref();
    launched = true;
    targets = await waitForCdp();
  }

  targets = await openPublishPageIfMissing(targets);
  const pageTargets = targets.filter((item) => item.type === "page");
  const matchingTargets = pageTargets.filter((item) => String(item.url || "").includes(targetHint));

  console.log(
    JSON.stringify(
      {
        ok: true,
        launched,
        chromePath: chromePath || "existing-cdp-browser",
        profileDir,
        cdpListUrl,
        targetHint,
        targetCount: targets.length,
        pageTargetCount: pageTargets.length,
        matchingTargetCount: matchingTargets.length,
        matchingTargets: matchingTargets.map((i) => ({ id: i.id, title: i.title, url: i.url })),
        note: "Chrome started without AutomationControlled-disabling flags. Log in manually in this window.",
      },
      null,
      2
    )
  );
} catch (error) {
  console.error(
    JSON.stringify(
      {
        ok: false,
        launched,
        chromePath,
        profileDir,
        cdpListUrl,
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2
    )
  );
  process.exit(1);
}
