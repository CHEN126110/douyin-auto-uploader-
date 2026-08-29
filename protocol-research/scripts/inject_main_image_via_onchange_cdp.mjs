import fs from "node:fs";
import path from "node:path";
import { withCdpTarget, delay } from "../../mcp-server/cdp-client.js";

const imagePath = process.env.UPLOAD_IMAGE_PATH;
if (!imagePath) {
  throw new Error("UPLOAD_IMAGE_PATH is required.");
}

const cdpListUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const waitMs = Number(process.env.WAIT_AFTER_UPLOAD_MS || 5000);

const resolvedPath = path.resolve(imagePath);
const fileBuffer = fs.readFileSync(resolvedPath);
const base64 = fileBuffer.toString("base64");
const fileName = path.basename(resolvedPath);
const mimeType = fileName.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg";

function asciiPreview(value) {
  return String(value ?? "")
    .replace(/[^\x20-\x7E]/g, "?")
    .slice(0, 160);
}

function unwrapEvaluation(label, payload) {
  if (payload?.result?.value !== undefined) {
    return payload.result.value;
  }
  return {
    ok: false,
    error: `${label}_evaluation_failed`,
    exceptionText: payload?.exceptionDetails?.text || null,
    exceptionDescription: asciiPreview(payload?.exceptionDetails?.exception?.description || ""),
    resultType: payload?.result?.type || null,
    resultDescription: asciiPreview(payload?.result?.description || ""),
  };
}

function buildExpression() {
  return `(() => {
    const allInputs = Array.from(document.querySelectorAll('input[type=file]'));
    const uploadInput = allInputs.find((input) => {
      const parent = input.parentElement;
      return !!parent && parent.tagName === 'LABEL' && parent.className.includes('index-module_button__st1_R');
    });
    if (!uploadInput) {
      return { ok: false, error: 'upload_input_not_found' };
    }

    const start = uploadInput.parentElement || uploadInput;
    const fiberKey = Object.keys(start).find((key) => key.startsWith('__reactFiber$'));
    let fiber = fiberKey ? start[fiberKey] : null;
    const candidates = [];
    for (let i = 0; i < 25 && fiber; i += 1, fiber = fiber.return) {
      const type = fiber.type;
      const name =
        typeof type === 'string'
          ? type
          : type?.displayName || type?.name || fiber.elementType?.displayName || fiber.elementType?.name || null;
      const props = fiber.memoizedProps;
      if (!props || typeof props !== 'object') continue;
      if (typeof props.onChange !== 'function') continue;
      candidates.push({
        name: name || '[anonymous]',
        props,
      });
    }

    const priority = ['P', 'C', 'Z', 'x'];
    const uploadProps =
      candidates.find((item) => priority.includes(item.name)) &&
      candidates
        .slice()
        .sort((a, b) => {
          const ai = priority.indexOf(a.name);
          const bi = priority.indexOf(b.name);
          return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        })[0];

    if (!uploadProps) {
      return {
        ok: false,
        error: 'upload_component_not_found',
        inputIndex: allInputs.indexOf(uploadInput),
      };
    }

    return {
      ok: true,
      inputIndex: allInputs.indexOf(uploadInput),
      component: uploadProps.name,
      source: uploadProps.props.source || null,
      scene: uploadProps.props.scene || null,
      maxCount: uploadProps.props.maxCount || null,
      hasOnChange: typeof uploadProps.props.onChange === 'function',
      currentValueLength: Array.isArray(uploadProps.props.value)
        ? uploadProps.props.value.length
        : Array.isArray(uploadProps.props.imgList)
          ? uploadProps.props.imgList.length
          : null,
      candidates: candidates.map((item) => item.name),
    };
  })()`;
}

function buildAfterExpression() {
  return `(() => {
    const allInputs = Array.from(document.querySelectorAll('input[type=file]'));
    const uploadInput = allInputs.find((input) => {
      const parent = input.parentElement;
      return !!parent && parent.tagName === 'LABEL' && parent.className.includes('index-module_button__st1_R');
    });
    const nextButton = Array.from(document.querySelectorAll('button')).find((button) => (button.textContent || '').includes('下一步'));
    if (!uploadInput) {
      return {
        ok: false,
        error: 'upload_input_not_found',
        nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
      };
    }

    const start = uploadInput.parentElement || uploadInput;
    const fiberKey = Object.keys(start).find((key) => key.startsWith('__reactFiber$'));
    let fiber = fiberKey ? start[fiberKey] : null;
    const candidates = [];
    for (let i = 0; i < 25 && fiber; i += 1, fiber = fiber.return) {
      const type = fiber.type;
      const name =
        typeof type === 'string'
          ? type
          : type?.displayName || type?.name || fiber.elementType?.displayName || fiber.elementType?.name || null;
      const props = fiber.memoizedProps;
      if (!props || typeof props !== 'object') continue;
      if (typeof props.onChange !== 'function') continue;
      candidates.push({
        name: name || '[anonymous]',
        valueLength: Array.isArray(props.value)
          ? props.value.length
          : Array.isArray(props.imgList)
            ? props.imgList.length
            : null,
      });
    }

    const previewImages = Array.from(document.querySelectorAll('img'))
      .map((img) => img.getAttribute('src') || '')
      .filter(Boolean)
      .filter((src) => !src.startsWith('data:'))
      .slice(0, 12);

    return {
      ok: true,
      nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
      nextButtonPresent: !!nextButton,
      candidates,
      previewImageCount: previewImages.length,
      previewImages,
    };
  })()`;
}

function buildUploadExpression({ encoded, uploadFileName, uploadMimeType }) {
  return `(async () => {
    const allInputs = Array.from(document.querySelectorAll('input[type=file]'));
    const uploadInput = allInputs.find((input) => {
      const parent = input.parentElement;
      return !!parent && parent.tagName === 'LABEL' && parent.className.includes('index-module_button__st1_R');
    });
    if (!uploadInput) {
      return { ok: false, error: 'upload_input_not_found' };
    }

    const start = uploadInput.parentElement || uploadInput;
    const fiberKey = Object.keys(start).find((key) => key.startsWith('__reactFiber$'));
    let fiber = fiberKey ? start[fiberKey] : null;
    const candidates = [];
    for (let i = 0; i < 25 && fiber; i += 1, fiber = fiber.return) {
      const type = fiber.type;
      const name =
        typeof type === 'string'
          ? type
          : type?.displayName || type?.name || fiber.elementType?.displayName || fiber.elementType?.name || null;
      const props = fiber.memoizedProps;
      if (!props || typeof props !== 'object') continue;
      if (typeof props.onChange !== 'function') continue;
      candidates.push({ name: name || '[anonymous]', props });
    }

    const priority = ['P', 'C', 'Z', 'x'];
    const uploadProps =
      candidates.find((item) => priority.includes(item.name)) &&
      candidates
        .slice()
        .sort((a, b) => {
          const ai = priority.indexOf(a.name);
          const bi = priority.indexOf(b.name);
          return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        })[0];

    if (!uploadProps) {
      return {
        ok: false,
        error: 'upload_component_not_found',
        inputIndex: allInputs.indexOf(uploadInput),
        candidates: candidates.map((item) => item.name),
      };
    }

    const binary = atob(${JSON.stringify(encoded)});
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const file = new File([bytes], ${JSON.stringify(uploadFileName)}, { type: ${JSON.stringify(uploadMimeType)} });
    const progress = [];
    let returnType = 'undefined';
    try {
      const ret = uploadProps.props.onChange(
        [file],
        {
          setProgress: (value) => progress.push(value),
          files: [file],
        },
        undefined
      );
      returnType = ret && typeof ret.then === 'function' ? 'promise' : typeof ret;
      if (ret && typeof ret.then === 'function') {
        await ret;
      }
    } catch (error) {
      return {
        ok: false,
        error: error?.message || String(error),
        progress,
        component: uploadProps.name,
        inputIndex: allInputs.indexOf(uploadInput),
        candidates: candidates.map((item) => item.name),
      };
    }

    const nextButton = Array.from(document.querySelectorAll('button')).find((button) => (button.textContent || '').includes('下一步'));
    return {
      ok: true,
      inputIndex: allInputs.indexOf(uploadInput),
      component: uploadProps.name,
      source: uploadProps.props.source || null,
      scene: uploadProps.props.scene || null,
      progress,
      returnType,
      nextButtonDisabled: nextButton ? !!nextButton.disabled : null,
      nextButtonPresent: !!nextButton,
      candidates: candidates.map((item) => item.name),
    };
  })()`;
}

const result = await withCdpTarget(
  {
    cdpListUrl,
    targetUrlContains,
  },
  async (client, target) => {
    await client.call("Runtime.enable");
    await client.call("Network.enable");

    const requests = [];
    const detach = client.onEvent((method, params) => {
      if (method !== "Network.requestWillBeSent") return;
      const request = params.request || {};
      const url = String(request.url || "");
      if (!url.includes("/product/")) return;
      requests.push({
        method: request.method || "",
        url,
      });
    });

    try {
      const before = await client.call("Runtime.evaluate", {
        expression: buildExpression(),
        awaitPromise: true,
        returnByValue: true,
      });

      const upload = await client.call("Runtime.evaluate", {
        expression: buildUploadExpression({
          encoded: base64,
          uploadFileName: fileName,
          uploadMimeType: mimeType,
        }),
        awaitPromise: true,
        returnByValue: true,
      });

      await delay(waitMs);

      const after = await client.call("Runtime.evaluate", {
        expression: buildAfterExpression(),
        awaitPromise: true,
        returnByValue: true,
      });

      return {
        ok: true,
        target: {
          url: target.url,
          webSocketDebuggerUrl: target.webSocketDebuggerUrl,
        },
        imageName: asciiPreview(fileName),
        waitMs,
        before: unwrapEvaluation("before", before),
        upload: unwrapEvaluation("upload", upload),
        after: unwrapEvaluation("after", after),
        productRequests: requests.slice(0, 20),
      };
    } finally {
      detach();
    }
  }
);

const safeResult = {
  ...result,
  target: result.target
    ? {
        ...result.target,
        url: asciiPreview(result.target.url),
      }
    : null,
};

console.log(JSON.stringify(safeResult, null, 2));
