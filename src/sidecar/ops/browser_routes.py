# -*- coding: utf-8 -*-
"""运营闭环：依赖浏览器会话的接口（健康检查、经营指标同步、发布前安全闸）。

浏览器能力由应用入口通过 ``OpsBrowserPort`` 注入；本模块不导入浏览器自动化库，
也不反向导入 app.py。
"""
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from src.ops_engine import (
    AI_POLICY,
    DAILY_NET_PROFIT_TARGET,
    build_daily_plan,
    build_main_video_upload_stop_gate,
    build_publish_preflight_evidence,
    build_publish_preflight_safety,
    build_save_edit_human_gate,
    get_ops_ledger,
    merge_observed_shop_metrics,
)
from ..responses import api_error, api_ok
from .support import (
    ops_find_product_issue_action,
    ops_int,
    ops_record_context,
    ops_request_data,
)


@dataclass(frozen=True)
class OpsBrowserPort:
    """运营接口需要的浏览器能力。

    各字段对应 app.py 里已有的实现，由应用入口一次性注入。``page_state`` 是带 ``page``
    属性的共享状态对象，每次读取都取最新值，所以必须传同一个对象而不是 ``page`` 的快照。
    """

    get_current_tab: Callable[..., Any]
    snapshot_context: Callable[..., Any]
    attach_reusable_tab: Callable[..., Any]
    find_reusable_browser: Callable[..., Any]
    discover_browsers: Callable[..., Any]
    upload_file: Callable[..., Any]
    is_upload_busy: Callable[..., Any]
    page_state: Any


def main_video_field_snapshot(tab):
    script = """
    return (() => {
      const normalize = (value, limit = 500) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
      const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const field = document.querySelector('[attr-field-id="主图视频"]');
      const mediaNodes = field
        ? Array.from(field.querySelectorAll('video, img, canvas, [class*="video"], [class*="Video"]')).filter(isVisible)
        : [];
      const html = field ? String(field.outerHTML || '') : '';
      const hasSuccessCard = /styles_item-success|item-success|upload-item-success/.test(html);
      const hasVideoAssetSign = /video-play-sign|tos-cn-v|video_id|vid=/.test(html);
      const localUploadCount = field
        ? Array.from(field.querySelectorAll('label, button, div'))
            .filter(isVisible)
            .filter((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 40).includes('本地上传'))
            .length
        : 0;
      return {
        exists: !!field,
        text: field ? normalize(field.innerText || '', 1000) : '',
        media_count: mediaNodes.length,
        has_video_tag: field ? Array.from(field.querySelectorAll('video')).some(isVisible) : false,
        has_success_card: hasSuccessCard,
        has_video_asset_sign: hasVideoAssetSign,
        file_input_count: field ? field.querySelectorAll('input[type="file"]').length : 0,
        visible_local_upload_count: localUploadCount,
        upload_busy: /上传中/.test(document.body ? document.body.innerText || '' : '')
          || Array.from(document.querySelectorAll('.ecom-g-btn-loading-icon')).some(isVisible)
      };
    })();
    """
    try:
        result = tab.run_js(script) or {}
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        return {'error': str(exc)}


def default_candidate_video_path(repo_root, product_id):
    value = str(product_id or '').strip()
    if not value:
        return ''
    candidate = os.path.join(repo_root, 'output', 'ops-materials', value, 'candidate-main-video.mp4')
    return candidate


class OpsBrowserProbe:
    """运营接口对浏览器页面状态的读取：页面快照、可复用的已登录抖店标签页。"""

    def __init__(self, browser: OpsBrowserPort):
        self._browser = browser

    def current_browser_snapshot(self):
        try:
            tab, _meta = self._browser.get_current_tab(create_if_missing=False)
        except Exception as exc:
            return {
                'status': 'not_ready',
                'error': str(exc),
                'has_browser': bool(self._browser.page_state.page),
            }
        if not tab:
            return {
                'status': 'not_ready',
                'error': 'Browser is not running.',
                'has_browser': False,
            }
        try:
            snapshot = self._browser.snapshot_context(tab, limit=8, include_html=False)
            url = str(snapshot.get('url') or '')
            title = str(snapshot.get('title') or '')
            page_ready = bool(url and title and 'login' not in url.lower())
            return {
                'status': 'ready' if page_ready else 'needs_login_or_navigation',
                'has_browser': True,
                'url': url,
                'title': title,
                'snapshot': snapshot,
            }
        except Exception as exc:
            return {
                'status': 'not_ready',
                'error': str(exc),
                'has_browser': True,
            }

    def reusable_fxg_browser_snapshot(self):
        try:
            return self._browser.find_reusable_browser(verify=True)
        except Exception as exc:
            return {
                'status': 'error',
                'error': str(exc),
            }

    def publish_preflight_page_snapshot(self):
        try:
            tab, _meta = self._browser.get_current_tab(create_if_missing=False)
        except Exception as exc:
            tab = None
            first_error = str(exc)
        else:
            first_error = ''
        if not tab:
            tab = self._browser.attach_reusable_tab(lambda _progress, _message: None)
        if not tab:
            return {
                'status': 'not_ready',
                'error': first_error or 'Browser is not running.',
                'has_browser': bool(self._browser.page_state.page),
            }

        try:
            snapshot = self._browser.snapshot_context(tab, limit=20, include_html=False)
        except Exception:
            snapshot = {}

        script = """
    return (() => {
      const normalize = (value, limit = 500) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
      const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const nodes = Array.from(document.querySelectorAll('label, div, span, section, [attr-field-id]')).filter(isVisible);
      const brandTexts = nodes
        .map((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 180))
        .filter((text) => text.includes('品牌'))
        .slice(0, 12);
      const titleValues = Array.from(document.querySelectorAll('input, textarea'))
        .filter(isVisible)
        .map((el) => normalize(el.value || '', 120))
        .filter(Boolean)
        .slice(0, 20);
      const labelNodes = nodes.filter((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 120).includes('使用品牌名'));
      let titleUseBrandNameChecked = null;
      if (labelNodes.length) {
        titleUseBrandNameChecked = false;
        for (const node of labelNodes) {
          const label = node.closest('label') || node;
          const checkbox = label.querySelector('input[type="checkbox"]') || node.querySelector('input[type="checkbox"]');
          const ariaChecked = String(label.getAttribute('aria-checked') || node.getAttribute('aria-checked') || '').toLowerCase();
          const className = String(label.className || node.className || '').toLowerCase();
          if ((checkbox && checkbox.checked) || ariaChecked === 'true' || /checked/.test(className)) {
            titleUseBrandNameChecked = true;
            break;
          }
        }
      }
      return {
        url: location.href,
        title: document.title,
        body_text: normalize(document.body ? document.body.innerText || '' : '', 4000),
        brand_text: brandTexts.join(' | '),
        brand_texts: brandTexts,
        title_values: titleValues,
        title_use_brand_name_visible: labelNodes.length > 0,
        title_use_brand_name_checked: titleUseBrandNameChecked
      };
    })();
    """
        try:
            page_evidence = tab.run_js(script) or {}
        except Exception as exc:
            page_evidence = {
                'error': str(exc),
            }
        merged = {
            **(snapshot or {}),
            **(page_evidence if isinstance(page_evidence, dict) else {}),
            'has_browser': True,
        }
        merged['status'] = 'ready' if merged.get('url') and 'login' not in str(merged.get('url')).lower() else 'needs_login_or_navigation'
        return merged

    def current_or_reusable_fxg_tab(self):
        try:
            tab, _meta = self._browser.get_current_tab(create_if_missing=False)
        except Exception:
            tab = None
        if tab:
            return tab
        return self._browser.attach_reusable_tab(lambda _progress, _message: None)

    def wait_main_video_upload_settled(self, tab, before_snapshot=None, timeout=20.0, interval=0.2):
        before_media_count = 0
        if isinstance(before_snapshot, dict):
            try:
                before_media_count = int(before_snapshot.get('media_count') or 0)
            except Exception:
                before_media_count = 0

        started_at = time.time()
        seen_busy = False
        idle_checks = 0
        last_snapshot = {}
        while time.time() - started_at < timeout:
            last_snapshot = main_video_field_snapshot(tab)
            busy = bool(last_snapshot.get('upload_busy'))
            try:
                busy = busy or bool(self._browser.is_upload_busy(tab))
            except Exception:
                pass
            if busy:
                seen_busy = True
                idle_checks = 0
            else:
                idle_checks += 1
                try:
                    media_count = int(last_snapshot.get('media_count') or 0)
                except Exception:
                    media_count = 0
                if idle_checks >= 3 and (seen_busy or media_count > before_media_count or time.time() - started_at >= 1.2):
                    return {
                        'settled': True,
                        'seen_busy': seen_busy,
                        'duration_seconds': round(time.time() - started_at, 2),
                        'before_media_count': before_media_count,
                        'after_media_count': media_count,
                        'field_snapshot': last_snapshot,
                    }
            time.sleep(interval)

        return {
            'settled': False,
            'seen_busy': seen_busy,
            'duration_seconds': round(time.time() - started_at, 2),
            'before_media_count': before_media_count,
            'after_media_count': int(last_snapshot.get('media_count') or 0) if isinstance(last_snapshot, dict) else 0,
            'field_snapshot': last_snapshot,
        }


def register_ops_browser_routes(routes, *, record_model, browser, is_sidecar_mode,
                                get_sidecar_port, repo_root):
    """注册依赖浏览器会话的接口：健康检查、经营指标同步、发布前安全闸。"""
    probe = OpsBrowserProbe(browser)

    def resolve_publish_preflight_context(data):
        action_id = ops_int(data, 'action_id', ops_int(data, 'actionId', 0))
        record_id = ops_int(data, 'record_id', ops_int(data, 'recordId', 0))
        issue_action = ops_find_product_issue_action(action_id)
        record, _sku_list, record_context = ops_record_context(record_model, record_id)

        expected_product_id = str(
            data.get('expected_product_id')
            or data.get('expectedProductId')
            or data.get('product_id')
            or data.get('productId')
            or (issue_action or {}).get('product_id')
            or ''
        ).strip()
        expected_title = str(
            data.get('expected_title')
            or data.get('expectedTitle')
            or (record.title if record else '')
            or (issue_action or {}).get('title')
            or ''
        ).strip()
        candidate_video_path = str(
            data.get('candidate_video_path')
            or data.get('candidateVideoPath')
            or default_candidate_video_path(repo_root, expected_product_id)
            or ''
        ).strip()

        page_snapshot = data.get('page_snapshot') if isinstance(data.get('page_snapshot'), dict) else None
        if page_snapshot is None:
            page_snapshot = probe.publish_preflight_page_snapshot()

        preflight = build_publish_preflight_safety(
            page_snapshot=page_snapshot,
            expected_product_id=expected_product_id,
            expected_title=expected_title,
            candidate_video_path=candidate_video_path,
        )

        return {
            'action_id': action_id,
            'record_id': record_id,
            'record': record,
            'record_context': record_context,
            'issue_action': issue_action,
            'expected_product_id': expected_product_id,
            'expected_title': expected_title,
            'candidate_video_path': candidate_video_path,
            'page_snapshot': page_snapshot,
            'preflight': preflight,
        }

    @routes.get('/api/ops/health')
    def ops_health_check():
        try:
            browsers = browser.discover_browsers(verify=True)
        except Exception as exc:
            browsers = []
            browser_discovery_error = str(exc)
        else:
            browser_discovery_error = None

        return api_ok('运营闭环健康检查完成', data={
            'target_net_profit': DAILY_NET_PROFIT_TARGET,
            'backend': {
                'status': 'ok',
                'mode': 'sidecar' if is_sidecar_mode() else 'gui',
                'port': get_sidecar_port() if is_sidecar_mode() else 5000,
            },
            'mcp': {
                'server_name': 'douyin-publisher',
                'backend_url': f'http://127.0.0.1:{get_sidecar_port() if is_sidecar_mode() else 5000}',
                'status': 'available_when_mcp_server_is_running',
            },
            'cdp': {
                'discoverable_browser_count': len(browsers),
                'browsers': browsers,
                'error': browser_discovery_error,
            },
            'browser': probe.current_browser_snapshot(),
            'reusable_fxg_browser': probe.reusable_fxg_browser_snapshot(),
            'ai_policy': dict(AI_POLICY),
            'safety_gates': [
                '登录与验证码由用户完成',
                '付款与投放扣费不自动确认',
                '最终发布确认保留人工安全闸',
                '未读到真实后台数据时不生成虚假利润结论',
            ],
        })

    @routes.post('/api/ops/publish-preflight-safety')
    def ops_publish_preflight_safety():
        try:
            data = ops_request_data()
            context = resolve_publish_preflight_context(data)
            action_id = context['action_id']
            preflight = context['preflight']

            updated_action = None
            events = []
            if action_id:
                existing_evidence = (
                    (context['issue_action'] or {}).get('evidence')
                    if isinstance(context['issue_action'], dict)
                    else None
                )
                existing_upload_evidence = bool(
                    isinstance(existing_evidence, dict)
                    and (
                        existing_evidence.get('mutation_type') == 'main_video_upload_only'
                        or isinstance(existing_evidence.get('upload_result'), dict)
                    )
                )
                note = (
                    '上传前安全预检通过：仅允许在人工安全闸下上传素材并截停在保存/发布前'
                    if preflight.get('ready_for_upload_preflight')
                    else '上传前安全预检未通过：' + '；'.join(item.get('message', '') for item in preflight.get('blockers', []))
                )
                if existing_upload_evidence:
                    note = str((context['issue_action'] or {}).get('action_note') or note)
                updated_action = get_ops_ledger().update_product_issue_action(
                    action_id=action_id,
                    action_status='in_progress',
                    note=note,
                    evidence=build_publish_preflight_evidence(
                        preflight,
                        record=context['record_context'],
                        issue_action=context['issue_action'],
                        existing_evidence=existing_evidence,
                    ),
                )
                events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

            return api_ok('发布前安全预检完成', data={
                'preflight': preflight,
                'page_snapshot': context['page_snapshot'],
                'record': context['record_context'],
                'issue_action': context['issue_action'],
                'updated_action': updated_action,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'发布前安全预检失败: {str(exc)}')

    @routes.post('/api/ops/upload-main-video-preflight')
    def ops_upload_main_video_preflight():
        try:
            data = ops_request_data()
            context = resolve_publish_preflight_context(data)
            action_id = context['action_id']
            preflight = context['preflight']
            initial_gate = build_main_video_upload_stop_gate(preflight)

            updated_action = None
            events = []
            if not initial_gate.get('ready_to_attempt_upload'):
                if action_id:
                    updated_action = get_ops_ledger().update_product_issue_action(
                        action_id=action_id,
                        action_status='in_progress',
                        note='主图视频上传截停未执行：' + '；'.join(item.get('message', '') for item in initial_gate.get('blockers', [])),
                        evidence={
                            'preflight': preflight,
                            'upload_gate': initial_gate,
                            'record': context['record_context'],
                            'issue_action': context['issue_action'],
                            'shop_mutation': False,
                            'no_upload': True,
                            'no_save': True,
                            'no_publish': True,
                            'no_ad_or_payment': True,
                        },
                    )
                    events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)
                return api_error('主图视频上传截停安全闸未通过', data={
                    'preflight': preflight,
                    'upload_gate': initial_gate,
                    'page_snapshot': context['page_snapshot'],
                    'record': context['record_context'],
                    'issue_action': context['issue_action'],
                    'updated_action': updated_action,
                    'events': events,
                    'ai_policy': dict(AI_POLICY),
                })

            tab = probe.current_or_reusable_fxg_tab()
            if not tab:
                return api_error('主图视频上传截停失败：未找到可复用的已登录抖店浏览器', data={
                    'preflight': preflight,
                    'upload_gate': initial_gate,
                    'ai_policy': dict(AI_POLICY),
                })

            candidate_video_path = str(preflight.get('candidate_video_path') or '').strip()
            before_video_field = main_video_field_snapshot(tab)
            try:
                video_area = tab.ele('xpath://div[@attr-field-id="主图视频"]', timeout=3)
                if not video_area:
                    raise Exception('未找到主图视频区域')
                video_area.scroll.to_see()
                video_area.scroll.to_center()
            except Exception as exc:
                return api_error(f'主图视频上传截停失败：{str(exc)}', data={
                    'preflight': preflight,
                    'upload_gate': initial_gate,
                    'before_video_field': before_video_field,
                    'ai_policy': dict(AI_POLICY),
                })

            upload_error = ''
            try:
                browser.upload_file(
                    tab,
                    [candidate_video_path],
                    '主图视频',
                    target_field_id='主图视频',
                    wait_for_finish=False,
                )
            except Exception as exc:
                upload_error = str(exc)

            settle_result = probe.wait_main_video_upload_settled(tab, before_snapshot=before_video_field)
            upload_result = {
                'upload_triggered': not bool(upload_error),
                'upload_error': upload_error,
                'candidate_video_path': candidate_video_path,
                'before_video_field': before_video_field,
                'settle': settle_result,
                'upload_confirmed': bool(
                    not upload_error
                    and (
                        settle_result.get('seen_busy')
                        or int(settle_result.get('after_media_count') or 0) > int(settle_result.get('before_media_count') or 0)
                    )
                ),
                'save_publish_performed': False,
                'no_save': True,
                'no_publish': True,
                'no_ad_or_payment': True,
            }
            post_upload_snapshot = probe.publish_preflight_page_snapshot()
            upload_gate = build_main_video_upload_stop_gate(
                preflight,
                upload_attempted=True,
                upload_result=upload_result,
                post_upload_snapshot=post_upload_snapshot,
            )

            if action_id:
                note = (
                    '主图视频已触发上传并在保存/发布前截停；未保存、未发布、未投放'
                    if upload_result.get('upload_triggered')
                    else f'主图视频上传触发失败并已截停：{upload_error}'
                )
                updated_action = get_ops_ledger().update_product_issue_action(
                    action_id=action_id,
                    action_status='in_progress',
                    note=note,
                    evidence={
                        'preflight': preflight,
                        'upload_gate': upload_gate,
                        'upload_result': upload_result,
                        'post_upload_snapshot': post_upload_snapshot,
                        'record': context['record_context'],
                        'issue_action': context['issue_action'],
                        'shop_mutation': bool(upload_result.get('upload_triggered')),
                        'mutation_type': 'main_video_upload_only' if upload_result.get('upload_triggered') else 'none',
                        'no_save': True,
                        'no_publish': True,
                        'no_ad_or_payment': True,
                    },
                )
                events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

            if upload_error or upload_gate.get('blockers'):
                return api_error('主图视频上传截停后校验未通过', data={
                    'preflight': preflight,
                    'upload_gate': upload_gate,
                    'upload_result': upload_result,
                    'post_upload_snapshot': post_upload_snapshot,
                    'record': context['record_context'],
                    'issue_action': context['issue_action'],
                    'updated_action': updated_action,
                    'events': events,
                    'ai_policy': dict(AI_POLICY),
                })

            return api_ok('主图视频已触发上传并在保存/发布前截停', data={
                'preflight': preflight,
                'upload_gate': upload_gate,
                'upload_result': upload_result,
                'post_upload_snapshot': post_upload_snapshot,
                'record': context['record_context'],
                'issue_action': context['issue_action'],
                'updated_action': updated_action,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'主图视频上传截停失败: {str(exc)}')

    @routes.post('/api/ops/save-edit-human-gate')
    def ops_save_edit_human_gate():
        try:
            data = ops_request_data()
            context = resolve_publish_preflight_context(data)
            action_id = context['action_id']
            preflight = context['preflight']
            issue_action = context['issue_action'] if isinstance(context['issue_action'], dict) else {}
            upload_evidence = issue_action.get('evidence') if isinstance(issue_action.get('evidence'), dict) else {}

            tab = probe.current_or_reusable_fxg_tab()
            if not tab:
                return api_error('保存前人工安全闸检查失败：未找到可复用的已登录抖店浏览器', data={
                    'preflight': preflight,
                    'ai_policy': dict(AI_POLICY),
                })

            main_video_field = main_video_field_snapshot(tab)
            page_snapshot = probe.publish_preflight_page_snapshot()
            page_snapshot['main_video_field'] = main_video_field
            gate = build_save_edit_human_gate(
                preflight,
                upload_evidence=upload_evidence,
                page_snapshot=page_snapshot,
            )

            updated_action = None
            events = []
            if action_id:
                note = (
                    '保存前人工安全闸已就绪：可请求用户确认保存当前编辑页；仍未自动保存、未发布、未投放'
                    if gate.get('ready_for_human_save_confirmation')
                    else '保存前人工安全闸未通过：' + '；'.join(item.get('message', '') for item in gate.get('blockers', []))
                )
                next_evidence = {
                    **upload_evidence,
                    'save_edit_human_gate': gate,
                    'latest_preflight': preflight,
                    'record': context['record_context'],
                    'issue_action': {
                        key: value
                        for key, value in issue_action.items()
                        if key not in ('evidence', 'evidence_json')
                    },
                    'no_auto_save': True,
                    'no_publish': True,
                    'no_ad_or_payment': True,
                }
                updated_action = get_ops_ledger().update_product_issue_action(
                    action_id=action_id,
                    action_status='in_progress',
                    note=note,
                    evidence=next_evidence,
                )
                events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

            return api_ok('保存前人工安全闸检查完成', data={
                'save_edit_human_gate': gate,
                'preflight': preflight,
                'page_snapshot': page_snapshot,
                'record': context['record_context'],
                'issue_action': context['issue_action'],
                'updated_action': updated_action,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'保存前人工安全闸检查失败: {str(exc)}')

    @routes.post('/api/ops/sync-shop-metrics')
    def ops_sync_shop_metrics():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            browser_snapshot = data.get('browser') if isinstance(data.get('browser'), dict) else probe.current_browser_snapshot()
            audit_metrics = data.get('audit_metrics') if isinstance(data.get('audit_metrics'), list) else []
            ledger = get_ops_ledger()
            audit_rows = []

            if browser_snapshot.get('url') or browser_snapshot.get('title'):
                audit_rows.extend(ledger.save_browser_metric_audit([
                    {
                        'metric_name': 'browser_page',
                        'metric_value': browser_snapshot.get('title') or '',
                        'page_url': browser_snapshot.get('url') or '',
                        'status': browser_snapshot.get('status') or 'observed',
                    }
                ]))
            if audit_metrics:
                audit_rows.extend(ledger.save_browser_metric_audit(audit_metrics))

            if not metrics:
                return api_ok('浏览器状态已记录，但没有读取到经营指标；未生成利润快照', data={
                    'synced': False,
                    'browser': browser_snapshot,
                    'audit_rows': audit_rows,
                    'message': '需要在已登录抖店经营页面提供或读取订单、退款、推广等指标后再入账',
                    'ai_policy': dict(AI_POLICY),
                })

            previous_snapshots = ledger.list_daily_snapshots(limit=10)
            metrics = merge_observed_shop_metrics(metrics, previous_snapshots)
            snapshot = ledger.save_daily_snapshot({
                'snapshot_date': metrics.get('snapshot_date'),
                'net_profit': metrics.get('net_profit', 0),
                'net_profit_verified': bool(metrics.get('net_profit_verified', 'net_profit' in metrics)),
                'gross_sales': metrics.get('gross_sales', 0),
                'orders_count': metrics.get('orders_count', 0),
                'product_exposure_count': metrics.get('product_exposure_count', 0),
                'product_click_count': metrics.get('product_click_count', 0),
                'search_exposure_count': metrics.get('search_exposure_count', 0),
                'refund_amount': metrics.get('refund_amount', 0),
                'after_sale_amount': metrics.get('after_sale_amount', 0),
                'promotion_cost': metrics.get('promotion_cost', 0),
                'experience_score': metrics.get('experience_score'),
                'source': metrics.get('source') or data.get('source') or 'browser',
                'status': metrics.get('status') or 'partial',
                'notes': metrics.get('notes') or '',
                'raw_payload': metrics.get('raw_payload') or data.get('raw_payload') or {},
            })
            plan = build_daily_plan(metrics)
            return api_ok('经营指标同步完成', data={
                'synced': True,
                'snapshot': snapshot,
                'daily_plan': plan,
                'browser': browser_snapshot,
                'audit_rows': audit_rows,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'经营指标同步失败: {str(exc)}')
