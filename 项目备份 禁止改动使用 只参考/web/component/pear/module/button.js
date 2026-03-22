layui.define(['jquery'], function (exports) {
	"use strict";

	/**
	 * @since Pear Admin 4.0
	 * 
	 * Button component
	 * */
	var MOD_NAME = 'button',
		dollar = layui.jquery;

	var button = function (opt) {
		this.option = opt;
	};

	/**
	 * @since Pear Admin 4.0
	 * 
	 * Button start loading
	 * */
	button.prototype.load = function (opt) {

		var options = {
			elem: opt.elem,
			time: opt.time ? opt.time : false,
			done: opt.done ? opt.done : function () { }
		}

		var text = dollar(options.elem).html();

		dollar(options.elem).html("<i class='layui-anim layui-anim-rotate layui-icon layui-anim-loop layui-icon-loading'/>");
		dollar(options.elem).attr("disabled", "disabled");

		var dollarbutton = dollar(options.elem);

		if (options.time != "" || options.time != false) {
			setTimeout(function () {
				dollarbutton.attr("disabled", false);
				dollarbutton.html(text);
				options.done();
			}, options.time);
		}
		options.text = text;
		return new button(options);
	}

	/**
	 * @since Pear Admin 4.0
	 * 
	 * Button stop loaded
	 * */
	button.prototype.stop = function (success) {
		dollar(this.option.elem).attr("disabled", false);
		dollar(this.option.elem).html(this.option.text);
		success && success();
	}

	exports(MOD_NAME, new button());
});
