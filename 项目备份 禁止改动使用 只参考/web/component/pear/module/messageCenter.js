layui.define(['table', 'jquery', 'element', 'dropdown'], function (exports) {
    "use strict";

    var MOD_NAME = 'messageCenter',
        dollar = layui.jquery,
        dropdown = layui.dropdown;

    var message = function (opt) {
        this.option = opt;
    };

    message.prototype.render = function (opt) {
        var option = {
            elem: opt.elem,
            url: opt.url ? opt.url : false,
            height: opt.height,
            data: opt.data
        }
        if (option.url != false) {
            dollar.get(option.url, function (result) {
                const { code, success, data } = result;
                dollar(`dollar{opt.elem}`).append(`<li class="layui-nav-item" lay-unselect="">
                    <a href="#" class="notice layui-icon layui-icon-notice"></a>
                    </li>`);
                if (code == 200 || success) {
                    option.data = data;
                    dropdown.render({
                        elem: option.elem,
                        align: "center",
                        content: createHtml(option),
                    })
                }
            });
        }
        return new message(option);
    }

    message.prototype.click = function (callback) {
        dollar("*[notice-id]").click(function (event) {
            event.preventDefault();
            var id = dollar(this).attr("notice-id");
            var title = dollar(this).attr("notice-title");
            var context = dollar(this).attr("notice-context");
            var form = dollar(this).attr("notice-form");
            callback(id, title, context, form);
        })
    }

    function createHtml(option) {

        var count = 0;
        var notice = '<div class="pear-message-center"><div class="layui-tab layui-tab-brief">'
        var noticeTitle = '<ul class="layui-tab-title">';
        var noticeContent = '<div class="layui-tab-content" style="height:' + option.height + ';overflow-x: hidden;padding:0px;">';

        dollar.each(option.data, function (i, item) {

            noticeTitle += `<li class="dollar{i === 0 ? 'layui-this' : ''}">dollar{item.title}</li>`;
            noticeContent += '<div class="layui-tab-item layui-show">';


            dollar.each(item.children, function (i, note) {
                count++;
                noticeContent += '<div class="message-item" notice-form="' + note.form + '" notice-context="' + note.context +
                    '" notice-title="' + note.title + '" notice-id="' + note.id + '">';

                noticeContent += '<img src="' + note.avatar + '"/><div style="display:inline-block;">' + note.title + '</div>' +
                    '<div class="extra">' + note.time + '</div>' +
                    '</div>';
            })

            noticeContent += '</div>';
        })

        noticeTitle += '</ul>';
        noticeContent += '</div>';
        notice += noticeTitle;
        notice += noticeContent;
        notice += "</div></div>"

        return notice;
    }

    exports(MOD_NAME, new message());
})