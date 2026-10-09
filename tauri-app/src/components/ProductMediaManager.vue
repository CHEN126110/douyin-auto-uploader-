<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from "vue";
import { Folder, Document, Refresh, Picture } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { api, productMediaImageUrl } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import type { ProductMediaEntry, ProductMediaReceipt } from "@/types";
import WhiteBgPanel from "@/components/WhiteBgPanel.vue";

const props = defineProps<{ modelValue: boolean; recordId: number | null; processingDisabled?: boolean }>();
const emit = defineEmits<{ (e: "update:modelValue", value: boolean): void }>();
const store = useProductStore();
const directory = ref("");
const page = ref(1);
const whiteBgPanelRef = ref<{ running: boolean; taskRecordId: number | null } | null>(null);
const selectionLocked = computed(() => props.processingDisabled || store.whiteBgSaving ||
  (whiteBgPanelRef.value?.running && whiteBgPanelRef.value?.taskRecordId === props.recordId));
const selected = ref<ProductMediaEntry | null>(null);
const failedImages = ref(new Set<string>());
const visible = computed({ get: () => props.modelValue, set: value => emit("update:modelValue", value) });
const listing = computed(() => store.mediaListing);
const whiteBgSelection = computed(() => listing.value?.white_bg_selection || { path: "", valid: true, error: "" });
const crumbs = computed(() => directory.value.split("/").filter(Boolean).map((name, index, parts) => ({
  name, path: parts.slice(0, index + 1).join("/"),
})));
const roles = { main: "主图", sku: "SKU", detail: "详情图" };

async function load(path = directory.value, nextPage = 1) {
  if (!props.recordId) return;
  directory.value = path;
  page.value = nextPage;
  selected.value = null;
  failedImages.value = new Set();
  await store.loadMediaDirectory(props.recordId, path, (nextPage - 1) * 100);
}

watch(() => [props.modelValue, props.recordId, store.currentShopSession?.active_profile], () => {
  if (props.modelValue && props.recordId) void load("");
  else {
    store.clearMediaListing();
    selected.value = null;
  }
}, { immediate: true });
onUnmounted(() => store.clearMediaListing());

async function handleProcessingDone(result: { recordId: number }) {
  // 关闭窗口或换商品后，旧任务只能保留自己的结果，不能刷新新商品的目录。
  if (!props.modelValue || props.recordId !== result.recordId) return;
  await load(directory.value, page.value);
}

async function setWhiteBg(path: string) {
  const recordId = props.recordId;
  if (!recordId || selectionLocked.value) return;
  const success = await store.setWhiteBgSelection(recordId, path);
  if (!props.modelValue || props.recordId !== recordId) return;
  if (success) ElMessage.success(path ? "已设为该商品的发布白底图" : "已恢复自动选择白底图");
  else ElMessage.error(store.lastActionError || "白底图选择保存失败");
}

function choose(entry: ProductMediaEntry) {
  if (entry.kind === "folder") void load(entry.path);
  else selected.value = entry;
}
function imageUrl(entry: ProductMediaEntry, preview = false) {
  return productMediaImageUrl(props.recordId!, entry.path, entry.modified_at, preview);
}
function receiptText(receipt: ProductMediaReceipt) {
  if (!receipt.content_matches) return "本地内容已更改";
  return receipt.status === "located" ? (receipt.folder_path.length ? "曾在图片空间定位" : "找到图片，目录未确认") : "上传完成，尚未定位";
}
function statusText(entry: ProductMediaEntry) {
  if (entry.kind === "folder") return "打开文件夹";
  if (entry.kind === "blocked") return "无法读取";
  if (entry.kind === "file") return "其它文件";
  if (!entry.receipts.length) return listing.value?.platform === "taobao" ? "无本账户上传记录" : "本地图片";
  if (entry.receipts.some(r => !r.content_matches)) return "本地内容已更改";
  return entry.receipts.every(r => r.status === "located" && r.folder_path.length) ? "有目录记录" : "目录待确认";
}
function fileSize(size: number) {
  return size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(2)} MB`;
}
function displayTime(value: string) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}
async function openLocal() {
  if (!props.recordId) return;
  try { await api.openProduct(props.recordId); }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : "本地文件夹打开失败"); }
}
</script>

<template>
  <!-- 关闭时保留处理组件，已启动的任务继续跟踪；再次打开可以查看结果。 -->
  <el-dialog v-model="visible" title="商品图片" width="min(1100px, 94vw)" top="5vh" class="product-media-dialog">
    <div class="media-heading">
      <div>
        <strong>{{ listing?.product_name || '本地商品目录' }}</strong>
        <p>打开文件夹查看其中的图片，点击图片查看预览和上传记录。</p>
      </div>
      <el-button :icon="Folder" @click="openLocal">打开本地文件夹</el-button>
    </div>
    <section class="media-processing" aria-label="图片处理">
      <div class="media-processing-copy">
        <h3>图片处理</h3>
        <p>{{ processingDisabled ? '商品正在发布，完成后可处理图片。' : '为当前商品生成白底图和 1:1 规格图，保留原图。' }}</p>
      </div>
      <WhiteBgPanel ref="whiteBgPanelRef" :record-id="recordId" :record-name="listing?.product_name" :active="visible"
        :disabled="processingDisabled" @done="handleProcessingDone" />
    </section>
    <div class="whitebg-selection" aria-live="polite">
      <div><strong>发布白底图</strong>
        <span>{{ whiteBgSelection.path ? `已指定：${whiteBgSelection.path}` : '自动选择，可点击图片指定要上传的白底图' }}</span>
      </div>
      <el-button v-if="whiteBgSelection.path" :disabled="selectionLocked"
        @click="setWhiteBg('')">恢复自动选择</el-button>
    </div>
    <el-alert v-if="whiteBgSelection.error" :title="whiteBgSelection.error" type="error" :closable="false" show-icon />
    <div class="media-toolbar">
      <nav aria-label="图片目录位置" class="breadcrumbs">
        <button type="button" :aria-current="!directory ? 'location' : undefined" @click="load('')">商品目录</button>
        <template v-for="crumb in crumbs" :key="crumb.path">
          <span aria-hidden="true">/</span>
          <button type="button" :aria-current="directory === crumb.path ? 'location' : undefined" @click="load(crumb.path)">{{ crumb.name }}</button>
        </template>
      </nav>
      <el-button :icon="Refresh" :loading="store.mediaLoading" @click="load(directory, page)">刷新</el-button>
    </div>
    <p v-if="listing?.platform === 'taobao'" class="media-note">
      淘宝位置来自当前账户最近一次填写记录。刷新只读取本地文件与记录；平台移动过的图片会在下次填写时重新核对。
    </p>
    <el-alert v-if="store.mediaError" :title="store.mediaError" type="error" :closable="false" show-icon />
    <div class="media-body" :aria-busy="store.mediaLoading">
      <section class="media-files" aria-label="当前文件夹内容">
        <p v-if="store.mediaLoading" class="empty-state" role="status">正在读取目录…</p>
        <p v-else-if="listing && !listing.entries.length" class="empty-state">这个文件夹是空的。</p>
        <div v-else class="media-grid">
          <button v-for="entry in listing?.entries || []" :key="entry.path" type="button" class="media-card"
            :class="{ selected: selected?.path === entry.path }" :aria-pressed="entry.kind !== 'folder' ? selected?.path === entry.path : undefined"
            :aria-label="`${entry.name}，${statusText(entry)}`" @click="choose(entry)">
            <div class="thumbnail">
              <img v-if="entry.kind === 'image' && !failedImages.has(entry.path)" :src="imageUrl(entry)" alt="" loading="lazy"
                @error="failedImages.add(entry.path)" />
              <template v-else-if="entry.kind === 'image'"><Picture /><span>预览不可用</span></template>
              <Folder v-else-if="entry.kind === 'folder'" class="folder-icon" />
              <Document v-else />
            </div>
            <span class="file-name" :title="entry.name">{{ entry.name }}</span>
            <span class="file-state">{{ whiteBgSelection.path === entry.path ? '已指定为发布白底图' : statusText(entry) }}</span>
          </button>
        </div>
      </section>
      <aside class="media-detail" aria-label="文件信息" aria-live="polite">
        <template v-if="selected">
          <el-image v-if="selected.kind === 'image'" :key="selected.path" class="detail-preview" :src="imageUrl(selected)"
            :preview-src-list="[imageUrl(selected, true)]" preview-teleported fit="contain" :alt="selected.name">
            <template #error><span class="preview-error">图片无法预览，请检查本地文件</span></template>
          </el-image>
          <h3>{{ selected.name }}</h3>
          <dl><dt>本地位置</dt><dd>{{ selected.path }}</dd><dt>大小</dt><dd>{{ fileSize(selected.size) }}</dd>
            <dt>修改时间</dt><dd>{{ displayTime(selected.modified_at) }}</dd></dl>
          <p v-if="selected.error" class="media-error">{{ selected.error }}</p>
          <el-button v-if="selected.kind === 'image'" type="primary" class="set-whitebg-button"
            :loading="store.whiteBgSaving" :disabled="selectionLocked || whiteBgSelection.path === selected.path"
            @click="setWhiteBg(selected.path)">
            {{ whiteBgSelection.path === selected.path ? '已设为发布白底图' : '设为发布白底图' }}
          </el-button>
          <template v-if="listing?.platform === 'taobao' && selected.kind === 'image'">
            <h4>淘宝图片空间对应记录</h4>
            <p v-if="!selected.receipts.length" class="media-note">本账户尚无这张图片的填写记录，不能据此判断平台里有没有图片。</p>
            <div v-for="receipt in selected.receipts" :key="receipt.name" class="receipt">
              <strong>{{ roles[receipt.role] }} · {{ receiptText(receipt) }}</strong>
              <dl><dt>上传名称</dt><dd>{{ receipt.name }}</dd><dt>最近确认目录</dt>
                <dd>{{ receipt.folder_path.length ? receipt.folder_path.join(' / ') : '目录尚未确认，不能按预期位置认定' }}</dd>
                <dt>记录时间</dt><dd>{{ displayTime(receipt.observed_at) }}</dd></dl>
            </div>
          </template>
        </template>
        <p v-else class="empty-state">选择一张图片查看详情</p>
      </aside>
    </div>
    <template #footer>
      <div class="media-footer"><span>{{ listing ? `当前目录共 ${listing.total} 项` : '目录读取结果以本地文件为准' }}</span>
        <el-pagination v-if="listing && listing.total > 100" layout="prev, pager, next" :total="listing.total" :page-size="100"
          :current-page="page" @current-change="load(directory, $event)" />
        <el-button @click="visible = false">关闭</el-button></div>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
:global(.product-media-dialog) { display: flex; flex-direction: column; max-height: 90vh; }
:global(.product-media-dialog > .el-dialog__header), :global(.product-media-dialog > .el-dialog__footer) { flex-shrink: 0; }
:global(.product-media-dialog > .el-dialog__body) { min-height: 0; overflow-y: auto; }
.media-heading, .media-toolbar, .media-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.media-heading { margin-bottom: 16px; strong { color: #283b4e; font-size: 17px; } p { margin: 6px 0 0; color: #626c7c; } }
.media-processing { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px 20px;
  margin-bottom: 16px; padding: 14px 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px;
  background: var(--el-color-primary-light-9);
}
.media-processing-copy { h3 { margin: 0; font-size: 14px; color: var(--el-text-color-primary); }
  p { margin: 5px 0 0; font-size: 13px; line-height: 1.6; color: var(--el-text-color-regular); }
}
.whitebg-selection { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
  margin: 0 0 14px; font-size: 13px; line-height: 1.6;
  div { min-width: 0; flex: 1; } strong { color: var(--el-text-color-primary); margin-right: 10px; }
  span { color: var(--el-text-color-regular); overflow-wrap: anywhere; }
}
.set-whitebg-button { margin-top: 14px; max-width: 100%; min-height: 40px; }
.media-toolbar { padding: 10px 0; border-block: 1px solid #e5e8f0; }
.breadcrumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0;
  button { border: 0; background: transparent; padding: 6px; color: #465bdd; font: inherit; cursor: pointer; overflow-wrap: anywhere; }
  button[aria-current] { font-weight: 600; color: #283b4e; }
}
.media-note { color: #626c7c; font-size: 13px; line-height: 1.65; }
.media-body { display: grid; grid-template-columns: minmax(0, 1fr) 290px; height: min(48vh, 460px); min-height: 280px; margin-top: 14px; gap: 20px; }
.media-files, .media-detail { overflow: auto; }
.media-files { padding: 3px; }
.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(125px, 1fr)); gap: 12px; align-content: start; }
.media-card { border: 1px solid #e5e8f0; border-radius: 10px; padding: 9px; background: #fff; text-align: left; font: inherit; cursor: pointer; min-width: 0;
  &:hover, &.selected { border-color: #6278ed; background: #f7f8ff; }
}
button:focus-visible { outline: 2px solid #465bdd; outline-offset: 2px; }
.thumbnail { aspect-ratio: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f6f7fa; border-radius: 6px; overflow: hidden;
  img { width: 100%; height: 100%; object-fit: contain; } svg { width: 40px; color: #8490a4; } span { font-size: 12px; margin-top: 8px; } .folder-icon { color: #647cef; width: 52px; }
}
.file-name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; color: #283b4e; line-height: 1.4; margin: 8px 0 4px; }
.file-state { display: block; font-size: 12px; color: #667080; }
.media-detail { border-left: 1px solid #e5e8f0; padding: 0 6px 0 18px; h3, h4 { overflow-wrap: anywhere; color: #283b4e; margin: 14px 0 10px; } h3 { font-size: 15px; } }
.detail-preview { width: 100%; height: 180px; border-radius: 8px; background: #f6f7fa; }
dl { margin: 0; font-size: 13px; dt { color: #747e8d; margin-top: 10px; } dd { color: #283b4e; margin: 4px 0 0; overflow-wrap: anywhere; line-height: 1.6; } }
.receipt { padding: 12px; margin-bottom: 10px; background: #f7f8ff; border-radius: 8px; strong { font-size: 13px; color: #465bdd; } }
.empty-state { color: #747e8d; padding: 36px 12px; text-align: center; }
.preview-error, .media-error { color: #b34747; font-size: 13px; padding: 12px; }
.media-footer { font-size: 13px; color: #667080; }
@media (max-width: 760px) { .media-body { grid-template-columns: 1fr; height: 60vh; overflow: auto; } .media-files, .media-detail { overflow: visible; } .media-detail { border-left: 0; border-top: 1px solid #e5e8f0; padding: 12px 0; } .media-heading { align-items: flex-start; } }
</style>
