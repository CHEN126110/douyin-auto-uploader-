layui.define(['jquery', 'element'], function (exports) {
	"use strict";

	var dollar = layui.jquery;
	var element = layui.element;

	var page = function (opt) {
		this.option = opt;
	};

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 创建 Page 页面
	 */
	page.prototype.render = function (opt) {
		var option = {
			elem: opt.elem,
			url: opt.url,
			width: opt.width || "100%",
			height: opt.height || "100%",
			title: opt.title
		}
		renderContent(option);
		return new page(option);
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * 切换 Page 页面 
	 */
	page.prototype.changePage = function (options) {
		const dollarframe = dollar(`#dollar{this.option.elem} .pear-page-content`);
		if (options.type === "_iframe") {
			dollarframe.html(`<iframe src='dollar{options.href}' scrolling='auto' frameborder='0' allowfullscreen='true'></iframe>`);
		} else {
			dollar.ajax({
				url: options.href,
				type: 'get',
				dataType: 'html',
				success: function (data) {
					dollarframe.html(data)
				},
				error: function (xhr) {
					return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
				}
			});
		}
		dollarframe.attr("type", options.type);
		dollarframe.attr("href", options.href);
	}

	page.prototype.refresh = function (loading) {
		var dollarframeLoad = dollar(`#dollar{this.option.elem} .pear-page-loading`);
		var dollarframe = dollar(`#dollar{this.option.elem} .pear-page-content`);
		if (loading) {
			dollarframeLoad.css({
				display: 'block'
			});
		}
		if (dollarframe.attr("type") === "_iframe") {
			dollarframe.html(`<iframe src='dollar{dollarframe.attr("href")}' scrolling='auto' frameborder='0' allowfullscreen='true'></iframe>`);
			const dollarcontentFrame = dollarframe.find("iframe");
			dollarcontentFrame.on("load", () => {
				dollarframeLoad.fadeOut(1000);
			})
		} else {
			dollar.ajax({
				type: 'get',
				url: dollarframe.attr("href"),
				dataType: 'html',
				success: function (data) {
					dollarframe.html(data)
					dollarframeLoad.fadeOut(1000);
					element.init();
				},
				error: function (xhr) {
					return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
				}
			});
		}
	}

	function renderContent(option) {
		dollar("#" + option.elem).html(`
			<div class='pear-page'>
				<div class='pear-page-content' type='dollar{option.type}' href='dollar{option.url}'></div>
				<div class="pear-page-loading">
					<div class="ball-loader">
						<span></span>
						<span></span>
						<span></span>
						<span></span>
					</div>
				</div>
			</div>`);

		var dollarframe = dollar("#" + option.elem).find(".pear-page-content");

		if (option.type === "_iframe") {
			dollarframe.html(`<iframe src='dollar{option.url}' scrolling='auto' frameborder='0' allowfullscreen='true'></iframe>`);
		} else {
			dollar.ajax({
				url: option.url,
				type: 'get',
				dataType: 'html',
				success: function (data) {
					dollarframe.html(data);
				},
				error: function (xhr) {
					return layer.msg('Status:' + xhr.status + ',' + xhr.statusText + ',请稍后再试!');
				}
			});
		}
	}

	exports('page', new page());
});