/**
 * Frontend Performance Optimization JavaScript Library
 * Contains debounce, throttle, DOM batch operations, event optimization, etc.
 */

(function(window) {
    'use strict';

    // Performance optimization tools namespace
    const PerformanceOptimizer = {

        // ===== Debounce and Throttle Functions =====

        /**
         * Debounce function - delay execution, only execute the last call
         * @param {Function} func - function to debounce
         * @param {number} delay - delay time(ms)
         * @param {boolean} immediate - whether to execute immediately for the first time
         * @returns {Function} debounced function
         */
        debounce: function(func, delay, immediate = false) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    timeout = null;
                    if (!immediate) func.apply(this, args);
                };
                const callNow = immediate && !timeout;
                clearTimeout(timeout);
                timeout = setTimeout(later, delay);
                if (callNow) func.apply(this, args);
            };
        },

        /**
         * Throttle function - limit execution frequency
         * @param {Function} func - function to throttle
         * @param {number} limit - limit interval(ms)
         * @returns {Function} throttled function
         */
        throttle: function(func, limit) {
            let inThrottle;
            return function(...args) {
                if (!inThrottle) {
                    func.apply(this, args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        },

        /**
         * Smart debounce - automatically choose delay time based on operation type
         * @param {Function} func - function to debounce
         * @param {string} type - operation type ('input', 'scroll', 'resize', 'search')
         * @returns {Function} debounced function
         */
        smartDebounce: function(func, type) {
            const delays = {
                input: 300,
                scroll: 100,
                resize: 250,
                search: 500
            };
            return this.debounce(func, delays[type] || 300);
        },

        // ===== DOM Batch Operations Optimization =====

        /**
         * DOM batch updater
         */
        DOMBatcher: {
            queue: [],
            scheduled: false,

            /**
             * Add DOM operation to batch queue
             * @param {Function} operation - DOM operation function
             */
            add: function(operation) {
                this.queue.push(operation);
                this.schedule();
            },

            /**
             * Schedule batch execution
             */
            schedule: function() {
                if (!this.scheduled) {
                    this.scheduled = true;
                    requestAnimationFrame(() => this.flush());
                }
            },

            /**
             * Execute all queued DOM operations
             */
            flush: function() {
                this.queue.forEach(operation => {
                    try {
                        operation();
                    } catch (error) {
                        console.warn('DOM batch operation execution failed:', error);
                    }
                });
                this.queue = [];
                this.scheduled = false;
            }
        },

        /**
         * Batch DOM update wrapper
         * @param {Function} operation - DOM operation function
         */
        batchUpdate: function(operation) {
            this.DOMBatcher.add(operation);
        },

        /**
         * Document fragment optimizer - reduce reflow and repaint
         * @param {Array} elements - array of elements to add
         * @param {Element} container - container element
         */
        appendWithFragment: function(elements, container) {
            const fragment = document.createDocumentFragment();
            elements.forEach(element => fragment.appendChild(element));
            container.appendChild(fragment);
        },

        // ===== Event Handling Optimization =====

        /**
         * Optimized event listener manager
         */
        EventManager: {
            listeners: new Map(),

            /**
             * Add optimized event listener
             * @param {Element} element - target element
             * @param {string} event - event type
             * @param {Function} handler - event handler function
             * @param {Object} options - options
             */
            add: function(element, event, handler, options = {}) {
                const optimizedHandler = this.optimizeHandler(handler, event, options);
                const key = this.generateKey(element, event);
                
                // Store original handler for removal
                if (!this.listeners.has(key)) {
                    this.listeners.set(key, new Map());
                }
                this.listeners.get(key).set(handler, optimizedHandler);

                // Add event listener with passive option for better performance
                const eventOptions = {
                    passive: ['scroll', 'wheel', 'touchstart', 'touchmove'].includes(event),
                    ...options
                };
                
                element.addEventListener(event, optimizedHandler, eventOptions);
            },

            /**
             * Remove event listener
             * @param {Element} element - target element
             * @param {string} event - event type
             * @param {Function} handler - original handler function
             */
            remove: function(element, event, handler) {
                const key = this.generateKey(element, event);
                const listeners = this.listeners.get(key);
                
                if (listeners && listeners.has(handler)) {
                    const optimizedHandler = listeners.get(handler);
                    element.removeEventListener(event, optimizedHandler);
                    listeners.delete(handler);
                    
                    if (listeners.size === 0) {
                        this.listeners.delete(key);
                    }
                }
            },

            /**
             * Optimize event handler function
             * @param {Function} handler - original handler function
             * @param {string} event - event type
             * @param {Object} options - options
             * @returns {Function} optimized handler function
             */
            optimizeHandler: function(handler, event, options) {
                // Apply different optimization strategies based on event type
                switch (event) {
                    case 'scroll':
                    case 'resize':
                        return PerformanceOptimizer.throttle(handler, options.throttle || 16);
                    case 'input':
                    case 'keyup':
                        return PerformanceOptimizer.debounce(handler, options.debounce || 300);
                    default:
                        return handler;
                }
            },

            /**
             * Generate listener key
             * @param {Element} element - target element
             * @param {string} event - event type
             * @returns {string} key
             */
            generateKey: function(element, event) {
                return `${element.tagName}_${element.id || 'no-id'}_${event}`;
            }
        },

        // ===== Scroll Performance Optimization =====

        /**
         * Virtual scroll implementation
         */
        VirtualScroll: {
            /**
             * Create virtual scroll container
             * @param {Object} config - configuration object
             * @returns {Object} virtual scroll instance
             */
            create: function(config) {
                const {
                    container,
                    items,
                    itemHeight,
                    renderItem,
                    visibleCount = Math.ceil(container.clientHeight / itemHeight) + 2
                } = config;

                let scrollTop = 0;
                let startIndex = 0;
                let endIndex = Math.min(startIndex + visibleCount, items.length);

                const render = () => {
                    // Calculate visible range
                    startIndex = Math.floor(scrollTop / itemHeight);
                    endIndex = Math.min(startIndex + visibleCount, items.length);

                    // Create top placeholder space
                    const topSpace = document.createElement('div');
                    topSpace.style.height = `${startIndex * itemHeight}px`;

                    // Render visible items
                    const visibleItems = items.slice(startIndex, endIndex).map((item, index) => 
                        renderItem(item, startIndex + index)
                    );

                    // Create bottom placeholder space
                    const bottomSpace = document.createElement('div');
                    bottomSpace.style.height = `${(items.length - endIndex) * itemHeight}px`;

                    // Batch update DOM
                    PerformanceOptimizer.batchUpdate(() => {
                        container.innerHTML = '';
                        container.appendChild(topSpace);
                        visibleItems.forEach(item => container.appendChild(item));
                        container.appendChild(bottomSpace);
                    });
                };

                // Bind scroll event
                const handleScroll = PerformanceOptimizer.throttle(() => {
                    scrollTop = container.scrollTop;
                    render();
                }, 16);

                container.addEventListener('scroll', handleScroll, { passive: true });

                // Initial render
                render();

                return { render, destroy: () => container.removeEventListener('scroll', handleScroll) };
            }
        },

        // ===== Memory Optimization =====

        /**
         * Memory manager
         */
        MemoryManager: {
            cache: new Map(),
            maxSize: 100,

            /**
             * Set cache
             * @param {string} key - cache key
             * @param {*} value - cache value
             */
            set: function(key, value) {
                if (this.cache.size >= this.maxSize) {
                    const firstKey = this.cache.keys().next().value;
                    this.cache.delete(firstKey);
                }
                this.cache.set(key, value);
            },

            /**
             * Get cache
             * @param {string} key - cache key
             * @returns {*} cache value
             */
            get: function(key) {
                return this.cache.get(key);
            },

            /**
             * Clear cache
             */
            clear: function() {
                this.cache.clear();
            },

            /**
             * Get memory usage
             * @returns {Object} memory info
             */
            getMemoryInfo: function() {
                if (performance.memory) {
                    return {
                        used: performance.memory.usedJSHeapSize,
                        total: performance.memory.totalJSHeapSize,
                        limit: performance.memory.jsHeapSizeLimit
                    };
                }
                return null;
            }
        },

        // ===== Network Request Optimization =====

        /**
         * Request manager
         */
        RequestManager: {
            cache: new Map(),
            pendingRequests: new Map(),
            requestQueue: [],
            isProcessingQueue: false,

            /**
             * Optimized AJAX request
             * @param {Object} options - request options
             * @returns {Promise} request Promise
             */
            request: function(options) {
                const cacheKey = this.generateCacheKey(options);
                
                // Check cache
                if (options.cache !== false && this.cache.has(cacheKey)) {
                    return Promise.resolve(this.cache.get(cacheKey));
                }

                // Check if same request is in progress
                if (this.pendingRequests.has(cacheKey)) {
                    return this.pendingRequests.get(cacheKey);
                }

                // Create new request
                const requestPromise = this.createRequest(options);
                this.pendingRequests.set(cacheKey, requestPromise);

                // Cache response
                requestPromise.then(response => {
                    if (options.cache !== false) {
                        this.cache.set(cacheKey, response);
                    }
                    this.pendingRequests.delete(cacheKey);
                }).catch(() => {
                    this.pendingRequests.delete(cacheKey);
                });

                return requestPromise;
            },

            /**
             * Create request
             * @param {Object} options - request options
             * @returns {Promise} request Promise
             */
            createRequest: function(options) {
                return new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open(options.method || 'GET', options.url, true);
                    
                    // Set request headers
                    if (options.headers) {
                        Object.keys(options.headers).forEach(key => {
                            xhr.setRequestHeader(key, options.headers[key]);
                        });
                    }

                    xhr.onload = function() {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            try {
                                const response = options.responseType === 'json' ? 
                                    JSON.parse(xhr.responseText) : xhr.responseText;
                                resolve(response);
                            } catch (e) {
                                reject(new Error('Response parsing failed'));
                            }
                        } else {
                            reject(new Error(`Request failed with status ${xhr.status}`));
                        }
                    };

                    xhr.onerror = () => reject(new Error('Network error'));
                    xhr.ontimeout = () => reject(new Error('Request timeout'));

                    if (options.timeout) {
                        xhr.timeout = options.timeout;
                    }

                    xhr.send(options.data || null);
                });
            },

            /**
             * Generate cache key
             * @param {Object} options - request options
             * @returns {string} cache key
             */
            generateCacheKey: function(options) {
                return `${options.method || 'GET'}_${options.url}_${JSON.stringify(options.data || {})}`;
            },

            /**
             * Batch requests
             * @param {Array} requests - request array
             * @returns {Promise} batch request Promise
             */
            batchRequest: function(requests) {
                return Promise.all(requests.map(request => this.request(request)));
            },

            /**
             * Batch request processing (execute in batches)
             * @param {Array} requests - request array
             * @param {Object} options - options
             * @returns {Promise} batch request Promise
             */
            batchRequestWithLimit: function(requests, options = {}) {
                const { batchSize = 5, delay = 100 } = options;
                const results = [];
                
                const processBatch = async (batch) => {
                    const batchResults = await Promise.allSettled(
                        batch.map(request => this.request(request))
                    );
                    results.push(...batchResults);
                };

                const processAllBatches = async () => {
                    for (let i = 0; i < requests.length; i += batchSize) {
                        const batch = requests.slice(i, i + batchSize);
                        await processBatch(batch);
                        
                        // Add delay between batches
                        if (i + batchSize < requests.length && delay > 0) {
                            await new Promise(resolve => setTimeout(resolve, delay));
                        }
                    }
                    return results;
                };

                return processAllBatches();
            },

            /**
             * Queue request
             * @param {Object} options - request options
             * @returns {Promise} request Promise
             */
            queueRequest: function(options) {
                return new Promise((resolve, reject) => {
                    this.requestQueue.push({
                        options,
                        resolve,
                        reject
                    });
                    this.processQueue();
                });
            },

            /**
             * Process request queue
             */
            processQueue: function() {
                if (this.isProcessingQueue || this.requestQueue.length === 0) {
                    return;
                }

                this.isProcessingQueue = true;
                const maxConcurrent = 3; // Maximum concurrent requests

                const processNext = () => {
                    if (this.requestQueue.length === 0) {
                        this.isProcessingQueue = false;
                        return;
                    }

                    const batch = this.requestQueue.splice(0, maxConcurrent);
                    const promises = batch.map(({ options, resolve, reject }) => {
                        return this.request(options).then(resolve).catch(reject);
                    });

                    Promise.allSettled(promises).then(() => {
                        this.processQueue(); // Process remaining queue
                    });
                };

                processNext();
            },

            /**
             * Retry request
             * @param {Object} options - request options
             * @param {number} maxRetries - maximum retry count
             * @param {number} retryDelay - retry delay
             * @returns {Promise} request Promise
             */
            retryRequest: function(options, maxRetries = 3, retryDelay = 1000) {
                let attempts = 0;

                const attemptRequest = () => {
                    return this.request(options).catch(error => {
                        attempts++;
                        if (attempts < maxRetries) {
                            return new Promise((resolve, reject) => {
                                setTimeout(() => {
                                    attemptRequest().then(resolve).catch(reject);
                                }, retryDelay * attempts); // Exponential backoff
                            });
                        } else {
                            throw error;
                        }
                    });
                };

                return attemptRequest();
            },

            /**
             * Timeout request
             * @param {Object} options - request options
             * @param {number} timeout - timeout duration
             * @returns {Promise} request Promise
             */
            timeoutRequest: function(options, timeout = 5000) {
                const timeoutPromise = new Promise((_, reject) => {
                    setTimeout(() => reject(new Error('Request timeout')), timeout);
                });

                return Promise.race([
                    this.request(options),
                    timeoutPromise
                ]);
            },

            /**
             * Clear cache
             */
            clearCache: function() {
                this.cache.clear();
            },

            /**
             * Get cache statistics
             * @returns {Object} cache statistics
             */
            getCacheStats: function() {
                return {
                    size: this.cache.size,
                    keys: Array.from(this.cache.keys())
                };
            }
        },

        // ===== Performance Monitoring =====

        /**
         * Performance monitor
         */
        PerformanceMonitor: {
            isMonitoring: false,
            metrics: {},

            /**
             * Start monitoring
             */
            start: function() {
                if (this.isMonitoring) return;
                
                this.isMonitoring = true;
                this.monitorFPS();
                this.monitorMemory();
                this.monitorNetworkRequests();
                this.monitorDOMOperations();
            },

            /**
             * Monitor FPS
             */
            monitorFPS: function() {
                let lastTime = performance.now();
                let frameCount = 0;
                
                const measureFPS = () => {
                    frameCount++;
                    const currentTime = performance.now();
                    
                    if (currentTime - lastTime >= 1000) {
                        this.metrics.fps = Math.round((frameCount * 1000) / (currentTime - lastTime));
                        frameCount = 0;
                        lastTime = currentTime;
                    }
                    
                    if (this.isMonitoring) {
                        requestAnimationFrame(measureFPS);
                    }
                };
                
                requestAnimationFrame(measureFPS);
            },

            /**
             * Monitor memory usage
             */
            monitorMemory: function() {
                const updateMemory = () => {
                    if (performance.memory) {
                        this.metrics.memory = {
                            used: Math.round(performance.memory.usedJSHeapSize / 1048576), // MB
                            total: Math.round(performance.memory.totalJSHeapSize / 1048576) // MB
                        };
                    }
                    
                    if (this.isMonitoring) {
                        setTimeout(updateMemory, 1000);
                    }
                };
                
                updateMemory();
            },

            /**
             * Monitor network requests
             */
            monitorNetworkRequests: function() {
                this.metrics.networkRequests = 0;
                
                // Override XMLHttpRequest to monitor requests
                const originalOpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function() {
                    PerformanceOptimizer.PerformanceMonitor.metrics.networkRequests++;
                    return originalOpen.apply(this, arguments);
                };
                
                // Monitor fetch requests
                if (window.fetch) {
                    const originalFetch = window.fetch;
                    window.fetch = function() {
                        PerformanceOptimizer.PerformanceMonitor.metrics.networkRequests++;
                        return originalFetch.apply(this, arguments);
                    };
                }
            },

            /**
             * Monitor DOM operations
             */
            monitorDOMOperations: function() {
                this.metrics.domNodes = document.querySelectorAll('*').length;
                
                // Monitor DOM changes
                const observer = new MutationObserver(() => {
                    this.metrics.domNodes = document.querySelectorAll('*').length;
                });
                
                observer.observe(document.body, {
                    childList: true,
                    subtree: true
                });
            },

            /**
             * Get performance metrics
             * @returns {Object} performance metrics
             */
            getMetrics: function() {
                return { ...this.metrics };
            },

            /**
             * Stop monitoring
             */
            stop: function() {
                this.isMonitoring = false;
            }
        },

        // ===== Initialization Methods =====

        /**
         * Initialize performance optimization
         * @param {Object} options - configuration options
         */
        init: function(options = {}) {
            console.log('Initializing frontend performance optimization...');
            
            // Start performance monitoring
            if (options.enableMonitoring !== false) {
                this.PerformanceMonitor.start();
            }
            
            // Optimize existing event listeners
            this.optimizeExistingEvents();
            
            // Set global error handling
            this.setupErrorHandling();
            
            console.log('Frontend performance optimization initialization completed');
        },

        /**
         * Optimize existing event listeners
         */
        optimizeExistingEvents: function() {
            // Optimize scroll events
            const scrollElements = document.querySelectorAll('[data-scroll-optimize]');
            scrollElements.forEach(element => {
                const originalHandler = element.onscroll;
                if (originalHandler) {
                    element.onscroll = this.throttle(originalHandler, 16);
                }
            });
            
            // Optimize input events
            const inputElements = document.querySelectorAll('input[data-input-optimize]');
            inputElements.forEach(element => {
                const originalHandler = element.oninput;
                if (originalHandler) {
                    element.oninput = this.debounce(originalHandler, 300);
                }
            });
        },

        /**
         * Set global error handling
         */
        setupErrorHandling: function() {
            window.addEventListener('error', (event) => {
                console.warn('Performance optimization caught error:', event.error);
            });
            
            window.addEventListener('unhandledrejection', (event) => {
                console.warn('Performance optimization caught unhandled Promise rejection:', event.reason);
            });
        }
    };

    // Export to global scope
    window.PerformanceOptimizer = PerformanceOptimizer;

})(window);