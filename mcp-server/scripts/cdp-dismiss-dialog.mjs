// Recovery: dismiss any open JS dialog (beforeunload/alert) that is blocking the
// renderer, then confirm the page is responsive again. Browser-side Page domain
// commands are not blocked by the renderer dialog, so these calls return.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";
const accept = process.env.DIALOG_ACCEPT !== "0"; // default: accept (leave page)

function callT(client, method, params, ms = 5000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    const log = {};
    let dialogSeen = false;
    client.onEvent((method, params) => {
      if (method === "Page.javascriptDialogOpening") {
        dialogSeen = true;
        log.dialog = { type: params.type, message: String(params.message || "").slice(0, 80) };
      }
    });
    await callT(client, "Page.enable").catch((e) => { log.pageEnableErr = e.message; });
    await delay(300);
    // Try to dismiss whatever dialog is open.
    try {
      await callT(client, "Page.handleJavaScriptDialog", { accept });
      log.handled = true;
    } catch (e) {
      log.handleErr = e.message;
    }
    await delay(500);
    // Confirm renderer is responsive now.
    try {
      const r = await callT(client, "Runtime.evaluate", { expression: "({href: location.href, ready: document.readyState})", returnByValue: true }, 4000);
      log.alive = !r.exceptionDetails;
      log.page = r.result && r.result.value;
    } catch (e) {
      log.aliveErr = e.message;
    }
    log.dialogSeen = dialogSeen;
    return { ok: true, ...log };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
