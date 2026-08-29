# -*- coding: utf-8 -*-
"""深入研究 window.secsdk.csrf 来找 _aToken 生成方式。"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)
mid = [0]

def send_cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    return mid[0]

def recv_until(msg_id, timeout_sec=20):
    dl = time.time() + timeout_sec
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except:
            break
        try:
            msg = json.loads(raw)
        except:
            continue
        if msg.get('id') == msg_id:
            return msg
    return {}

send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

# 1. Deep inspect window.secsdk
print('[1] Inspecting window.secsdk...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            if (!window.secsdk) {
                results.error = 'secsdk not found';
                return JSON.stringify(results);
            }

            // Get all keys
            results.keys = Object.keys(window.secsdk);

            // Inspect csrf object
            if (window.secsdk.csrf) {
                var csrf = window.secsdk.csrf;
                results.csrfKeys = Object.keys(csrf);
                results.csrfProto = Object.getOwnPropertyNames(Object.getPrototypeOf(csrf) || {}).slice(0, 20);

                // Try to get all properties including non-enumerable
                var allProps = [];
                for (var k in csrf) {
                    try {
                        var v = csrf[k];
                        var t = typeof v;
                        if (t === 'function') {
                            allProps.push({key: k, type: 'function', src: v.toString().substring(0, 150)});
                        } else if (t === 'string') {
                            allProps.push({key: k, type: 'string', val: v.substring(0, 80)});
                        } else {
                            allProps.push({key: k, type: t});
                        }
                    } catch(e) {
                        allProps.push({key: k, type: 'error', msg: e.message});
                    }
                }
                results.csrfAllProps = allProps;

                // Try to get _aToken directly
                try {
                    results.currentToken = csrf.getToken ? csrf.getToken() : 'no getToken';
                } catch(e) {
                    results.getTokenError = e.message;
                }

                // Try common method names
                ['getToken', 'getCSRFToken', 'sign', 'encrypt', 'generate', 'getAtoken', 'get_aToken', 'createToken'].forEach(function(m) {
                    if (typeof csrf[m] === 'function') {
                        try {
                            results['call_' + m] = csrf[m]();
                        } catch(e) {
                            results['call_' + m] = 'error: ' + e.message;
                        }
                    }
                });
            }

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:2000]}')

# 2. Look for the _aToken in the addWithSchema request construction code
print('\n[2] Searching for how the page constructs addWithSchema body...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            // Search all inline scripts for addWithSchema or request_extra
            var scripts = document.querySelectorAll('script:not([src])');
            scripts.forEach(function(s, i) {
                var text = s.textContent || '';
                if (text.includes('addWithSchema') || text.includes('request_extra') || text.includes('_aToken')) {
                    var idx = text.indexOf('_aToken');
                    if (idx < 0) idx = text.indexOf('request_extra');
                    if (idx < 0) idx = text.indexOf('addWithSchema');
                    results['script_' + i] = text.substring(Math.max(0, idx - 50), idx + 200);
                }
            });

            // Also check what the webpack post function actually receives
            // The post function might call a body transform function before sending
            // Let's monkey-patch it to see
            if (!window.__fxgWebpackRequire) {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }

            var req = window.__fxgWebpackRequire;
            // Try to find axios interceptor or request transform functions
            var postMod = req(90665);

            // The bE function calls eJ(e,t,"request") - let's look for eJ
            // Search the entire chunk for eJ function definition
            if (!window.__fxgChunkContent) {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                if (chunkName) {
                    // Try to get the full chunk source by evaluating it
                    try {
                        var chunkStr = JSON.stringify(window[chunkName], function(key, val) {
                            if (typeof val === 'function') return val.toString();
                            return val;
                        });
                        window.__fxgChunkContent = chunkStr;
                    } catch(e) {}
                }
            }

            results.chunkSize = window.__fxgChunkContent ? window.__fxgChunkContent.length : 0;

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 15000
})
r = recv_until(mid[0], timeout_sec=20)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:2000]}')

# 3. Check if _aToken is in the secsdk csrf token header
print('\n[3] Checking relationship between secsdk csrf and _aToken...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            // The x-secsdk-csrf-token header format: 000100000001...
            // Maybe _aToken is extracted from or related to this
            if (window.secsdk && window.secsdk.csrf) {
                // Try to get any token-related values
                try {
                    // Some security SDKs store token in a getter
                    var descs = Object.getOwnPropertyDescriptors(window.secsdk.csrf);
                    results.descriptors = Object.keys(descs).slice(0, 20);
                } catch(e) {
                    results.descError = e.message;
                }

                // Try to enumerate all methods
                var methods = [];
                var obj = window.secsdk.csrf;
                do {
                    Object.getOwnPropertyNames(obj).forEach(function(k) {
                        if (methods.indexOf(k) < 0) methods.push(k);
                    });
                    obj = Object.getPrototypeOf(obj);
                } while (obj && obj !== Object.prototype);
                results.allMethods = methods;
            }

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1500]}')

# 4. Try hooking the addWithSchema network call to capture how the body is constructed
print('\n[4] Setting up XHR/fetch hook to capture addWithSchema body construction...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // Monkey-patch the webpack post function to log the final body
            if (!window.__fxgWebpackRequire) {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;
            var originalBE = req(90665).bE;

            // Store original
            window.__originalPost = originalBE;
            window.__capturedBodies = [];

            // Replace with interception
            req(90665).bE = function(url, body, options) {
                window.__capturedBodies.push({
                    url: url,
                    body: JSON.parse(JSON.stringify(body)),
                    time: new Date().toISOString()
                });
                return originalBE.call(this, url, body, options);
            };

            return JSON.stringify({hooked: true});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
print(f'    Hook installed')

# 5. Trigger a real page action that makes an addWithSchema call
# Navigate to a test scenario: click "发布" button or save draft
print('\n[5] Attempting to trigger addWithSchema through page UI...')
print('    (Check if there is a form we can submit)')

r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // Check for any submit buttons or form actions
            var buttons = document.querySelectorAll('button');
            var submitBtn = null;
            buttons.forEach(function(b) {
                var text = (b.textContent || '').trim();
                if (text.includes('发布') || text.includes('保存') || text.includes('提交') || text.includes('草稿')) {
                    submitBtn = {text: text, disabled: b.disabled, visible: b.offsetParent !== null};
                }
            });
            return JSON.stringify({buttonsFound: buttons.length, submitBtn: submitBtn});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:500]}')

# 6. Since we can't trigger the page's submit, let's try a different approach:
# Get the _aToken from secsdk by calling its sign/transform function
print('\n[6] Trying to use secsdk to sign a request body...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            if (window.secsdk) {
                // Try to access the CSRF token directly
                if (window.secsdk.csrf) {
                    try {
                        // Some secsdk versions expose a sign() or transformRequest() method
                        var testBody = {test: true};
                        var testUrl = '/product/tproduct/addWithSchema';

                        if (typeof window.secsdk.csrf.sign === 'function') {
                            results.signed = window.secsdk.csrf.sign(testBody, testUrl);
                        }
                        if (typeof window.secsdk.csrf.transformRequest === 'function') {
                            results.transformed = window.secsdk.csrf.transformRequest(testBody, testUrl);
                        }
                        if (typeof window.secsdk.csrf.getRequestExtra === 'function') {
                            results.requestExtra = window.secsdk.csrf.getRequestExtra();
                        }

                        // Try to find any function that returns a string (likely the token)
                        var methodsWithResults = {};
                        Object.keys(window.secsdk.csrf).forEach(function(k) {
                            try {
                                if (typeof window.secsdk.csrf[k] === 'function' && k !== 'setOptions') {
                                    var result = window.secsdk.csrf[k]();
                                    if (typeof result === 'string' && result.length > 10) {
                                        methodsWithResults[k] = result.substring(0, 100);
                                    }
                                }
                            } catch(e) {}
                        });
                        results.methodResults = methodsWithResults;
                    } catch(e) {
                        results.error = e.message;
                    }
                }
            }

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1000]}')

# 7. Let's try to find the secsdk script URL and examine it
print('\n[7] Finding secsdk script URL...')
r = send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = [];
            var scripts = document.querySelectorAll('script[src]');
            scripts.forEach(function(s) {
                if (s.src && (s.src.includes('sec') || s.src.includes('sdk') || s.src.includes('goofy') || s.src.includes('byte'))) {
                    results.push(s.src);
                }
            });
            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1500]}')

ws.close()
