import { ElMessageBox } from "element-plus";

/** 确认框的「取消 / 关闭」不是出错：调用方据此区分用户取消和真正的异常。 */
export function isUserCancel(error: unknown) {
  if (error === "cancel" || error === "close") {
    return true;
  }

  if (typeof error === "object" && error !== null && "action" in error) {
    const action = (error as { action?: unknown }).action;
    return action === "cancel" || action === "close";
  }

  return false;
}

export async function confirmAction(
  message: string,
  title: string,
  options: Parameters<typeof ElMessageBox.confirm>[2] = {}
) {
  try {
    await ElMessageBox.confirm(message, title, options);
    return true;
  } catch (error) {
    if (isUserCancel(error)) {
      return false;
    }

    throw error;
  }
}
