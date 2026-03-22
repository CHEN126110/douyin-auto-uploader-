layui.define(['table', 'jquery', 'element'], function (exports) {
	"use strict";

	var MOD_NAME = 'menu',
		dollar = layui.jquery,
		element = layui.element;

	var menu = function (opt) {
		this.option = opt;
	};

	menu.prototype.render = function (opt) {

		var option = {
			elem: opt.elem,
			async: opt.async || true,
			parseData: opt.parseData,
			url: opt.url,
			method: opt.method ? opt.method : "GET",
			defaultOpen: opt.defaultOpen,
			defaultSelect: opt.defaultSelect,
			control: opt.control,
			controlWidth: opt.controlWidth ? opt.controlWidth : "auto",
			defaultMenu: opt.defaultMenu || 0,
			accordion: opt.accordion,
			height: opt.height || "100%",
			theme: opt.theme || "dark-theme",
			data: opt.data ? opt.data : [],
			change: opt.change ? opt.change : function () { },
			done: opt.done ? opt.done : function () { }
		}

		var tempDone = option.done;

		option.done = function () {
			if (option.control) {
				rationalizeHeaderControlWidthAuto(option);
			}
			tempDone();
		}

		if (option.async) {
			if (option.method === "GET") {
				getData(option.url).then(function (data) {
					option.data = data;
					renderMenu(option);
				});
			} else {
				postData(option.url).then(function (data) {
					option.data = data;
					renderMenu(option);
				});
			}
		} else {
			window.setTimeout(function () { renderMenu(option); }, 500);
		}

		dollar("#" + opt.elem).height(option.height)

		setTimeout(function () {
			dollar("#" + opt.control + " .control").on("mousewheel DOMMouseScroll", function (event) {

				var delta = (event.originalEvent.wheelDelta && (event.originalEvent.wheelDelta > 0 ? 1 : -1)) || // chrome & ie
					(event.originalEvent.detail && (event.originalEvent.detail > 0 ? -1 : 1)); // firefox

				if (delta > 0) {
					for (var num = 1; num < 20; num++) {
						setTimeout(function () {
							if (dollar("#" + opt.control + " .control ul").css('left').replace("px", "") < 0) {
								dollar("#" + opt.control + " .control ul").css("left", "+=2px");
							}
						}, 10)
					}
				} else if (delta < 0) {
					if (((Number)(dollar("#" + opt.control + " .control ul").css("left").replace("px", "")) + (dollar("#" + opt.control + " .control ul").width() - dollar("#" + opt.control + " .control").width())) > 0) {
						for (var num = 1; num < 20; num++) {
							setTimeout(function () {
								dollar("#" + opt.control + " .control ul").css("left", "-=2px");
							}, 10)
						}
					}
				}
			});
		}, 1000)

		return new menu(option);
	}

	menu.prototype.cache = function () {
		return this.option.data;
	}

	menu.prototype.click = function (clickEvent) {
		var _this = this;
		dollar("body").on("click", "#" + _this.option.elem + " .site-demo-active", function () {
			var dom = dollar(this);
			var data = {
				menuId: dom.attr("menu-id"),
				menuTitle: dom.attr("menu-title"),
				menuPath: dom.attr("menu-title"),
				menuIcon: dom.attr("menu-icon"),
				menuUrl: dom.attr("menu-url"),
				menuType: dom.attr("menu-type"),
				menuOpenType: dom.attr("menu-open-type")
			};
			var doms = hash(dom);
			if (doms != null) {
				if (doms.text() != '') {
					data['menuPath'] = doms.find("span").text() + " / " + data['menuPath'];
				}
			}
			if (doms != null) {
				var domss = hash(doms);
				if (domss != null) {
					if (domss.text() != '') {
						data['menuPath'] = domss.find("span").text() + " / " + data['menuPath'];
					}
				}
			}
			if (domss != null) {
				var domsss = hash(domss);
				if (domsss != null) {
					if (domsss.text() != '') {
						data['menuPath'] = domsss.find("span").text() + " / " + data['menuPath'];
					}
				}
			}
			if (dollar("#" + _this.option.elem).is(".pear-nav-mini")) {
				if (_this.option.accordion) {
					activeMenus = dollar(this).parent().parent().parent().children("a");
				} else {
					activeMenus.push(dollar(this).parent().parent().parent().children("a"));
				}
			}
			clickEvent(dom, data);
		})
	}

	function hash(dom) {
		var d = dom.parent().parent().prev();
		if (d.prop("tagName") === "UL") {
			return null;
		}
		return d;
	}

	menu.prototype.skin = function (skin) {
		var menu = dollar(".pear-nav-tree[lay-filter='" + this.option.elem + "']").parent();
		menu.removeClass("dark-theme");
		menu.removeClass("light-theme");
		menu.addClass(skin);
	}

	menu.prototype.selectItem = function (pearId) {
		if (this.option.control != false) {
			dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents(".layui-side-scroll ").find("ul").css({
				display: "none"
			});
			dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents(".layui-side-scroll ").find(".layui-this").removeClass(
				"layui-this");
			dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents("ul").css({
				display: "block"
			});
			var controlId = dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents("ul").attr("pear-id");
			if (controlId != undefined) {
				dollar("#" + this.option.control).find(".layui-this").removeClass("layui-this");
				dollar("#" + this.option.control).find("[pear-id='" + controlId + "']").addClass("layui-this");
			}
		}

		dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents(".pear-nav-tree").find(".layui-this").removeClass(
			"layui-this");
		if (!dollar("#" + this.option.elem).is(".pear-nav-mini")) {
			var openEle = null;
			var openEleHeight = 0;
			dollar(dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parents('.layui-nav-child').get().reverse()).each(function () {
				if (!dollar(this).parent().is('.layui-nav-itemed')) {
					if (openEleHeight == 0) {
						openEle = dollar(this);
					} else {
						dollar(this).parent().addClass('layui-nav-itemed');
						dollar(this).css({
							height: 'auto',
						});
					}
					openEleHeight += dollar(this).children("dd").length * 48;
				}
			});
			if (this.option.accordion) {
				if (openEleHeight > 0) {
					var currentDom = openEle.parent().siblings('.layui-nav-itemed').children(".layui-nav-child");
					currentDom.animate({
						height: "0px"
					}, 240, function () {
						currentDom.css({
							height: "auto"
						});
						dollar(this).parent().removeClass("layui-nav-itemed");
						dollar(this).find('.layui-nav-itemed').removeClass("layui-nav-itemed");
					});
				}
			}
			if (openEleHeight > 0) {
				openEle.parent().addClass("layui-nav-itemed");
				openEle.height(0);
				openEle.animate({
					height: openEleHeight + "px"
				}, 240, function () {
					dollar(this).css({ height: 'auto' });
				});
			}
		}
		dollar("#" + this.option.elem + " a[menu-id='" + pearId + "']").parent().addClass("layui-this");
	}

	var activeMenus;
	menu.prototype.collapse = function (time) {
		var elem = this.option.elem;
		var config = this.option;
		if (dollar("#" + this.option.elem).is(".pear-nav-mini")) {
			dollar.each(activeMenus, function (i, item) {
				dollar("#" + elem + " a[menu-id='" + dollar(this).attr("menu-id") + "']").parent().addClass("layui-nav-itemed");
			})
			dollar("#" + this.option.elem).removeClass("pear-nav-mini");
			dollar("#" + this.option.elem).animate({
				width: "220px"
			}, 180);
			isHoverMenu(false, config);
			var that = this;
			dollar("#" + this.option.elem)
				.promise()
				.done(function () {
					if (that.option.control) {
						rationalizeHeaderControlWidth(that.option);
					}
				})
		} else {
			activeMenus = dollar("#" + this.option.elem).find(".layui-nav-itemed>a");
			dollar("#" + this.option.elem).find(".layui-nav-itemed").removeClass("layui-nav-itemed");
			dollar("#" + this.option.elem).addClass("pear-nav-mini");
			dollar("#" + this.option.elem).animate({
				width: "60px"
			}, 400);
			var that = this;
			dollar("#" + this.option.elem)
				.promise()
				.done(function () {
					isHoverMenu(true, config);
					if (that.option.control) {
						rationalizeHeaderControlWidth(that.option);
					}
				})
		}
	}

	function getData(url) {
		var defer = dollar.Deferred();
		var symbol = url.indexOf('?') !== -1 ? '&' : '?';
		dollar.get(url + symbol + "fresh=" + Math.random(), function (result) {
			defer.resolve(result)
		});
		return defer.promise();
	}

	function postData(url) {
		var defer = dollar.Deferred();
		var symbol = url.indexOf('?') !== -1 ? '&' : '?';
		dollar.post(url + symbol + "fresh=" + Math.random(), function (result) {
			defer.resolve(result)
		}, "json");
		return defer.promise();
	}

	function renderMenu(option) {
		if (option.parseData != false) {
			option.parseData(option.data);
		}
		if (option.data.length > 0) {
			if (option.control != false) {
				createMenuAndControl(option);
			} else {
				createMenu(option);
			}
		}
		element.init();
		option.done();
	}

	function createMenu(option) {
		var menuHtml = '<div style="height:100%!important;" class="pear-side-scroll layui-side-scroll ' + option.theme + '"><ul lay-filter="' + option.elem +
			'" class="layui-nav arrow   pear-menu layui-nav-tree pear-nav-tree" ' + (option.accordion ? "lay-accordion" : "") + '>'
		dollar.each(option.data, function (i, item) {
			var content = '<li class="layui-nav-item" >';
			if (i == option.defaultOpen) {
				content = '<li class="layui-nav-item layui-nav-itemed" >';
			}
			var href = "javascript:;";
			var target = "";
			var className = "site-demo-active"
			if (item.openType == "_blank" && item.type == 1) {
				href = item.href;
				target = "target='_blank'";
				className = "";
			}
			if (item.type == 0) {
				// 创 建 目 录 结 构
				content += '<a  href="javascript:;" menu-type="' + item.type + '" menu-id="' + item.id + '" href="' + href +
					'" ' + target + '><i class="' + item.icon + '"></i><span>' + item.title +
					'</span></a>';
			} else if (item.type == 1) {
				content += '<a class="' + className + '" menu-type="' + item.type + '" menu-open-type="' + item.openType + '"  menu-url="' + item.href + '" menu-id="' +
					item.id +
					'" menu-title="' + item.title + '"  href="' + href + '"  ' + target + '><i class="' + item.icon +
					'"></i><span>' + item.title + '</span></a>';
			}
			// 调 用 递 归 方 法 加 载 无 限 层 级 的 子 菜 单 
			content += loadchild(item);
			// 结 束 一 个 根 菜 单 项
			content += '</li>';
			menuHtml += content;
		});
		// 结 束 菜 单 结 构 的 初 始 化
		menuHtml += "</ul></div>";
		// 将 菜 单 拼 接 到 初 始 化 容 器 中
		dollar("#" + option.elem).html(menuHtml);
	}

	function createMenuAndControl(option) {
		var control = '<div style="width: ' + option.controlWidth + 'px;white-space: nowrap;overflow-x: scroll;overflow: hidden;" class="control"><ul class="layui-nav pear-nav-control pc layui-hide-xs" style="width: fit-content;">';
		var controlPe = '<ul class="layui-nav pear-nav-control layui-hide-sm">';
		// 声 明 头 部
		var menu = '<div class="layui-side-scroll ' + option.theme + '">'
		// 开 启 同 步 操 作
		var index = 0;
		var controlItemPe = '<dl class="layui-nav-child">';
		dollar.each(option.data, function (i, item) {
			var menuItem = '';
			var controlItem = '';
			if (i === option.defaultMenu) {
				controlItem = '<li pear-href="' + item.href + '" pear-title="' + item.title + '" pear-id="' + item.id +
					'" class="layui-this layui-nav-item"><a href="#">' + item.title + '</a></li>';
				menuItem = '<ul  pear-id="' + item.id + '" lay-filter="' + option.elem +
					'" class="layui-nav arrow layui-nav-tree pear-nav-tree">';

				controlPe += '<li class="layui-nav-item"><a class="pe-title" href="javascript:;" >' + item.title + '</a>';

				controlItemPe += '<dd  pear-href="' + item.href + '" pear-title="' + item.title + '" pear-id="' + item.id +
					'"><a href="javascript:void(0);">' + item.title + '</a></dd>';
			} else {

				controlItem = '<li  pear-href="' + item.href + '" pear-title="' + item.title + '" pear-id="' + item.id +
					'" class="layui-nav-item"><a href="#">' + item.title + '</a></li>';

				menuItem = '<ul style="display:none" pear-id="' + item.id + '" lay-filter="' + option.elem +
					'" class="layui-nav arrow layui-nav-tree pear-nav-tree">';

				controlItemPe += '<dd pear-href="' + item.href + '" pear-title="' + item.title + '" pear-id="' + item.id +
					'"><a href="javascript:void(0);">' + item.title + '</a></dd>';

			}
			index++;
			dollar.each(item.children, function (i, note) {
				// 创 建 每 一 个 菜 单 项
				var content = '<li class="layui-nav-item" >';
				var href = "javascript:;";
				var target = "";
				var className = "site-demo-active";
				if (note.openType == "_blank" && note.type == 1) {
					href = note.href;
					target = "target='_blank'";
					className = "";
				}
				// 判 断 菜 单 类 型 0 是 不可跳转的目录 1 是 可 点 击 跳 转 的 菜 单
				if (note.type == 0) {
					// 创 建 目 录 结 构
					content += '<a  href="' + href + '" ' + target + ' menu-type="' + note.type + '" menu-id="' + note.id +
						'" ><i class="' + note.icon + '"></i><span>' + note.title +
						'</span></a>';
				} else if (note.type == 1) {
					// 创 建 菜 单 结 构
					content += '<a ' + target + ' class="' + className + '" menu-open-type="' + note.openType + '" menu-type="' + note.type + '" menu-url="' + note.href +
						'" menu-id="' + note.id +
						'" menu-title="' + note.title + '" href="' + href + '"><i class="' + note.icon +
						'"></i><span>' + note.title + '</span></a>';
				}
				content += loadchild(note);
				content += '</li>';
				menuItem += content;
			})
			menu += menuItem + '</ul>';
			control += controlItem;
		})
		controlItemPe += "</li></dl></ul>"
		controlPe += controlItemPe;
		dollar("#" + option.control).html(control + "</div>");
		dollar("#" + option.control).append(controlPe);
		dollar("#" + option.elem).html(menu);
		dollar("#" + option.control + " .pear-nav-control").on("click", "[pear-id]", function () {
			dollar("#" + option.elem).find(".pear-nav-tree").css({
				display: 'none'
			});
			dollar("#" + option.elem).find(".pear-nav-tree[pear-id='" + dollar(this).attr("pear-id") + "']").css({
				display: 'block'
			});
			dollar("#" + option.control).find(".pe-title").html(dollar(this).attr("pear-title"));
			dollar("#" + option.control).find("")
			option.change(dollar(this).attr("pear-id"), dollar(this).attr("pear-title"), dollar(this).attr("pear-href"))
		})
	}

	/** 加载子菜单 (递归)*/
	function loadchild(obj) {
		// 判 单 是 否 是 菜 单, 如 果 是 菜 单 直 接 返 回
		if (obj.type == 1) {
			return "";
		}
		// 创 建 子 菜 单 结 构
		var content = '<dl class="layui-nav-child">';
		// 如 果 嵌 套 不 等 于 空 
		if (obj.children != null && obj.children.length > 0) {
			// 遍 历 子 项 目
			dollar.each(obj.children, function (i, note) {
				// 创 建 子 项 结 构
				content += '<dd>';
				var href = "javascript:;";
				var target = "";
				var className = "site-demo-active";
				if (note.openType == "_blank" && note.type == 1) {
					href = note.href;
					target = "target='_blank'";
					className = "";
				}
				// 判 断 子 项 类 型
				if (note.type == 0) {
					// 创 建 目 录 结 构
					content += '<a ' + target + '  href="' + href + '" menu-type="' + note.type + '" menu-id="' + note.id +
						'"><i class="' + note.icon + '"></i><span>' + note.title + '</span></a>';
				} else if (note.type == 1) {
					// 创 建 菜 单 结 构
					content += '<a ' + target + ' class="' + className + '" menu-open-type="' + note.openType + '" menu-type="' + note.type + '" menu-url="' + note.href +
						'" menu-id="' + note.id + '" menu-title="' + note.title + '" menu-icon="' + note.icon + '" href="' + href +
						'" ><i class="' + note.icon + '"></i><span>' + note.title + '</span></a>';
				}
				// 加 载 子 项 目 录
				content += loadchild(note);
				// 结 束 当 前 子 菜 单
				content += '</dd>';
			});
			// 封 装
		} else {
			content += '<dd style="background-color: transparent!important;"><a style="background-color: transparent!important;margin-left: 26px">目录为空</a></dd>';
		}
		content += '</dl>';
		return content;
	}

	/** 二 级 悬 浮 菜 单*/
	function isHoverMenu(b, option) {
		if (b) {
			var navItem = "#" + option.elem + ".pear-nav-mini .layui-nav-item";
			var navChildDl = navItem + " .layui-nav-child>dl";
			var navChildDd = navItem + " .layui-nav-child>dd";

			dollar(navItem + "," + navChildDd).mouseenter(function () {
				var _this = dollar(this);
				_this.siblings().find(".layui-nav-child")
					.removeClass("layui-nav-hover").css({
						left: 0,
						top: 0
					});
				_this.children(".layui-nav-child").addClass("layui-nav-hover");
				var height = dollar(window).height();
				var topLength = _this.offset().top;
				var thisHeight = _this.children(".layui-nav-child").height();
				if ((thisHeight + topLength) > height) {
					topLength = height - thisHeight - 10;
				}
				var left = _this.offset().left + 60;
				if (!_this.hasClass("layui-nav-item")) {
					left = _this.offset().left + _this.width();
				}
				var isQWebEngineView = navigator.userAgent.indexOf('QtWebEngine') !== -1 ||
										typeof window.qwebchannel !== 'undefined' || typeof window.qt !== 'undefined';
				var child = _this.children(".layui-nav-child");
				if (isQWebEngineView) {
					child.css({
						position: 'fixed',
						transform: 'translate(' + left + 'px, ' + topLength + 'px)'
					});
				} else {
					child.offset({
						top: topLength,
						left: left
					});
				}
			});

			dollar(navItem + "," + navChildDl).mouseleave(function () {
				var _this = dollar(this);
				var isQWebEngineView = navigator.userAgent.indexOf('QtWebEngine') !== -1 ||
										typeof window.qwebchannel !== 'undefined' || typeof window.qt !== 'undefined';
				var child = _this.closest('.layui-nav-item').find(".layui-nav-child");
				child.removeClass("layui-nav-hover");
				if (isQWebEngineView) {
					child.css({ transform: 'none' });
				} else {
					child.css({ left: 0, top: 0 });
				}
			});

		} else {
			dollar("#" + option.elem + " .layui-nav-item").off('mouseenter').unbind('mouseleave');
			dollar("#" + option.elem + " dd").off('mouseenter').unbind('mouseleave');
		}
	}

	function rationalizeHeaderControlWidth(option) {
		var dollarheaderControl = dollar("#" + option.control);
		var dollarnextEl = dollarheaderControl.next();
		var rationalizeWidth;
		if (dollarnextEl.length) {
			rationalizeWidth = dollarnextEl.position().left - dollarheaderControl.position().left;
		} else {
			rationalizeWidth = dollarheaderControl.parent().innerWidth() - dollarheaderControl.position().left;
		}

		if (option.controlWidth && rationalizeWidth >= option.controlWidth) {
			rationalizeWidth = option.controlWidth;
		}
		dollar("#" + option.control + " .control").css({ "width": rationalizeWidth, "transition": "width .15s" });
	}

	function rationalizeHeaderControlWidthAuto(option) {
		dollar(window).on('resize', function () {
			rationalizeHeaderControlWidth(option);
		})
		dollar(document).ready(function () {
			setTimeout(() => {
				rationalizeHeaderControlWidth(option);
			}, 1000);
		});
	}

	exports(MOD_NAME, new menu());
})
