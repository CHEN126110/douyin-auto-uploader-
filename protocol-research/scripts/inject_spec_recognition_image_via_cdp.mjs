import path from "node:path";
import { withCdpTarget, delay } from "../../mcp-server/cdp-client.js";

const imagePath = process.env.UPLOAD_IMAGE_PATH;
if (!imagePath) {
  throw new Error("UPLOAD_IMAGE_PATH is required.");
}

const cdpListUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const openWaitMs = Number(process.env.WAIT_AFTER_OPEN_MS || 1200);
const uploadWaitMs = Number(process.env.WAIT_AFTER_UPLOAD_MS || 5000);
const clickStartRecognize = process.env.CLICK_START_RECOGNIZE === "1";
const recognizeWaitMs = Number(process.env.WAIT_AFTER_RECOGNIZE_MS || 8000);
const networkUrlFilters = ["/spec/", "/product/", "/material/", "/img/", "/api/"];

const uploadInputExpression = `(() => {
  const drawer = document.querySelector(".ecom-g-drawer-open");
  if (!drawer) return null;
  return (
    drawer.querySelector('input[type="file"][accept*="image"]') ||
    drawer.querySelector('input[type="file"]')
  );
})()`;

const result = await withCdpTarget(
  {
    cdpListUrl,
    targetUrlContains,
  },
  async (client, target) => {
    await client.call("DOM.enable");
    await client.call("Network.enable");
    await client.call("Runtime.enable");

    const resolvedPath = path.resolve(imagePath);
    const networkRecords = new Map();

    const stopListening = client.onEvent((method, params) => {
      if (method === "Network.requestWillBeSent") {
        const type = params.type || "";
        if (type !== "XHR" && type !== "Fetch") {
          return;
        }
        networkRecords.set(params.requestId, {
          requestId: params.requestId,
          type,
          method: params.request?.method || "",
          url: params.request?.url || "",
          requestHeaders: params.request?.headers || {},
          requestPostData: params.request?.postData || "",
          responseStatus: null,
          responseHeaders: null,
          responseMimeType: "",
          responseBody: "",
        });
        return;
      }

      if (method === "Network.responseReceived") {
        const current = networkRecords.get(params.requestId);
        if (!current) {
          return;
        }
        current.responseStatus = params.response?.status ?? null;
        current.responseHeaders = params.response?.headers || {};
        current.responseMimeType = params.response?.mimeType || "";
      }
    });

    try {
      const openDrawerResult = await client.call("Runtime.evaluate", {
        expression: `(() => {
          const existingDrawer = document.querySelector(".ecom-g-drawer-open");
          if (existingDrawer) {
            return {
              ok: true,
              alreadyOpen: true,
              drawerTitle: (existingDrawer.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 120),
            };
          }

          const trigger =
            document.querySelector(".styles_uploadImgBtn__KH1g7") ||
            Array.from(document.querySelectorAll("div, button, span, a")).find((node) => {
              const text = (node.textContent || "").replace(/\\s+/g, " ").trim();
              return text === "立即上传图片" && node.closest(".styles_createSpecByImgEntry__nwxej");
            });

          if (!trigger) {
            return { ok: false, error: "spec-upload-trigger-missing" };
          }

          trigger.scrollIntoView({ block: "center", inline: "center" });
          trigger.click();

          return {
            ok: true,
            alreadyOpen: false,
            triggerText: (trigger.textContent || "").replace(/\\s+/g, " ").trim(),
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });

      const drawerOpenState = openDrawerResult.result?.value ?? null;
      if (!drawerOpenState?.ok) {
        throw new Error(`Failed to open spec recognition drawer: ${drawerOpenState?.error || "unknown-error"}`);
      }

      await delay(openWaitMs);

      const inputHandle = await client.call("Runtime.evaluate", {
        expression: uploadInputExpression,
        awaitPromise: true,
      });
      const inputObjectId = inputHandle.result?.objectId;
      if (!inputObjectId) {
        throw new Error("No drawer-scoped image file input was found.");
      }

      await client.call("DOM.setFileInputFiles", {
        objectId: inputObjectId,
        files: [resolvedPath],
      });

      const dispatchResult = await client.call("Runtime.evaluate", {
        expression: `(() => {
          const input = ${uploadInputExpression};
          if (!input) {
            return { ok: false, error: "drawer-input-missing-after-upload" };
          }
          const beforeLength = input.files ? input.files.length : null;
          input.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
          input.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));

          const drawer = document.querySelector(".ecom-g-drawer-open");
          const confirmButton = drawer
            ? Array.from(drawer.querySelectorAll("button, div, span"))
                .find((node) => (node.textContent || "").replace(/\\s+/g, " ").trim() === "确认填写")
            : null;
          const startRecognizeNode = drawer
            ? Array.from(drawer.querySelectorAll("button, div, span"))
                .find((node) => (node.textContent || "").replace(/\\s+/g, " ").trim().includes("开始识别"))
            : null;

          return {
            ok: true,
            beforeLength,
            afterLength: input.files ? input.files.length : null,
            fileName: input.files && input.files[0] ? input.files[0].name : "",
            drawerText: drawer ? (drawer.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 400) : "",
            confirmText: confirmButton ? (confirmButton.textContent || "").replace(/\\s+/g, " ").trim() : "",
            startRecognizeText: startRecognizeNode ? (startRecognizeNode.textContent || "").replace(/\\s+/g, " ").trim() : "",
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });

      await delay(uploadWaitMs);

      let startRecognizeResult = null;
      if (clickStartRecognize) {
        const clickStart = await client.call("Runtime.evaluate", {
          expression: `(() => {
            const drawer = document.querySelector(".ecom-g-drawer-open");
            if (!drawer) {
              return { ok: false, error: "drawer-closed-before-recognize" };
            }

            const trigger = Array.from(drawer.querySelectorAll("button, div, span"))
              .find((node) => (node.textContent || "").replace(/\\s+/g, " ").trim() === "开始识别");

            if (!trigger) {
              return { ok: false, error: "recognize-trigger-missing" };
            }

            trigger.scrollIntoView({ block: "center", inline: "center" });
            trigger.click();

            return {
              ok: true,
              triggerText: (trigger.textContent || "").replace(/\\s+/g, " ").trim(),
            };
          })()`,
          awaitPromise: true,
          returnByValue: true,
        });

        startRecognizeResult = clickStart.result?.value ?? null;
        if (startRecognizeResult?.ok) {
          await delay(recognizeWaitMs);
        }
      }

      const finalState = await client.call("Runtime.evaluate", {
        expression: `(() => {
          const drawer = document.querySelector(".ecom-g-drawer-open");
          const input = ${uploadInputExpression};
          if (!drawer) {
            return { drawerOpen: false };
          }

          const shortTexts = Array.from(drawer.querySelectorAll("button, div, span"))
            .map((node) => (node.textContent || "").replace(/\\s+/g, " ").trim())
            .filter((text) => text && text.length <= 120)
            .slice(0, 80);

          const previewImages = drawer.querySelectorAll("img").length;
          const confirmButton = Array.from(drawer.querySelectorAll("button"))
            .find((button) => (button.textContent || "").replace(/\\s+/g, " ").trim().includes("确认填写"));

          return {
            drawerOpen: true,
            drawerText: (drawer.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 800),
            inputState: input
              ? {
                  accept: input.accept || "",
                  filesLength: input.files ? input.files.length : null,
                  fileName: input.files && input.files[0] ? input.files[0].name : "",
                }
              : null,
            previewImages,
            confirmDisabled: confirmButton ? !!confirmButton.disabled : null,
            shortTexts,
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });

      const matchedNetwork = Array.from(networkRecords.values()).filter((entry) =>
        networkUrlFilters.some((needle) => entry.url.includes(needle))
      );

      for (const entry of matchedNetwork.slice(0, 30)) {
        try {
          if (!entry.requestPostData) {
            const postData = await client.call("Network.getRequestPostData", {
              requestId: entry.requestId,
            });
            entry.requestPostData = postData.postData || "";
          }
        } catch {
          /* ignore request post data failures */
        }

        try {
          const responseBody = await client.call("Network.getResponseBody", {
            requestId: entry.requestId,
          });
          entry.responseBody = responseBody.body || "";
        } catch {
          /* ignore response body failures */
        }
      }

      return {
        ok: true,
        target: {
          title: target.title,
          url: target.url,
        },
        imagePath: resolvedPath,
        openWaitMs,
        uploadWaitMs,
        clickStartRecognize,
        recognizeWaitMs,
        drawerOpenState,
        inputObjectId,
        dispatchResult: dispatchResult.result?.value ?? null,
        startRecognizeResult,
        finalState: finalState.result?.value ?? null,
        networkHits: matchedNetwork.map((entry) => ({
          requestId: entry.requestId,
          type: entry.type,
          method: entry.method,
          url: entry.url,
          responseStatus: entry.responseStatus,
          responseMimeType: entry.responseMimeType,
          requestPostData: entry.requestPostData,
          responseBody: entry.responseBody,
        })),
      };
    } finally {
      stopListening();
    }
  }
);

console.log(JSON.stringify(result, null, 2));
