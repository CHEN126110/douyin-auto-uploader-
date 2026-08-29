import path from "node:path";
import { withCdpTarget, delay } from "../../mcp-server/cdp-client.js";

const imagePath = process.env.UPLOAD_IMAGE_PATH;
if (!imagePath) {
  throw new Error("UPLOAD_IMAGE_PATH is required.");
}

const cdpListUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const waitMs = Number(process.env.WAIT_AFTER_UPLOAD_MS || 4000);

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

    await client.call("DOM.setFileInputFiles", {
      nodeId: fileInputNodeId,
      files: [path.resolve(imagePath)],
    });

    await delay(waitMs);

    const state = await client.call("Runtime.evaluate", {
      expression: `(() => {
        const nextButton = Array.from(document.querySelectorAll('button'))
          .find((button) => (button.textContent || '').includes('下一步'));
        const titleInput = document.querySelector('#pg-title-input');
        const allFileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
        const fileInputs = allFileInputs.map((input, index) => ({
          index,
          disabled: !!input.disabled,
          accept: input.accept || '',
          multiple: !!input.multiple,
          filesLength: input.files ? input.files.length : 0,
          fileName: input.files && input.files[0] ? input.files[0].name : '',
        }));
        const activeFileInput = fileInputs.find((input) => input.filesLength > 0) || null;
        const mainImageSection =
          document.querySelector('[attr-field-id="主图"]') ||
          Array.from(document.querySelectorAll('div')).find((node) => (node.textContent || '').includes('上传主图'));
        const sectionTexts = mainImageSection
          ? Array.from(mainImageSection.querySelectorAll('button, div, span'))
              .map((node) => (node.textContent || '').replace(/\\s+/g, ' ').trim())
              .filter((text) => {
                if (!text || text.length > 120) return false;
                return (
                  text.includes('上传主图') ||
                  text.includes('商品正面图') ||
                  text.includes('上传中') ||
                  text.includes('上传失败') ||
                  text.includes('重新上传') ||
                  text.includes('格式要求') ||
                  text.includes('下一步')
                );
              })
              .slice(0, 20)
          : [];
        return {
          href: location.href,
          titleValue: titleInput ? titleInput.value : '',
          nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
          nextButtonText: nextButton ? (nextButton.textContent || '').trim() : '',
          activeFileInput,
          fileInputs,
          sectionTexts,
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
      imagePath: path.resolve(imagePath),
      waitMs,
      pageState: state.result?.value ?? null,
    };
  }
);

console.log(JSON.stringify(result, null, 2));
