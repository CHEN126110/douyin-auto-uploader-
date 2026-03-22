(function (root, factory) {
	if(typeof define === 'function' && define.amd) {
		define([], factory(root));
	} else if(typeof exports === 'object') {
		module.exports = factory(root);
	} else if (window.layui && layui.define) {
		layui.define(function(exports){
            exports('toast',factory(root))
		})
	}else {
		root.iziToast = factory(root);
	}
})(typeof global !== 'undefined' ? global : window || this.window || this.global, function (root) {

	'use strict';

	var dollariziToast = {},
		PLUGIN_NAME = 'iziToast',
		BODY = document.querySelector('body'),
		ISMOBILE = (/Mobi/.test(navigator.userAgent)) ? true : false,
		ISCHROME = /Chrome/.test(navigator.userAgent) && /Google Inc/.test(navigator.vendor),
		ISFIREFOX = typeof InstallTrigger !== 'undefined',
		ACCEPTSTOUCH = 'ontouchstart' in document.documentElement,
		POSITIONS = ['bottomRight','bottomLeft','bottomCenter','topRight','topLeft','topCenter','center'],
		THEMES = {
			info: {
				color: 'blue',
				icon: 'ico-info'
			},
			success: {
				color: 'green',
				icon: 'ico-success'
			},
			warning: {
				color: 'orange',
				icon: 'ico-warning'
			},
			error: {
				color: 'red',
				icon: 'ico-error'
			},
			question: {
				color: 'yellow',
				icon: 'ico-question'
			}
		},
		MOBILEWIDTH = 568,
		CONFIG = {};

	dollariziToast.children = {};

	// Default settings
	var defaults = {
		id: null, 
		class: '',
		title: '',
		titleColor: '',
		titleSize: '',
		titleLineHeight: '',
		message: '',
		messageColor: '',
		messageSize: '',
		messageLineHeight: '',
		backgroundColor: '',
		theme: 'light', // dark
		color: '', // blue, red, green, yellow
		icon: '',
		iconText: '',
		iconColor: '',
		iconUrl: null,
		image: '',
		imageWidth: 50,
		maxWidth: null,
		zindex: null,
		layout: 2,
		balloon: false,
		close: true,
		closeOnEscape: false,
		closeOnClick: false,
		displayMode: 0,
		position: 'topCenter', // bottomRight, bottomLeft, topRight, topLeft, topCenter, bottomCenter, center
		target: '',
		targetFirst: true,
		timeout: 3000, // 默认3秒
		rtl: false,
		animateInside: false, // 动画效果
		drag: true,
		pauseOnHover: true,
		resetOnHover: false,
		progressBar: false,
		progressBarColor: '',
		progressBarEasing: 'linear',
		overlay: false,
		overlayClose: false,
		overlayColor: 'rgba(0, 0, 0, 0.6)',
        transitionIn: 'fadeInDown', // bounceInLeft, bounceInRight, bounceInUp, bounceInDown, fadeIn, fadeInDown, fadeInUp, fadeInLeft, fadeInRight, flipInX
        transitionOut: 'fadeOut', // fadeOut, fadeOutUp, fadeOutDown, fadeOutLeft, fadeOutRight, flipOutX
        transitionInMobile: 'bounceInDown',  
        transitionOutMobile: 'fadeOutUp', 
		buttons: {},
		inputs: {},
		onOpening: function () {},
		onOpened: function () {},
		onClosing: function () {},
		onClosed: function () {}
	};

	if(!('remove' in Element.prototype)) {
	    Element.prototype.remove = function() {
	        if(this.parentNode) {
	            this.parentNode.removeChild(this);
	        }
	    };
	}
	
    if(typeof window.CustomEvent !== 'function') {
        var CustomEventPolyfill = function (event, params) {
            params = params || { bubbles: false, cancelable: false, detail: undefined };
            var evt = document.createEvent('CustomEvent');
            evt.initCustomEvent(event, params.bubbles, params.cancelable, params.detail);
            return evt;
        };

        CustomEventPolyfill.prototype = window.Event.prototype;

        window.CustomEvent = CustomEventPolyfill;
    }

	var forEach = function (collection, callback, scope) {
		if(Object.prototype.toString.call(collection) === '[object Object]') {
			for (var prop in collection) {
				if(Object.prototype.hasOwnProperty.call(collection, prop)) {
					callback.call(scope, collection[prop], prop, collection);
				}
			}
		} else {
			if(collection){
				for (var i = 0, len = collection.length; i < len; i++) {
					callback.call(scope, collection[i], i, collection);
				}
			}
		}
	};

	var extend = function (defaults, options) {
		var extended = {};
		forEach(defaults, function (value, prop) {
			extended[prop] = defaults[prop];
		});
		forEach(options, function (value, prop) {
			extended[prop] = options[prop];
		});
		return extended;
	};

	var createFragElem = function(htmlStr) {
		var frag = document.createDocumentFragment(),
			temp = document.createElement('div');
		temp.innerHTML = htmlStr;
		while (temp.firstChild) {
			frag.appendChild(temp.firstChild);
		}
		return frag;
	};

	var generateId = function(params) {
		var newId = btoa(encodeURIComponent(params));
		return newId.replace(/=/g, "");
	};

	var isColor = function(color){
		if( color.substring(0,1) == '#' || color.substring(0,3) == 'rgb' || color.substring(0,3) == 'hsl' ){
			return true;
		} else {
			return false;
		}
	};

	var isBase64 = function(str) {
	    try {
	        return btoa(atob(str)) == str;
	    } catch (err) {
	        return false;
	    }
	};

	var drag = function() {
	    
	    return {
	        move: function(toast, instance, settings, xpos) {

	        	var opacity,
	        		opacityRange = 0.3,
	        		distance = 180;
	            
	            if(xpos !== 0){
	            	
	            	toast.classList.add(PLUGIN_NAME+'-dragged');

	            	toast.style.transform = 'translateX('+xpos + 'px)';

		            if(xpos > 0){
		            	opacity = (distance-xpos) / distance;
		            	if(opacity < opacityRange){
							instance.hide(extend(settings, { transitionOut: 'fadeOutRight', transitionOutMobile: 'fadeOutRight' }), toast, 'drag');
						}
		            } else {
		            	opacity = (distance+xpos) / distance;
		            	if(opacity < opacityRange){
							instance.hide(extend(settings, { transitionOut: 'fadeOutLeft', transitionOutMobile: 'fadeOutLeft' }), toast, 'drag');
						}
		            }
					toast.style.opacity = opacity;
			
					if(opacity < opacityRange){

						if(ISCHROME || ISFIREFOX)
							toast.style.left = xpos+'px';

						toast.parentNode.style.opacity = opacityRange;

		                this.stopMoving(toast, null);
					}
	            }

				
	        },
	        startMoving: function(toast, instance, settings, e) {

	            e = e || window.event;
	            var posX = ((ACCEPTSTOUCH) ? e.touches[0].clientX : e.clientX),
	                toastLeft = toast.style.transform.replace('px)', '');
	                toastLeft = toastLeft.replace('translateX(', '');
	            var offsetX = posX - toastLeft;

				if(settings.transitionIn){
					toast.classList.remove(settings.transitionIn);
				}
				if(settings.transitionInMobile){
					toast.classList.remove(settings.transitionInMobile);
				}
				toast.style.transition = '';

	            if(ACCEPTSTOUCH) {
	                document.ontouchmove = function(e) {
	                    e.preventDefault();
	                    e = e || window.event;
	                    var posX = e.touches[0].clientX,
	                        finalX = posX - offsetX;
                        drag.move(toast, instance, settings, finalX);
	                };
	            } else {
	                document.onmousemove = function(e) {
	                    e.preventDefault();
	                    e = e || window.event;
	                    var posX = e.clientX,
	                        finalX = posX - offsetX;
                        drag.move(toast, instance, settings, finalX);
	                };
	            }

	        },
	        stopMoving: function(toast, e) {

	            if(ACCEPTSTOUCH) {
	                document.ontouchmove = function() {};
	            } else {
	            	document.onmousemove = function() {};
	            }

				toast.style.opacity = '';
				toast.style.transform = '';

	            if(toast.classList.contains(PLUGIN_NAME+'-dragged')){
	            	
	            	toast.classList.remove(PLUGIN_NAME+'-dragged');

					toast.style.transition = 'transform 0.4s ease, opacity 0.4s ease';
					setTimeout(function() {
						toast.style.transition = '';
					}, 400);
	            }

	        }
	    };

	}();

	dollariziToast.setSetting = function (ref, option, value) {

		dollariziToast.children[ref][option] = value;

	};

	dollariziToast.getSetting = function (ref, option) {

		return dollariziToast.children[ref][option];

	};

	dollariziToast.destroy = function () {

		forEach(document.querySelectorAll('.'+PLUGIN_NAME+'-overlay'), function(element, index) {
			element.remove();
		});

		forEach(document.querySelectorAll('.'+PLUGIN_NAME+'-wrapper'), function(element, index) {
			element.remove();
		});

		forEach(document.querySelectorAll('.'+PLUGIN_NAME), function(element, index) {
			element.remove();
		});

		this.children = {};

		// Remove event listeners
		document.removeEventListener(PLUGIN_NAME+'-opened', {}, false);
		document.removeEventListener(PLUGIN_NAME+'-opening', {}, false);
		document.removeEventListener(PLUGIN_NAME+'-closing', {}, false);
		document.removeEventListener(PLUGIN_NAME+'-closed', {}, false);
		document.removeEventListener('keyup', {}, false);

		// Reset variables
		CONFIG = {};
	};

	/**
	 * Initialize Plugin
	 * @public
	 * @param {Object} options User settings
	 */
	dollariziToast.settings = function (options) {

		// Destroy any existing initializations
		dollariziToast.destroy();

		CONFIG = options;
		defaults = extend(defaults, options || {});
	};


	/**
	 * Building themes functions.
	 * @public
	 * @param {Object} options User settings
	 */
	forEach(THEMES, function (theme, name) {

		dollariziToast[name] = function (options) {

			var settings = extend(CONFIG, options || {});
			settings = extend(theme, settings || {});

			this.show(settings);
		};

	});


	/**
	 * Do the calculation to move the progress bar
	 * @private
	 */
	dollariziToast.progress = function (options, dollartoast, callback) {


		var that = this,
			ref = dollartoast.getAttribute('data-iziToast-ref'),
			settings = extend(this.children[ref], options || {}),
			dollarelem = dollartoast.querySelector('.'+PLUGIN_NAME+'-progressbar div');

	    return {
	        start: function() {

	        	if(typeof settings.time.REMAINING == 'undefined'){

	        		dollartoast.classList.remove(PLUGIN_NAME+'-reseted');

		        	if(dollarelem !== null){
						dollarelem.style.transition = 'width '+ settings.timeout +'ms '+settings.progressBarEasing;
						dollarelem.style.width = '0%';
					}

		        	settings.time.START = new Date().getTime();
		        	settings.time.END = settings.time.START + settings.timeout;
					settings.time.TIMER = setTimeout(function() {

						clearTimeout(settings.time.TIMER);

						if(!dollartoast.classList.contains(PLUGIN_NAME+'-closing')){

							that.hide(settings, dollartoast, 'timeout');

							if(typeof callback === 'function'){
								callback.apply(that);
							}
						}

					}, settings.timeout);			
		        	that.setSetting(ref, 'time', settings.time);
	        	}
	        },
	        pause: function() {

	        	if(typeof settings.time.START !== 'undefined' && !dollartoast.classList.contains(PLUGIN_NAME+'-paused') && !dollartoast.classList.contains(PLUGIN_NAME+'-reseted')){

        			dollartoast.classList.add(PLUGIN_NAME+'-paused');

					settings.time.REMAINING = settings.time.END - new Date().getTime();

					clearTimeout(settings.time.TIMER);

					that.setSetting(ref, 'time', settings.time);

					if(dollarelem !== null){
						var computedStyle = window.getComputedStyle(dollarelem),
							propertyWidth = computedStyle.getPropertyValue('width');

						dollarelem.style.transition = 'none';
						dollarelem.style.width = propertyWidth;					
					}

					if(typeof callback === 'function'){
						setTimeout(function() {
							callback.apply(that);						
						}, 10);
					}
        		}
	        },
	        resume: function() {

				if(typeof settings.time.REMAINING !== 'undefined'){

					dollartoast.classList.remove(PLUGIN_NAME+'-paused');

		        	if(dollarelem !== null){
						dollarelem.style.transition = 'width '+ settings.time.REMAINING +'ms '+settings.progressBarEasing;
						dollarelem.style.width = '0%';
					}

		        	settings.time.END = new Date().getTime() + settings.time.REMAINING;
					settings.time.TIMER = setTimeout(function() {

						clearTimeout(settings.time.TIMER);

						if(!dollartoast.classList.contains(PLUGIN_NAME+'-closing')){

							that.hide(settings, dollartoast, 'timeout');

							if(typeof callback === 'function'){
								callback.apply(that);
							}
						}


					}, settings.time.REMAINING);

					that.setSetting(ref, 'time', settings.time);
				} else {
					this.start();
				}
	        },
	        reset: function(){

				clearTimeout(settings.time.TIMER);

				delete settings.time.REMAINING;

				that.setSetting(ref, 'time', settings.time);

				dollartoast.classList.add(PLUGIN_NAME+'-reseted');

				dollartoast.classList.remove(PLUGIN_NAME+'-paused');

				if(dollarelem !== null){
					dollarelem.style.transition = 'none';
					dollarelem.style.width = '100%';
				}

				if(typeof callback === 'function'){
					setTimeout(function() {
						callback.apply(that);						
					}, 10);
				}
	        }
	    };

	};


	/**
	 * Close the specific Toast
	 * @public
	 * @param {Object} options User settings
	 */
	dollariziToast.hide = function (options, dollartoast, closedBy) {

		if(typeof dollartoast != 'object'){
			dollartoast = document.querySelector(dollartoast);
		}		

		var that = this,
			settings = extend(this.children[dollartoast.getAttribute('data-iziToast-ref')], options || {});
			settings.closedBy = closedBy || null;

		delete settings.time.REMAINING;

		dollartoast.classList.add(PLUGIN_NAME+'-closing');

		// Overlay
		(function(){

			var dollaroverlay = document.querySelector('.'+PLUGIN_NAME+'-overlay');
			if(dollaroverlay !== null){
				var refs = dollaroverlay.getAttribute('data-iziToast-ref');		
					refs = refs.split(',');
				var index = refs.indexOf(String(settings.ref));

				if(index !== -1){
					refs.splice(index, 1);			
				}
				dollaroverlay.setAttribute('data-iziToast-ref', refs.join());

				if(refs.length === 0){
					dollaroverlay.classList.remove('fadeIn');
					dollaroverlay.classList.add('fadeOut');
					setTimeout(function() {
						dollaroverlay.remove();
					}, 700);
				}
			}

		})();

		if(settings.transitionIn){
			dollartoast.classList.remove(settings.transitionIn);
		} 

		if(settings.transitionInMobile){
			dollartoast.classList.remove(settings.transitionInMobile);
		}

		if(ISMOBILE || window.innerWidth <= MOBILEWIDTH){
			if(settings.transitionOutMobile)
				dollartoast.classList.add(settings.transitionOutMobile);
		} else {
			if(settings.transitionOut)
				dollartoast.classList.add(settings.transitionOut);
		}
		var H = dollartoast.parentNode.offsetHeight;
				dollartoast.parentNode.style.height = H+'px';
				dollartoast.style.pointerEvents = 'none';
		
		if(!ISMOBILE || window.innerWidth > MOBILEWIDTH){
			dollartoast.parentNode.style.transitionDelay = '0.2s';
		}

		try {
			var event = new CustomEvent(PLUGIN_NAME+'-closing', {detail: settings, bubbles: true, cancelable: true});
			document.dispatchEvent(event);
		} catch(ex){
			console.warn(ex);
		}

		setTimeout(function() {
			
			dollartoast.parentNode.style.height = '0px';
			dollartoast.parentNode.style.overflow = '';

			setTimeout(function(){
				
				delete that.children[settings.ref];

				dollartoast.parentNode.remove();

				try {
					var event = new CustomEvent(PLUGIN_NAME+'-closed', {detail: settings, bubbles: true, cancelable: true});
					document.dispatchEvent(event);
				} catch(ex){
					console.warn(ex);
				}

				if(typeof settings.onClosed !== 'undefined'){
					settings.onClosed.apply(null, [settings, dollartoast, closedBy]);
				}

			}, 1000);
		}, 200);


		if(typeof settings.onClosing !== 'undefined'){
			settings.onClosing.apply(null, [settings, dollartoast, closedBy]);
		}
	};

	/**
	 * Create and show the Toast
	 * @public
	 * @param {Object} options User settings
	 */
	dollariziToast.show = function (options) {

		var that = this;

		// Merge user options with defaults
		var settings = extend(CONFIG, options || {});
			settings = extend(defaults, settings);
			settings.time = {};

		if(settings.id === null){
			settings.id = generateId(settings.title+settings.message+settings.color);
		}

		if(settings.displayMode === 1 || settings.displayMode == 'once'){
			try {
				if(document.querySelectorAll('.'+PLUGIN_NAME+'#'+settings.id).length > 0){
					return false;
				}
			} catch (exc) {
				console.warn('['+PLUGIN_NAME+'] Could not find an element with this selector: '+'#'+settings.id+'. Try to set an valid id.');
			}
		}

		if(settings.displayMode === 2 || settings.displayMode == 'replace'){
			try {
				forEach(document.querySelectorAll('.'+PLUGIN_NAME+'#'+settings.id), function(element, index) {
					that.hide(settings, element, 'replaced');
				});
			} catch (exc) {
				console.warn('['+PLUGIN_NAME+'] Could not find an element with this selector: '+'#'+settings.id+'. Try to set an valid id.');
			}
		}

		settings.ref = new Date().getTime() + Math.floor((Math.random() * 10000000) + 1);

		dollariziToast.children[settings.ref] = settings;

		var dollarDOM = {
			body: document.querySelector('body'),
			overlay: document.createElement('div'),
			toast: document.createElement('div'),
			toastBody: document.createElement('div'),
			toastTexts: document.createElement('div'),
			toastCapsule: document.createElement('div'),
			cover: document.createElement('div'),
			buttons: document.createElement('div'),
			inputs: document.createElement('div'),
			icon: !settings.iconUrl ? document.createElement('i') : document.createElement('img'),
			wrapper: null
		};

		dollarDOM.toast.setAttribute('data-iziToast-ref', settings.ref);
		dollarDOM.toast.appendChild(dollarDOM.toastBody);
		dollarDOM.toastCapsule.appendChild(dollarDOM.toast);

		// CSS Settings
		(function(){

			dollarDOM.toast.classList.add(PLUGIN_NAME);
			dollarDOM.toast.classList.add(PLUGIN_NAME+'-opening');
			dollarDOM.toastCapsule.classList.add(PLUGIN_NAME+'-capsule');
			dollarDOM.toastBody.classList.add(PLUGIN_NAME + '-body');
			dollarDOM.toastTexts.classList.add(PLUGIN_NAME + '-texts');

			if(ISMOBILE || window.innerWidth <= MOBILEWIDTH){
				if(settings.transitionInMobile)
					dollarDOM.toast.classList.add(settings.transitionInMobile);
			} else {
				if(settings.transitionIn)
					dollarDOM.toast.classList.add(settings.transitionIn);
			}

			if(settings.class){
				var classes = settings.class.split(' ');
				forEach(classes, function (value, index) {
					dollarDOM.toast.classList.add(value);
				});
			}

			if(settings.id){ dollarDOM.toast.id = settings.id; }

			if(settings.rtl){
				dollarDOM.toast.classList.add(PLUGIN_NAME + '-rtl');
				dollarDOM.toast.setAttribute('dir', 'rtl');
			}

			if(settings.layout > 1){ dollarDOM.toast.classList.add(PLUGIN_NAME+'-layout'+settings.layout); }

			if(settings.balloon){ dollarDOM.toast.classList.add(PLUGIN_NAME+'-balloon'); }

			if(settings.maxWidth){
				if( !isNaN(settings.maxWidth) ){
					dollarDOM.toast.style.maxWidth = settings.maxWidth+'px';
				} else {
					dollarDOM.toast.style.maxWidth = settings.maxWidth;
				}
			}

			if(settings.theme !== '' || settings.theme !== 'light') {

				dollarDOM.toast.classList.add(PLUGIN_NAME+'-theme-'+settings.theme);
			}

			if(settings.color) { //#, rgb, rgba, hsl
				
				if( isColor(settings.color) ){
					dollarDOM.toast.style.background = settings.color;
				} else {
					dollarDOM.toast.classList.add(PLUGIN_NAME+'-color-'+settings.color);
				}
			}

			if(settings.backgroundColor) {
				dollarDOM.toast.style.background = settings.backgroundColor;
				if(settings.balloon){
					dollarDOM.toast.style.borderColor = settings.backgroundColor;				
				}
			}
		})();

		// Cover image
		(function(){
			if(settings.image) {
				dollarDOM.cover.classList.add(PLUGIN_NAME + '-cover');
				dollarDOM.cover.style.width = settings.imageWidth + 'px';

				if(isBase64(settings.image.replace(/ /g,''))){
					dollarDOM.cover.style.backgroundImage = 'url(data:image/png;base64,' + settings.image.replace(/ /g,'') + ')';
				} else {
					dollarDOM.cover.style.backgroundImage = 'url(' + settings.image + ')';
				}

				if(settings.rtl){
					dollarDOM.toastBody.style.marginRight = (settings.imageWidth + 10) + 'px';
				} else {
					dollarDOM.toastBody.style.marginLeft = (settings.imageWidth + 10) + 'px';				
				}
				dollarDOM.toast.appendChild(dollarDOM.cover);
			}
		})();

		// Button close
		(function(){
			if(settings.close){
				
				dollarDOM.buttonClose = document.createElement('button');
				dollarDOM.buttonClose.type = 'button';
				dollarDOM.buttonClose.classList.add(PLUGIN_NAME + '-close');
				dollarDOM.buttonClose.addEventListener('click', function (e) {
					var button = e.target;
					that.hide(settings, dollarDOM.toast, 'button');
				});
				dollarDOM.toast.appendChild(dollarDOM.buttonClose);
			} else {
				if(settings.rtl){
					dollarDOM.toast.style.paddingLeft = '18px';
				} else {
					dollarDOM.toast.style.paddingRight = '18px';
				}
			}
		})();

		// Progress Bar & Timeout
		(function(){

			if(settings.progressBar){
				dollarDOM.progressBar = document.createElement('div');
				dollarDOM.progressBarDiv = document.createElement('div');
				dollarDOM.progressBar.classList.add(PLUGIN_NAME + '-progressbar');
				dollarDOM.progressBarDiv.style.background = settings.progressBarColor;
				dollarDOM.progressBar.appendChild(dollarDOM.progressBarDiv);
				dollarDOM.toast.appendChild(dollarDOM.progressBar);
			}

			if(settings.timeout) {

				if(settings.pauseOnHover && !settings.resetOnHover){
					
					dollarDOM.toast.addEventListener('mouseenter', function (e) {
						that.progress(settings, dollarDOM.toast).pause();
					});
					dollarDOM.toast.addEventListener('mouseleave', function (e) {
						that.progress(settings, dollarDOM.toast).resume();
					});
				}

				if(settings.resetOnHover){

					dollarDOM.toast.addEventListener('mouseenter', function (e) {
						that.progress(settings, dollarDOM.toast).reset();
					});
					dollarDOM.toast.addEventListener('mouseleave', function (e) {
						that.progress(settings, dollarDOM.toast).start();
					});
				}
			}
		})();

		// Icon
		(function(){

			if(settings.iconUrl) {

				dollarDOM.icon.setAttribute('class', PLUGIN_NAME + '-icon');
				dollarDOM.icon.setAttribute('src', settings.iconUrl);

			} else if(settings.icon) {
				dollarDOM.icon.setAttribute('class', PLUGIN_NAME + '-icon ' + settings.icon);
				
				if(settings.iconText){
					dollarDOM.icon.appendChild(document.createTextNode(settings.iconText));
				}
				
				if(settings.iconColor){
					dollarDOM.icon.style.color = settings.iconColor;
				}				
			}

			if(settings.icon || settings.iconUrl) {

				if(settings.rtl){
					dollarDOM.toastBody.style.paddingRight = '33px';
				} else {
					dollarDOM.toastBody.style.paddingLeft = '33px';				
				}

				dollarDOM.toastBody.appendChild(dollarDOM.icon);
			}

		})();

		// Title & Message
		(function(){
			if(settings.title.length > 0) {

				dollarDOM.strong = document.createElement('strong');
				dollarDOM.strong.classList.add(PLUGIN_NAME + '-title');
				dollarDOM.strong.appendChild(createFragElem(settings.title));
				dollarDOM.toastTexts.appendChild(dollarDOM.strong);

				if(settings.titleColor) {
					dollarDOM.strong.style.color = settings.titleColor;
				}
				if(settings.titleSize) {
					if( !isNaN(settings.titleSize) ){
						dollarDOM.strong.style.fontSize = settings.titleSize+'px';
					} else {
						dollarDOM.strong.style.fontSize = settings.titleSize;
					}
				}
				if(settings.titleLineHeight) {
					if( !isNaN(settings.titleSize) ){
						dollarDOM.strong.style.lineHeight = settings.titleLineHeight+'px';
					} else {
						dollarDOM.strong.style.lineHeight = settings.titleLineHeight;
					}
				}
			}

			if(settings.message.length > 0) {

				dollarDOM.p = document.createElement('p');
				dollarDOM.p.classList.add(PLUGIN_NAME + '-message');
				dollarDOM.p.appendChild(createFragElem(settings.message));
				dollarDOM.toastTexts.appendChild(dollarDOM.p);

				if(settings.messageColor) {
					dollarDOM.p.style.color = settings.messageColor;
				}
				if(settings.messageSize) {
					if( !isNaN(settings.titleSize) ){
						dollarDOM.p.style.fontSize = settings.messageSize+'px';
					} else {
						dollarDOM.p.style.fontSize = settings.messageSize;
					}
				}
				if(settings.messageLineHeight) {
					
					if( !isNaN(settings.titleSize) ){
						dollarDOM.p.style.lineHeight = settings.messageLineHeight+'px';
					} else {
						dollarDOM.p.style.lineHeight = settings.messageLineHeight;
					}
				}
			}

			if(settings.title.length > 0 && settings.message.length > 0) {
				if(settings.rtl){
					dollarDOM.strong.style.marginLeft = '10px';
				} else if(settings.layout !== 2 && !settings.rtl) {
					dollarDOM.strong.style.marginRight = '10px';	
				}
			}
		})();

		dollarDOM.toastBody.appendChild(dollarDOM.toastTexts);

		// Inputs
		var dollarinputs;
		(function(){
			if(settings.inputs.length > 0) {

				dollarDOM.inputs.classList.add(PLUGIN_NAME + '-inputs');

				forEach(settings.inputs, function (value, index) {
					dollarDOM.inputs.appendChild(createFragElem(value[0]));

					dollarinputs = dollarDOM.inputs.childNodes;

					dollarinputs[index].classList.add(PLUGIN_NAME + '-inputs-child');

					if(value[3]){
						setTimeout(function() {
							dollarinputs[index].focus();
						}, 300);
					}

					dollarinputs[index].addEventListener(value[1], function (e) {
						var ts = value[2];
						return ts(that, dollarDOM.toast, this, e);
					});
				});
				dollarDOM.toastBody.appendChild(dollarDOM.inputs);
			}
		})();

		// Buttons
		(function(){
			if(settings.buttons.length > 0) {

				dollarDOM.buttons.classList.add(PLUGIN_NAME + '-buttons');

				forEach(settings.buttons, function (value, index) {
					dollarDOM.buttons.appendChild(createFragElem(value[0]));

					var dollarbtns = dollarDOM.buttons.childNodes;

					dollarbtns[index].classList.add(PLUGIN_NAME + '-buttons-child');

					if(value[2]){
						setTimeout(function() {
							dollarbtns[index].focus();
						}, 300);
					}

					dollarbtns[index].addEventListener('click', function (e) {
						e.preventDefault();
						var ts = value[1];
						return ts(that, dollarDOM.toast, this, e, dollarinputs);
					});
				});
			}
			dollarDOM.toastBody.appendChild(dollarDOM.buttons);
		})();

		if(settings.message.length > 0 && (settings.inputs.length > 0 || settings.buttons.length > 0)) {
			dollarDOM.p.style.marginBottom = '0';
		}

		if(settings.inputs.length > 0 || settings.buttons.length > 0){
			if(settings.rtl){
				dollarDOM.toastTexts.style.marginLeft = '10px';
			} else {
				dollarDOM.toastTexts.style.marginRight = '10px';
			}
			if(settings.inputs.length > 0 && settings.buttons.length > 0){
				if(settings.rtl){
					dollarDOM.inputs.style.marginLeft = '8px';
				} else {
					dollarDOM.inputs.style.marginRight = '8px';
				}
			}
		}

		// Wrap
		(function(){
			dollarDOM.toastCapsule.style.visibility = 'hidden';
			setTimeout(function() {
				var H = dollarDOM.toast.offsetHeight;
				var style = dollarDOM.toast.currentStyle || window.getComputedStyle(dollarDOM.toast);
				var marginTop = style.marginTop;
					marginTop = marginTop.split('px');
					marginTop = parseInt(marginTop[0]);
				var marginBottom = style.marginBottom;
					marginBottom = marginBottom.split('px');
					marginBottom = parseInt(marginBottom[0]);

				dollarDOM.toastCapsule.style.visibility = '';
				dollarDOM.toastCapsule.style.height = (H+marginBottom+marginTop)+'px';

				setTimeout(function() {
					dollarDOM.toastCapsule.style.height = 'auto';
					if(settings.target){
						dollarDOM.toastCapsule.style.overflow = 'visible';
					}
				}, 500);

				if(settings.timeout) {
					that.progress(settings, dollarDOM.toast).start();
				}
			}, 100);
		})();

		// Target
		(function(){
			var position = settings.position;

			if(settings.target){

				dollarDOM.wrapper = document.querySelector(settings.target);
				dollarDOM.wrapper.classList.add(PLUGIN_NAME + '-target');

				if(settings.targetFirst) {
					dollarDOM.wrapper.insertBefore(dollarDOM.toastCapsule, dollarDOM.wrapper.firstChild);
				} else {
					dollarDOM.wrapper.appendChild(dollarDOM.toastCapsule);
				}

			} else {

				if( POSITIONS.indexOf(settings.position) == -1 ){
					console.warn('['+PLUGIN_NAME+'] Incorrect position.\nIt can be > ' + POSITIONS);
					return;
				}

				if(ISMOBILE || window.innerWidth <= MOBILEWIDTH){
					if(settings.position == 'bottomLeft' || settings.position == 'bottomRight' || settings.position == 'bottomCenter'){
						position = PLUGIN_NAME+'-wrapper-bottomCenter';
					}
					else if(settings.position == 'topLeft' || settings.position == 'topRight' || settings.position == 'topCenter'){
						position = PLUGIN_NAME+'-wrapper-topCenter';
					}
					else {
						position = PLUGIN_NAME+'-wrapper-center';
					}
				} else {
					position = PLUGIN_NAME+'-wrapper-'+position;
				}
				dollarDOM.wrapper = document.querySelector('.' + PLUGIN_NAME + '-wrapper.'+position);

				if(!dollarDOM.wrapper) {
					dollarDOM.wrapper = document.createElement('div');
					dollarDOM.wrapper.classList.add(PLUGIN_NAME + '-wrapper');
					dollarDOM.wrapper.classList.add(position);
					document.body.appendChild(dollarDOM.wrapper);
				}
				if(settings.position == 'topLeft' || settings.position == 'topCenter' || settings.position == 'topRight'){
					dollarDOM.wrapper.insertBefore(dollarDOM.toastCapsule, dollarDOM.wrapper.firstChild);
				} else {
					dollarDOM.wrapper.appendChild(dollarDOM.toastCapsule);
				}
			}

			if(!isNaN(settings.zindex)) {
				dollarDOM.wrapper.style.zIndex = settings.zindex;
			} else {
				console.warn('['+PLUGIN_NAME+'] Invalid zIndex.');
			}
		})();

		// Overlay
		(function(){

			if(settings.overlay) {

				if( document.querySelector('.'+PLUGIN_NAME+'-overlay.fadeIn') !== null ){

					dollarDOM.overlay = document.querySelector('.'+PLUGIN_NAME+'-overlay');
					dollarDOM.overlay.setAttribute('data-iziToast-ref', dollarDOM.overlay.getAttribute('data-iziToast-ref') + ',' + settings.ref);

					if(!isNaN(settings.zindex) && settings.zindex !== null) {
						dollarDOM.overlay.style.zIndex = settings.zindex-1;
					}

				} else {

					dollarDOM.overlay.classList.add(PLUGIN_NAME+'-overlay');
					dollarDOM.overlay.classList.add('fadeIn');
					dollarDOM.overlay.style.background = settings.overlayColor;
					dollarDOM.overlay.setAttribute('data-iziToast-ref', settings.ref);
					if(!isNaN(settings.zindex) && settings.zindex !== null) {
						dollarDOM.overlay.style.zIndex = settings.zindex-1;
					}
					document.querySelector('body').appendChild(dollarDOM.overlay);
				}

				if(settings.overlayClose) {

					dollarDOM.overlay.removeEventListener('click', {});
					dollarDOM.overlay.addEventListener('click', function (e) {
						that.hide(settings, dollarDOM.toast, 'overlay');
					});
				} else {
					dollarDOM.overlay.removeEventListener('click', {});
				}
			}			
		})();

		// Inside animations
		(function(){
			if(settings.animateInside){
				dollarDOM.toast.classList.add(PLUGIN_NAME+'-animateInside');
			
				var animationTimes = [200, 100, 300];
				if(settings.transitionIn == 'bounceInLeft' || settings.transitionIn == 'bounceInRight'){
					animationTimes = [400, 200, 400];
				}

				if(settings.title.length > 0) {
					setTimeout(function(){
						dollarDOM.strong.classList.add('slideIn');
					}, animationTimes[0]);
				}

				if(settings.message.length > 0) {
					setTimeout(function(){
						dollarDOM.p.classList.add('slideIn');
					}, animationTimes[1]);
				}

				if(settings.icon || settings.iconUrl) {
					setTimeout(function(){
						dollarDOM.icon.classList.add('revealIn');
					}, animationTimes[2]);
				}

				var counter = 150;
				if(settings.buttons.length > 0 && dollarDOM.buttons) {

					setTimeout(function(){

						forEach(dollarDOM.buttons.childNodes, function(element, index) {

							setTimeout(function(){
								element.classList.add('revealIn');
							}, counter);
							counter = counter + 150;
						});

					}, settings.inputs.length > 0 ? 150 : 0);
				}

				if(settings.inputs.length > 0 && dollarDOM.inputs) {
					counter = 150;
					forEach(dollarDOM.inputs.childNodes, function(element, index) {

						setTimeout(function(){
							element.classList.add('revealIn');
						}, counter);
						counter = counter + 150;
					});
				}
			}
		})();

		settings.onOpening.apply(null, [settings, dollarDOM.toast]);

		try {
			var event = new CustomEvent(PLUGIN_NAME + '-opening', {detail: settings, bubbles: true, cancelable: true});
			document.dispatchEvent(event);
		} catch(ex){
			console.warn(ex);
		}

		setTimeout(function() {

			dollarDOM.toast.classList.remove(PLUGIN_NAME+'-opening');
			dollarDOM.toast.classList.add(PLUGIN_NAME+'-opened');

			try {
				var event = new CustomEvent(PLUGIN_NAME + '-opened', {detail: settings, bubbles: true, cancelable: true});
				document.dispatchEvent(event);
			} catch(ex){
				console.warn(ex);
			}

			settings.onOpened.apply(null, [settings, dollarDOM.toast]);
		}, 1000);

		if(settings.drag){

			if(ACCEPTSTOUCH) {

			    dollarDOM.toast.addEventListener('touchstart', function(e) {
			        drag.startMoving(this, that, settings, e);
			    }, false);

			    dollarDOM.toast.addEventListener('touchend', function(e) {
			        drag.stopMoving(this, e);
			    }, false);
			} else {

			    dollarDOM.toast.addEventListener('mousedown', function(e) {
			    	e.preventDefault();
			        drag.startMoving(this, that, settings, e);
			    }, false);

			    dollarDOM.toast.addEventListener('mouseup', function(e) {
			    	e.preventDefault();
			        drag.stopMoving(this, e);
			    }, false);
			}
		}

		if(settings.closeOnEscape) {

			document.addEventListener('keyup', function (evt) {
				evt = evt || window.event;
				if(evt.keyCode == 27) {
				    that.hide(settings, dollarDOM.toast, 'esc');
				}
			});
		}

		if(settings.closeOnClick) {
			dollarDOM.toast.addEventListener('click', function (evt) {
				that.hide(settings, dollarDOM.toast, 'toast');
			});
		}

		that.toast = dollarDOM.toast;		
	};
	return dollariziToast;
});