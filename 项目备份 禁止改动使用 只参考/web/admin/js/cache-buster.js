
        // 缓存清理机制
        (function() {
            var version = new Date().getTime();
            var links = document.querySelectorAll('link[rel="stylesheet"]');
            var scripts = document.querySelectorAll('script[src]');
            
            // 为CSS文件添加版本参数
            links.forEach(function(link) {
                if (link.href.indexOf('?') > -1) {
                    link.href = link.href.split('?')[0] + '?v=' + version;
                } else {
                    link.href += '?v=' + version;
                }
            });
        })();
        