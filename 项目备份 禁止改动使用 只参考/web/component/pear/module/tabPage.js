layui.define(['jquery', 'element', 'dropdown'], function (exports) {
	"use strict";

	var MOD_NAME = 'tabPage',
		dollar = layui.jquery,
		dropdown = layui.dropdown,
		element = layui.element;

	var tabPage = function (opt) {
		this.option = opt;
	};

	var tabData = new Array();
	var tabDataCurrent = 0;
	var contextTabDOM;

	tabPage.prototype.render = function (opt) {

		var option = {
			elem: opt.elem,
			data: opt.data,
			index: opt.index,
			tool: opt.tool || true,
			roll: opt.roll || true,
			success: opt.success ? opt.success : function (id) { },
			session: opt.session ? opt.session : false,
			preload: opt.preload ? opt.preload : false,
			height: opt.height || "100%",
			width: opt.width || "100%",
			closeEvent: opt.closeEvent,
			tabMax: opt.tabMax,
		}

		if (option.session) {
			if (sessionStorage.getItem(option.elem + "-pear-tab-page-data") != null) {
				tabData = JSON.parse(sessionStorage.getItem(option.elem + "-pear-tab-page-data"));
				option.data = JSON.parse(sessionStorage.getItem(option.elem + "-pear-tab-page-data"));
				tabDataCurrent = sessionStorage.getItem(option.elem + "-pear-tab-page-data-current");
				tabData.forEach(function (item, index) {
					if (item.id == tabDataCurrent) {
						option.index = index;
					}
				})
			} else {
				tabData = opt.data;
			}
		}

		var lastIndex;
		var tab = createTab(option);
		dollar("#" + option.elem).html(tab);
		dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-prev").click(function () {
			rollPage("left", option);
		})
		dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-next").click(function () {
			rollPage("right", option);
		})
		element.init();

		dollar("#" + option.elem).width(opt.width);
		dollar("#" + option.elem).height(opt.height);
		dollar("#" + option.elem).css({
			position: "relative"
		});

		closeEvent(option);

		option.success(sessionStorage.getItem(option.elem + "-pear-tab-page-data-current"));

		dropdown.render({
			elem: `#dollar{option.elem} .layui-tab-control > .layui-icon-down`,
			trigger: 'hover',
			data: [{
				title: '关 闭 当 前',
				id: 1
			}, {
				title: '关 闭 其 他',
				id: 2
			}, {
				title: '关 闭 全 部',
				id: 3
			}],
			click: function (obj) {

				const id = obj.id;

				if (id === 1) {
					var currentTab = dollar(".layui-tab[lay-filter='" + option.elem +
						"'] .layui-tab-title .layui-this");
					if (currentTab.find("span").is(".able-close")) {
						var currentId = currentTab.attr("lay-id");
						tabDelete(option.elem, currentId, option.closeEvent, option);
					} else {
						layer.msg("当前页面不允许关闭", {
							icon: 3,
							time: 1000
						})
					}
				} else if (id === 2) {
					var currentId = dollar(".layui-tab[lay-filter='" + option.elem +
						"'] .layui-tab-title .layui-this").attr("lay-id");
					var tabtitle = dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title li");
					dollar.each(tabtitle, function (i) {
						if (dollar(this).attr("lay-id") != currentId) {
							if (dollar(this).find("span").is(".able-close")) {
								tabDelete(option.elem, dollar(this).attr("lay-id"), option.closeEvent,
									option);
							}
						}
					})
				} else {
					var currentId = dollar(".layui-tab[lay-filter='" + option.elem +
						"'] .layui-tab-title .layui-this").attr("lay-id");
					var tabtitle = dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title li");
					dollar.each(tabtitle, function (i) {
						if (dollar(this).find("span").is(".able-close")) {
							tabDelete(option.elem, dollar(this).attr("lay-id"), option.closeEvent, option);
						}
					})
				}

			}
		})

		dollar("body .layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title").on("contextmenu", "li",
			function (e) {
				var top = e.clientY;
				var left = e.clientX;
				var menuWidth = 100;
				var menu = `<ul>
								<li class='item' id='dollar{option.elem}closeThis'>关闭当前</li>
								<li class='item' id='dollar{option.elem}closeOther'>关闭其他</li>
								<li class='item' id='dollar{option.elem}closeAll'>关闭所有</li>
							</ul>`;

				contextTabDOM = dollar(this);
				var isOutsideBounds = (left + menuWidth) > dollar(window).width();
				if (isOutsideBounds) {
					left = dollar(window).width() - menuWidth;
				}

				layer.open({
					type: 1,
					title: false,
					shade: false,
					skin: 'pear-tab-page-menu',
					closeBtn: false,
					area: [menuWidth + 'px', '108px'],
					fixed: true,
					anim: false,
					isOutAnim: false,
					offset: [top, left],
					content: menu,
					success: function (layero, index) {
						layer.close(lastIndex);
						lastIndex = index;
						menuEvent(option, index);
						var timer;
						dollar(layero).on('mouseout', function () {
							timer = setTimeout(function () {
								layer.close(index);
							}, 30)
						});

						dollar(layero).on('mouseover', function () {
							clearTimeout(timer);
						});

						dollar(layero).on('contextmenu', function () {
							return false;
						})
					}
				});
				return false;
			})

		mousewheelAndTouchmoveHandler(option)
		return new tabPage(option);
	}

	tabPage.prototype.click = function (callback) {
		var option = this.option;
		var elem = this.option.elem;
		element.on('tab(' + this.option.elem + ')', function (data) {
			var id = dollar("#" + elem + " .layui-tab-title .layui-this").attr("lay-id");
			sessionStorage.setItem(option.elem + "-pear-tab-page-data-current", id);
			callback(id);
		});
	}

	tabPage.prototype.positionTab = function () {
		var dollartabTitle = dollar('.layui-tab[lay-filter=' + this.option.elem + ']  .layui-tab-title');
		var autoLeft = 0;
		dollartabTitle.children("li").each(function () {
			if (dollar(this).hasClass('layui-this')) {
				return false;
			} else {
				autoLeft += dollar(this).outerWidth();
			}
		});
		dollartabTitle.animate({
			scrollLeft: autoLeft - dollartabTitle.width() / 3
		}, 200);
	}

	tabPage.prototype.clear = function () {
		sessionStorage.removeItem(this.option.elem + "-pear-tab-page-data");
		sessionStorage.removeItem(this.option.elem + "-pear-tab-page-data-current");
	}

	tabPage.prototype.changeTabTitleById = function (id, title) {
		var currentTab = dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-title [lay-id='" + id + "'] .title");
		currentTab.html(title);
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 删除指定选项卡
	 * 
	 * @param id 编号
	 */
	tabPage.prototype.removeTab = function (id) {
		var elem = this.option.elem;
		if (id != undefined) {
			var currentTab = dollar(".layui-tab[lay-filter='" + elem + "'] .layui-tab-title [lay-id='" + id + "']");
			if (currentTab.find("span").is(".able-close")) {
				tabDelete(elem, id, () => { });
			}
		} else {
			var tabtitle = dollar(".layui-tab[lay-filter='" + elem + "'] .layui-tab-title li");
			dollar.each(tabtitle, function () {
				if (dollar(this).find("span").is(".able-close")) {
					tabDelete(elem, dollar(this).attr("lay-id"), () => { });
				}
			})
		}
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 删除其他选项卡
	 */
	tabPage.prototype.removeOtherTab = function () {
		var elem = this.option.elem;
		var currentId = dollar(".layui-tab[lay-filter='" + elem + "'] .layui-tab-title .layui-this").attr("lay-id");
		var tabtitle = dollar(".layui-tab[lay-filter='" + elem + "'] .layui-tab-title li");
		dollar.each(tabtitle, function () {
			if (dollar(this).attr("lay-id") != currentId) {
				if (dollar(this).find("span").is(".able-close")) {
					tabDelete(elem, dollar(this).attr("lay-id"), () => { });
				}
			}
		})
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 删除选中选项卡
	 */
	tabPage.prototype.removeCurrentTab = function () {
		var currentTab = dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-title .layui-this");
		if (currentTab.find("span").is(".able-close")) {
			var currentId = currentTab.attr("lay-id");
			tabDelete(this.option.elem, currentId, () => { });
		}
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 切换选项卡
	 * 
	 * @param opt 内容
	 */
	tabPage.prototype.changePage = function (opt) {

		var title = `<span class="pear-tab-page-active"></span>
					 <span class="dollar{opt.close ? 'able-close' : 'disable-close'} title">dollar{opt.title}</span>
					 <i class="layui-icon layui-unselect layui-tab-close">ဆ</i>`;

		if (dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-title li[lay-id]").length <=
			0) {

			var that = this;

			if (opt.type === "_iframe") {

				element.tabAdd(this.option.elem, {
					id: opt.id,
					title: title,
					content: `<iframe id="dollar{opt.id}" type="dollar{opt.type}" data-frameid="dollar{opt.id}" scrolling="auto" frameborder="0" src="dollar{opt.url}" style="width:100%;height:100%;" allowfullscreen="true"></iframe>`
				});

			} else {

				dollar.ajax({
					url: opt.url,
					type: 'get',
					dataType: 'html',
					async: false,
					success: function (data) {
						element.tabAdd(that.option.elem, {
							id: opt.id,
							title: title,
							content: `<div id="dollar{opt.id}" type="dollar{opt.type}" data-frameid="dollar{opt.id}" src="dollar{opt.url}">dollar{data}</div>`,
						});
					},
					error: function (xhr, textstatus, thrown) {
						return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
					}
				});
			}

			tabData.push(opt);
			sessionStorage.setItem(that.option.elem + "-pear-tab-page-data", JSON.stringify(tabData));
			sessionStorage.setItem(that.option.elem + "-pear-tab-page-data-current", opt.id);

		} else {

			var isData = false;
			dollar.each(dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-title li[lay-id]"),
				function () {
					if (dollar(this).attr("lay-id") == opt.id) {
						isData = true;
					}
				})

			if (isData == false) {

				if (this.option.tabMax != false) {
					if (dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-title li[lay-id]")
						.length >= this.option.tabMax) {
						layer.msg("最多打开" + this.option.tabMax + "个标签页", {
							icon: 2,
							time: 1000,
							shift: 6
						});
						return false;
					}
				}

				var that = this;
				if (opt.type === "_iframe") {
					element.tabAdd(this.option.elem, {
						id: opt.id,
						title: title,
						content: `<iframe id="dollar{opt.id}" type="dollar{opt.type}" data-frameid="dollar{opt.id}" scrolling="auto" frameborder="0" src="dollar{opt.url}" style="width:100%;height:100%;" allowfullscreen="true"></iframe>`
					});
				} else {
					dollar.ajax({
						url: opt.url,
						type: 'get',
						dataType: 'html',
						async: false,
						success: function (data) {
							element.tabAdd(that.option.elem, {
								id: opt.id,
								title: title,
								content: `<div id="dollar{opt.id}" type="dollar{opt.type}" data-frameid="dollar{opt.id}" src="dollar{opt.url}">dollar{data}</div>`,
							});
						},
						error: function (xhr, textstatus, thrown) {
							return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
						}
					});
				}
				tabData.push(opt);
				sessionStorage.setItem(that.option.elem + "-pear-tab-page-data", JSON.stringify(tabData));
				sessionStorage.setItem(that.option.elem + "-pear-tab-page-data-current", opt.id);
			}
		}
		element.tabChange(this.option.elem, opt.id);
		sessionStorage.setItem(this.option.elem + "-pear-tab-page-data-current", opt.id);
	}

	/**
	 * 刷新当前选型卡
	 * 
	 * @param time 动画时长
	 */
	tabPage.prototype.refresh = function (time) {

		var dollariframe = dollar(".layui-tab[lay-filter='" + this.option.elem + "'] .layui-tab-content .layui-show > *");
		var dollariframeLoad;

		if (time != false && time != 0) {
			dollariframeLoad = dollar("#" + this.option.elem).find(".pear-tab-page-loading");
			dollariframeLoad.css({
				display: "block"
			});
		}

		if (dollariframe.attr("type") === "_iframe") {
			dollariframe.attr("src", dollariframe.attr("src"));
			dollariframe.on("load", function () {
				dollariframeLoad.fadeOut(1000, function () {
					dollariframeLoad.css({
						display: "none"
					});
				});
			})
		} else {
			dollar.ajax({
				url: dollariframe.attr("src"),
				type: 'get',
				dataType: 'html',
				success: function (data) {
					dollariframe.html(data);
					if (dollariframeLoad != undefined) {
						dollariframeLoad.fadeOut(1000, function () {
							dollariframeLoad.css({
								display: "none"
							});
						});
					}
				},
				error: function (xhr) {
					return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
				}
			});
		}
	}

	function tabDelete(elem, id, callback) {
		var tabTitle = dollar(".layui-tab[lay-filter='" + elem + "']").find(".layui-tab-title");
		var removeTab = tabTitle.find("li[lay-id='" + id + "']");
		var nextNode = removeTab.next("li");
		if (!removeTab.hasClass("layui-this")) {
			removeTab.remove();
			var tabContent = dollar(".layui-tab[lay-filter='" + elem + "']").find("*[id='" + id + "']")
				.parent();
			tabContent.remove();

			tabData = JSON.parse(sessionStorage.getItem(elem + "-pear-tab-page-data"));
			tabDataCurrent = sessionStorage.getItem(elem + "-pear-tab-page-data-current");
			tabData = tabData.filter(function (item) {
				return item.id != id;
			})
			sessionStorage.setItem(elem + "-pear-tab-page-data", JSON.stringify(tabData));
			return false;
		}

		var currId;
		if (nextNode.length) {
			nextNode.addClass("layui-this");
			currId = nextNode.attr("lay-id");
			dollar("#" + elem + " [id='" + currId + "']").parent().addClass("layui-show");
		} else {
			var prevNode = removeTab.prev("li");
			prevNode.addClass("layui-this");
			currId = prevNode.attr("lay-id");
			dollar("#" + elem + " [id='" + currId + "']").parent().addClass("layui-show");
		}
		callback(currId);
		tabData = JSON.parse(sessionStorage.getItem(elem + "-pear-tab-page-data"));
		tabDataCurrent = sessionStorage.getItem(elem + "-pear-tab-page-data-current");
		tabData = tabData.filter(function (item) {
			return item.id != id;
		})
		sessionStorage.setItem(elem + "-pear-tab-page-data", JSON.stringify(tabData));
		sessionStorage.setItem(elem + "-pear-tab-page-data-current", currId);
		removeTab.remove();
		var tabContent = dollar(".layui-tab[lay-filter='" + elem + "']").find("*[id='" + id + "']").parent();
		tabContent.remove();
	}

	/**
	 * @since Pear Admin 4.0
	 */
	function createTab(option) {

		var type = "";
		if (option.roll == true) {
			type = "layui-tab-roll";
		}
		if (option.tool != false) {
			type = "layui-tab-tool";
		}
		if (option.roll == true && option.tool != false) {
			type = "layui-tab-rollTool";
		}
		var tab = '<div class="pear-tab-page ' + type + ' layui-tab" lay-filter="' + option.elem +
			'" lay-allowClose="true">';

		var headers = '<ul class="layui-tab-title">';
		var content = '<div class="layui-tab-content">';
		var loading = '<div class="pear-tab-page-loading"><div class="ball-loader"><span></span><span></span><span></span><span></span></div></div>'
		var control = `<div class="layui-tab-control">
							<li class="layui-tab-prev layui-icon layui-icon-left"></li>
							<li class="layui-tab-next layui-icon layui-icon-right"></li>
							<li class="layui-tab-tool layui-icon layui-icon-down"></li>
						</div>`;

		// 处 理 选 项 卡 头 部
		var index = 0;

		dollar.each(option.data, function (i, item) {

			var titleItem = `<li lay-id="dollar{item.id}" class="dollar{option.index == index ? 'layui-this' : ''}">
								<span class="pear-tab-page-active"></span>
								<span class="dollar{item.close ? 'able-close' : 'disable-close'} title">
									dollar{item.title}
								</span>
                                <i class="layui-icon layui-unselect layui-tab-close">ဆ</i></li>
							</li>`;

			headers += titleItem;

			if (item.type === "_iframe") {

				content += `<div class="dollar{option.index == index ? 'layui-show' : ''} layui-tab-item"><iframe id="dollar{item.id}" type="dollar{item.type}" data-frameid="dollar{item.id}" scrolling="auto" frameborder="0" src="dollar{item.url}" style="width:100%;height:100%;" allowfullscreen="true"></iframe></div>`

			} else {

				dollar.ajax({
					url: item.url,
					type: 'get',
					dataType: 'html',
					async: false,
					success: function (data) {
						content += `<div class="dollar{option.index == index ? 'layui-show' : ''} layui-tab-item"><div id="dollar{item.id}" type="dollar{item.type}" data-frameid="dollar{item.id}"  src="dollar{item.url}">dollar{data}</div></div>`;
					},
					error: function (xhr) {
						return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
					}
				});
			}

			index++;
		});

		headers += '</ul>';
		content += '</div>';

		tab += headers;
		tab += control;
		tab += content;
		tab += loading;
		tab += '</div>';
		tab += ''
		return tab;
	}

	function rollPage(d, option) {
		var dollartabTitle = dollar('#' + option.elem + '  .layui-tab-title');
		var left = dollartabTitle.scrollLeft();
		if ('left' === d) {
			dollartabTitle.animate({
				scrollLeft: left - 450
			}, 200);
		} else {
			dollartabTitle.animate({
				scrollLeft: left + 450
			}, 200);
		}
	}

	function closeEvent(option) {
		dollar(".layui-tab[lay-filter='" + option.elem + "']").on("click", ".layui-tab-close", function () {
			var layid = dollar(this).parent().attr("lay-id");
			tabDelete(option.elem, layid, option.closeEvent, option);
		})
	}

	function menuEvent(option, index) {

		dollar("#" + option.elem + "closeThis").click(function () {
			var currentTab = contextTabDOM;

			if (currentTab.find("span").is(".able-close")) {
				var currentId = currentTab.attr("lay-id");
				tabDelete(option.elem, currentId, option.closeEvent, option);
			} else {
				layer.msg("当前页面不允许关闭", {
					icon: 3,
					time: 800
				})
			}
			layer.close(index);
		})

		dollar("#" + option.elem + "closeOther").click(function () {
			var currentId = contextTabDOM.attr("lay-id");
			var tabtitle = dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title li");
			dollar.each(tabtitle, function (i) {
				if (dollar(this).attr("lay-id") != currentId) {
					if (dollar(this).find("span").is(".able-close")) {
						tabDelete(option.elem, dollar(this).attr("lay-id"), option.closeEvent,
							option);
					}
				}
			})
			layer.close(index);
		})

		dollar("#" + option.elem + "closeAll").click(function () {
			var tabtitle = dollar(".layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title li");
			dollar.each(tabtitle, function (i) {
				if (dollar(this).find("span").is(".able-close")) {
					tabDelete(option.elem, dollar(this).attr("lay-id"), option.closeEvent, option);
				}
			})
			layer.close(index);
		})
	}

	function mousewheelAndTouchmoveHandler(option) {
		var dollarbodyTab = dollar("body .layui-tab[lay-filter='" + option.elem + "'] .layui-tab-title")
		var dollartabTitle = dollar('#' + option.elem + '  .layui-tab-title');
		var mouseScrollStep = 100
		// 鼠标滚轮
		dollarbodyTab.on("mousewheel DOMMouseScroll", function (e) {
			e.originalEvent.preventDefault()
			var delta = (e.originalEvent.wheelDelta && (e.originalEvent.wheelDelta > 0 ? "top" :
				"down")) || // chrome & ie
				(e.originalEvent.detail && (e.originalEvent.detail > 0 ? "down" : "top")); // firefox
			var scrollLeft = dollartabTitle.scrollLeft();

			if (delta === "top") {
				scrollLeft -= mouseScrollStep
			} else if (delta === "down") {
				scrollLeft += mouseScrollStep
			}
			dollartabTitle.scrollLeft(scrollLeft)
		});

		// 触摸移动
		var touchX = 0;
		dollarbodyTab.on("touchstart", function (e) {
			var touch = e.originalEvent.targetTouches[0];
			touchX = touch.pageX
		})
		dollarbodyTab.on("touchmove", function (e) {
			var event = e.originalEvent;
			if (event.targetTouches.length > 1) return;
			event.preventDefault();
			var touch = event.targetTouches[0];
			var distanceX = touchX - touch.pageX
			var scrollLeft = dollartabTitle.scrollLeft();
			touchX = touch.pageX
			dollartabTitle.scrollLeft(scrollLeft += distanceX)
		});
	}

	exports(MOD_NAME, new tabPage());
})
