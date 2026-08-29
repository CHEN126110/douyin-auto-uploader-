import path from "node:path";
import { withCdpTarget, delay } from "../../mcp-server/cdp-client.js";

const imagePath = process.env.UPLOAD_IMAGE_PATH;
if (!imagePath) {
  throw new Error("UPLOAD_IMAGE_PATH is required.");
}

const cdpListUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const waitMs = Number(process.env.WAIT_AFTER_UPLOAD_MS || 5000);

const result = await withCdpTarget(
  {
    cdpListUrl,
    targetUrlContains,
  },
  async (client, target) => {
    await client.call("DOM.enable");
    await client.call("Runtime.enable");

    const { root } = await client.call("DOM.getDocument", { depth: 2, pierce: true });
    const fileInputNodeId = (await client.call("DOM.querySelector", {
      nodeId: root.nodeId,
      selector: "input[type='file']",
    })).nodeId;

    if (!fileInputNodeId) {
      throw new Error("No file input was found on the current FXG page.");
    }

    const resolvedPath = path.resolve(imagePath);
    await client.call("DOM.setFileInputFiles", {
      nodeId: fileInputNodeId,
      files: [resolvedPath],
    });

    const dispatchResult = await client.call("Runtime.evaluate", {
      expression: `(() => {
        const input = document.querySelector("input[type='file']");
        if (!input) {
          return { ok: false, error: "no-input" };
        }
        const beforeLength = input.files ? input.files.length : null;
        input.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
        input.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
        const afterLength = input.files ? input.files.length : null;
        const nextButton = Array.from(document.querySelectorAll("button"))
          .find((button) => (button.textContent || "").includes("下一步"));
        return {
          ok: true,
          beforeLength,
          afterLength,
          fileName: input.files && input.files[0] ? input.files[0].name : "",
          nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
          nextButtonText: nextButton ? (nextButton.textContent || "").trim() : "",
        };
      })()`,
      awaitPromise: true,
      returnByValue: true,
    });

    await delay(waitMs);

    const state = await client.call("Runtime.evaluate", {
      expression: `(() => {
        const input = document.querySelector("input[type='file']");
        const nextButton = Array.from(document.querySelectorAll("button"))
          .find((button) => (button.textContent || "").includes("下一步"));
        return {
          filesLength: input && input.files ? input.files.length : null,
          fileName: input && input.files && input.files[0] ? input.files[0].name : "",
          nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
          nextButtonText: nextButton ? (nextButton.textContent || "").trim() : "",
        };
      })()`,
      awaitPromise: true,
      returnByValue: true,
    });

    return {
      ok: true,
      target: {
        title: target.title,
        url: target.url,
      },
      fileInputNodeId,
      imagePath: resolvedPath,
      waitMs,
      dispatchResult: dispatchResult.result?.value ?? null,
      pageState: state.result?.value ?? null,
    };
  }
);

console.log(JSON.stringify(result, null, 2));
