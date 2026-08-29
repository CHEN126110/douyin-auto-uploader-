import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..", "..");

const cdpPort = Number(process.env.CDP_PORT || 9333);
const cdpListUrl = process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL || `http://127.0.0.1:${cdpPort}/json/list`;
const fxgUrl = process.env.FXG_URL || "https://fxg.jinritemai.com/ffa/g/create";
const profileDir = path.resolve(process.env.CDP_PROFILE_DIR || path.join(projectRoot, ".runtime", "chrome-fxg-cdp"));
const targetHint = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const waitMs = Number(process.env.WAIT_MS || 10000);

function getChromeCandidates() {
  const candidates = [];
  if (process.env.CHROME_PATH) candidates.push(process.env.CHROME_PATH);

  if (process.platform === "win32") {
    const env = process.env;
    const programFiles = [env.ProgramFiles, env["ProgramFiles(x86)"], env.LOCALAPPDATA].filter(Boolean);
    for (const base of programFiles) {
      candidates.push(path.join(base, "Google", "Chrome", "Application", "chrome.exe"));
    }
  } else if (process.platform === "darwin") {
    candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser");
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
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text.slice(0, 500)}`);
  }
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

async function openFxgPageIfMissing(targets) {
  const pages = targets.filter((item) => item.type === "page");
  const matching = pages.filter((item) => String(item.url || "").includes(targetHint));
  if (matching.length > 0) return targets;

  const newUrl = `${cdpListUrl.replace(/\/json\/list$/, "/json/new")}?${encodeURIComponent(fxgUrl)}`;
  await fetch(newUrl, { method: "PUT" });
  await new Promise((resolve) => setTimeout(resolve, 1500));
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
      fxgUrl,
    ];
    spawn(chromePath, args, {
      detached: true,
      stdio: "ignore",
    }).unref();
    launched = true;
    targets = await waitForCdp();
  }

  targets = await openFxgPageIfMissing(targets);
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
        matchingTargets: matchingTargets.map((item) => ({
          id: item.id,
          title: item.title,
          url: item.url,
        })),
        note: "Chrome was started without AutomationControlled-disabling flags.",
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
