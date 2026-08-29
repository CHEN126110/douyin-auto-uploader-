import { withCdpTarget, delay } from "../../mcp-server/cdp-client.js";

const cdpListUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const waitMs = Number(process.env.WAIT_AFTER_REPLACE_MS || 2500);
const needle = process.env.MAIN34_URL_NEEDLE || "651bca8eff0f7ba1dc4ad7c12d371514";

function buildProbeExpression(targetNeedle) {
  return `(() => {
    const findImg = () =>
      Array.from(document.querySelectorAll('img')).find((img) =>
        (img.getAttribute('src') || '').includes(${JSON.stringify(targetNeedle)})
      );

    const summarizeProps = (props, keys) => {
      const out = {};
      for (const key of keys) {
        if (!(key in props)) continue;
        const value = props[key];
        if (typeof value === 'function') {
          out[key] = '[fn]';
        } else if (Array.isArray(value)) {
          out[key] = value;
        } else if (value && typeof value === 'object') {
          try {
            out[key] = JSON.parse(JSON.stringify(value));
          } catch {
            out[key] = '[object]';
          }
        } else {
          out[key] = value;
        }
      }
      return out;
    };

    const collectToasts = () =>
      Array.from(document.querySelectorAll('.ecom-g-message-notice-content, .ecom-g-message-custom-content, .ecom-g-message-notice span'))
        .map((el) => (el.innerText || '').trim())
        .filter(Boolean)
        .slice(0, 20);

    const image = findImg();
    if (!image) {
      return { ok: false, error: 'target_image_not_found' };
    }

    const src = image.getAttribute('src') || '';
    const imgInfo = {
      src,
      naturalWidth: image.naturalWidth || null,
      naturalHeight: image.naturalHeight || null,
    };

    const fiberKey = Object.keys(image).find((key) => key.startsWith('__reactFiber$'));
    let fiber = fiberKey ? image[fiberKey] : null;
    let autoCut = null;
    let zComp = null;
    let xComp = null;

    for (let i = 0; i < 30 && fiber; i += 1, fiber = fiber.return) {
      const type = fiber.type;
      const name =
        typeof type === 'string'
          ? type
          : type?.displayName || type?.name || fiber.elementType?.displayName || fiber.elementType?.name || null;
      const props = fiber.memoizedProps;
      if (!props || typeof props !== 'object') continue;
      if (!autoCut && name === 'AutoCutWrapper' && typeof props.onReplace === 'function') {
        autoCut = {
          name,
          summary: summarizeProps(props, ['imgUrl', 'imgRatio', 'successMessage']),
        };
        autoCut.__onReplace = props.onReplace;
      }
      if (!zComp && name === 'Z') {
        zComp = {
          name,
          summary: summarizeProps(props, ['dataIndex', 'source', 'scene', 'maxCount', 'url', 'imgList']),
        };
      }
      if (!xComp && name === 'x') {
        xComp = {
          name,
          summary: summarizeProps(props, ['dataIndex', 'source', 'scene', 'maxCount', 'url', 'value']),
        };
      }
    }

    const beforeToasts = collectToasts();
    let replaceResult = { attempted: false };
    if (autoCut && autoCut.__onReplace) {
      let callbackCalled = false;
      try {
        autoCut.__onReplace(autoCut.summary.imgUrl, autoCut.summary.imgUrl, () => {
          callbackCalled = true;
        });
        replaceResult = {
          attempted: true,
          callbackCalled,
          imgUrl: autoCut.summary.imgUrl,
        };
      } catch (error) {
        replaceResult = {
          attempted: true,
          callbackCalled,
          error: error?.message || String(error),
        };
      }
    }

    delete autoCut?.__onReplace;

    return {
      ok: true,
      image: imgInfo,
      autoCut,
      zComp,
      xComp,
      replaceResult,
      beforeToasts,
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
        expression: buildProbeExpression(needle),
        awaitPromise: true,
        returnByValue: true,
      });

      await delay(waitMs);

      const after = await client.call("Runtime.evaluate", {
        expression: `(() => {
          const toasts = Array.from(document.querySelectorAll('.ecom-g-message-notice-content, .ecom-g-message-custom-content, .ecom-g-message-notice span'))
            .map((el) => (el.innerText || '').trim())
            .filter(Boolean)
            .slice(0, 20);
          const img = Array.from(document.querySelectorAll('img')).find((node) =>
            (node.getAttribute('src') || '').includes(${JSON.stringify(needle)})
          );
          return {
            toasts,
            imageStillThere: !!img,
            imageSrc: img ? img.getAttribute('src') : null,
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
          webSocketDebuggerUrl: target.webSocketDebuggerUrl,
        },
        waitMs,
        before: before.result?.value ?? null,
        after: after.result?.value ?? null,
        productRequests: requests,
      };
    } finally {
      detach();
    }
  }
);

console.log(JSON.stringify(result, null, 2));
